"""
TikTok Content Posting API v2 upload service.

Simple public interface::

    result = upload_video("video.mp4", "My Title", tags=["gaming"])
    if result:
        print(result["video_id"], result["url"])

Uses OAuth2 token from ``data/tiktok_token.json`` (auto-refreshed).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _load_token(data_dir: str) -> Optional[dict[str, Any]]:
    """Load the persisted token dict from *data_dir*/tiktok_token.json."""
    token_file = Path(data_dir) / "tiktok_token.json"
    if not token_file.exists():
        return None
    try:
        return json.loads(token_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_token(token_data: dict[str, Any], data_dir: str) -> None:
    """Persist *token_data* to *data_dir*/tiktok_token.json."""
    token_file = Path(data_dir) / "tiktok_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(
        json.dumps(token_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _get_valid_token(
    client_key: str, client_secret: str, data_dir: str
) -> Optional[str]:
    """Return a valid access token, refreshing the stored token if needed."""
    token = _load_token(data_dir)
    if not token:
        return None

    access_token = token.get("access_token")
    if not access_token:
        return None

    # Still fresh (use 60 s buffer)
    if time.time() < token.get("expires_at", 0) - 60:
        return access_token

    # Expired — try refresh
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        return None

    try:
        resp = httpx.post(
            f"{_TIKTOK_API_BASE}/oauth/token/",
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        new_token: dict[str, Any] = {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token", refresh_token),
            "expires_at": time.time() + body.get("expires_in", 86400),
        }
        _save_token(new_token, data_dir)
        return body["access_token"]
    except httpx.HTTPError as exc:
        print(f"[TIKTOK] Token refresh failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------


def _init_upload(
    access_token: str, file_size: int
) -> Optional[dict[str, Any]]:
    """Initialize a TikTok video upload session.

    Returns a dict with ``upload_url`` and ``publish_id``, or ``None``.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    payload = {
        "source_info": {
            "source_type": 1,  # file_upload
            "video_size": file_size,
            "chunk_count": 1,
            "chunk_size": file_size,
        },
    }
    try:
        resp = httpx.post(
            f"{_TIKTOK_API_BASE}/video/upload/init/",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except httpx.RequestError as exc:
        print(f"[TIKTOK] Init upload network error: {exc}")
        return None

    # 401 — token stale, caller should retry
    if resp.status_code == 401:
        print("[TIKTOK] Auth failure during init — token may be invalid.")
        return None
    if resp.status_code == 429:
        print("[TIKTOK] Rate limited during init.")
        return None
    if resp.is_error:
        body = _safe_text(resp)
        print(f"[TIKTOK] Init upload HTTP {resp.status_code}: {body}")
        return None

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"[TIKTOK] Invalid JSON in init response: {resp.text[:200]}")
        return None

    info = data.get("data") or {}
    if not info.get("upload_url") or not info.get("publish_id"):
        print(f"[TIKTOK] Missing upload_url or publish_id in init response: {info}")
        return None
    return info


def _upload_file(upload_url: str, video_path: str) -> bool:
    """Upload the video binary to the pre-signed URL (PUT)."""
    try:
        video_bytes = Path(video_path).read_bytes()
    except OSError as exc:
        print(f"[TIKTOK] Failed to read video file: {exc}")
        return False

    try:
        resp = httpx.put(upload_url, content=video_bytes, timeout=600)
    except httpx.RequestError as exc:
        print(f"[TIKTOK] File upload network error: {exc}")
        return False

    if resp.status_code == 429:
        print("[TIKTOK] Rate limited during file upload.")
        return False
    if resp.is_error:
        print(f"[TIKTOK] File upload HTTP {resp.status_code}: {resp.text[:300]}")
        return False

    return True


def _complete_upload(access_token: str, publish_id: str) -> bool:
    """Mark the upload as complete so TikTok starts processing."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    payload = {"publish_id": publish_id}
    try:
        resp = httpx.post(
            f"{_TIKTOK_API_BASE}/video/upload/complete/",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except httpx.RequestError as exc:
        print(f"[TIKTOK] Complete upload network error: {exc}")
        return False

    if resp.is_error:
        print(f"[TIKTOK] Complete upload HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    return True


def _poll_upload_status(access_token: str, publish_id: str) -> bool:
    """Poll until the upload is processed or fails (up to ~60 s)."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    for _attempt in range(30):
        try:
            resp = httpx.post(
                f"{_TIKTOK_API_BASE}/video/upload/status/",
                headers=headers,
                json={"publish_id": publish_id},
                timeout=30,
            )
        except httpx.RequestError:
            time.sleep(2)
            continue

        if resp.is_error:
            time.sleep(2)
            continue

        try:
            data = resp.json()
            status = (data.get("data") or {}).get("status")
            if status == "COMPLETE":
                return True
            if status == "FAILED":
                err = (data.get("data") or {}).get("error", {})
                msg = err.get("message", "Unknown error")
                print(f"[TIKTOK] Upload processing failed: {msg}")
                return False
        except (json.JSONDecodeError, KeyError):
            pass

        time.sleep(2)

    print("[TIKTOK] Upload status check timed out")
    return False


def _publish_video(
    access_token: str,
    publish_id: str,
    title: str,
    description: str,
    privacy_level: int,
) -> Optional[str]:
    """Publish the uploaded video with metadata and return the video ID."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    payload = {
        "publish_id": publish_id,
        "post_info": {
            "title": title,
            "description": description,
            "privacy_level": privacy_level,
        },
    }
    try:
        resp = httpx.post(
            f"{_TIKTOK_API_BASE}/video/publish/",
            headers=headers,
            json=payload,
            timeout=60,
        )
    except httpx.RequestError as exc:
        print(f"[TIKTOK] Publish network error: {exc}")
        return None

    if resp.status_code == 401:
        print("[TIKTOK] Auth failure during publish — token may be stale.")
        return None
    if resp.status_code == 429:
        print("[TIKTOK] Rate limited during publish.")
        return None
    if resp.status_code == 403:
        print(f"[TIKTOK] Quota / permission error: {resp.text[:300]}")
        return None
    if resp.is_error:
        print(f"[TIKTOK] Publish HTTP {resp.status_code}: {resp.text[:300]}")
        return None

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"[TIKTOK] Invalid JSON in publish response: {resp.text[:200]}")
        return None

    video_id = (data.get("data") or {}).get("video_id")
    if not video_id:
        # Fallback: use publish_id so the caller still gets something
        video_id = publish_id

    return str(video_id)


def _safe_text(resp: httpx.Response) -> str:
    """Return up to 300 chars of response text, safely."""
    try:
        return resp.text[:300]
    except Exception:
        return f"<status {resp.status_code}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def upload_video(
    file_path: str,
    title: str,
    description: str = "",
    tags: Optional[list[str]] = None,
    privacy: str = "private",
    **kwargs: Any,
) -> Optional[dict[str, str]]:
    """Upload a video to TikTok via the Content Posting API v2.

    OAuth2 credentials are read from ``data/tiktok_token.json`` and
    refreshed automatically when expired.

    Parameters
    ----------
    file_path:
        Absolute or relative path to the video file (e.g. ``.mp4``).
    title:
        Video title.
    description:
        Video description (optional).
    tags:
        List of keyword tags (optional).  Each tag is converted to a
        hashtag and appended to the description.
    privacy:
        Privacy status — ``"private"`` (default) or ``"public"``.

    Returns
    -------
    A dict ``{"video_id": str, "url": str}`` on success, or ``None`` on
    failure.

    Extra keyword arguments (``client_key``, ``client_secret``,
    ``data_dir``) are accepted for backward compatibility with the
    existing CLI code.
    """
    # Resolve optional overrides
    client_key = kwargs.get("client_key") or os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = kwargs.get("client_secret") or os.environ.get(
        "TIKTOK_CLIENT_SECRET", ""
    )
    data_dir = kwargs.get("data_dir") or str(_DATA_DIR)

    # --- Validate inputs ---------------------------------------------------

    if not client_key or not client_secret:
        msg = (
            "[TIKTOK] TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET must be set "
            "in the environment or passed as extra kwargs."
        )
        print(msg)
        return None

    video_path = Path(file_path)
    if not video_path.exists():
        print(f"[TIKTOK] File not found: {file_path}")
        return None

    # --- Obtain a valid token ----------------------------------------------

    token = _get_valid_token(client_key, client_secret, data_dir)
    if not token:
        print("[TIKTOK] Not authenticated — token missing or expired.")
        return None

    # --- Privacy mapping ---------------------------------------------------

    privacy_level = 0  # public
    if privacy == "private":
        privacy_level = 1
    elif privacy == "friends":
        privacy_level = 2

    # --- Build full description with inline hashtags -----------------------

    full_description = description or ""
    if tags:
        tag_str = " ".join(
            f"#{t}" if not t.startswith("#") else t for t in tags
        )
        if full_description:
            full_description += "\n\n" + tag_str
        else:
            full_description = tag_str

    file_size = video_path.stat().st_size

    # --- Step 1: Initialize upload -----------------------------------------

    print(
        f"[TIKTOK] Initializing upload for {video_path.name} "
        f"({file_size} bytes)..."
    )
    init_data = _init_upload(token, file_size)
    if not init_data:
        return None

    upload_url = init_data["upload_url"]
    publish_id = init_data["publish_id"]

    # --- Step 2: Upload file binary ----------------------------------------

    print("[TIKTOK] Uploading video file...")
    if not _upload_file(upload_url, file_path):
        return None

    # --- Step 3: Mark upload as complete -----------------------------------

    print("[TIKTOK] Completing upload...")
    if not _complete_upload(token, publish_id):
        return None

    # --- Step 4: Wait for processing ---------------------------------------

    print("[TIKTOK] Waiting for processing...")
    if not _poll_upload_status(token, publish_id):
        return None

    # --- Step 5: Publish with metadata -------------------------------------

    print("[TIKTOK] Publishing video...")
    video_id = _publish_video(
        token, publish_id, title, full_description, privacy_level
    )
    if not video_id:
        print("[TIKTOK] Publish failed.")
        return None

    return {
        "video_id": video_id,
        "url": f"https://www.tiktok.com/video/{video_id}",
    }
