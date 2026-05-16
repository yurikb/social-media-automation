"""
YouTube Data API v3 upload service.

Simple public interface::

    result = upload_video("video.mp4", "My Title", tags=["gaming"])
    if result:
        print(result["video_id"], result["url"])

Uses OAuth2 token from ``data/youtube_token.json`` (auto-refreshed).
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

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _load_token(data_dir: str) -> Optional[dict[str, Any]]:
    """Load the persisted token dict from *data_dir*/youtube_token.json."""
    token_file = Path(data_dir) / "youtube_token.json"
    if not token_file.exists():
        return None
    try:
        return json.loads(token_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_token(token_data: dict[str, Any], data_dir: str) -> None:
    """Persist *token_data* to *data_dir*/youtube_token.json."""
    token_file = Path(data_dir) / "youtube_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(json.dumps(token_data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_valid_token(client_id: str, client_secret: str, data_dir: str) -> Optional[str]:
    """Return a valid access token, refreshing the stored token if needed."""
    token = _load_token(data_dir)
    if not token:
        return None

    access_token = token.get("access_token")
    if not access_token:
        return None

    # Still fresh
    if time.time() < token.get("expires_at", 0):
        return access_token

    # Expired — try refresh
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        return None

    try:
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        new_token: dict[str, Any] = {
            "access_token": body["access_token"],
            "refresh_token": refresh_token,
            "expires_at": time.time() + body.get("expires_in", 3600),
        }
        _save_token(new_token, data_dir)
        return body["access_token"]
    except httpx.HTTPError:
        return None


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------


def _build_multipart(metadata: dict[str, Any], video_path: str, boundary: str) -> bytes:
    """Build a multipart/related request body (JSON metadata + binary video)."""
    parts = [
        f"--{boundary}\r\n".encode(),
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
        json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b"Content-Type: video/*\r\n\r\n",
        Path(video_path).read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts)


# ---------------------------------------------------------------------------
# YouTubeAuth  — kept for backward compatibility with cli.py
# ---------------------------------------------------------------------------


class YouTubeAuth:
    """YouTube OAuth2 authentication (backward-compatible wrapper)."""

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    def __init__(self, client_id: str, client_secret: str, data_dir: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = Path(data_dir) / "youtube_token.json"

    def get_token(self) -> Optional[str]:
        return _get_valid_token(self.client_id, self.client_secret, str(self.token_file.parent))

    def is_authenticated(self) -> bool:
        return self.get_token() is not None


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
    """Upload a video to YouTube via the Data API v3.

    OAuth2 credentials are read from ``data/youtube_token.json`` and
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
        List of keyword tags (optional).
    privacy:
        Privacy status — ``"private"`` (default), ``"unlisted"``, or
        ``"public"``.

    Returns
    -------
    A dict ``{"video_id": str, "url": str}`` on success, or ``None`` on
    failure.

    Extra keyword arguments (``client_id``, ``client_secret``,
    ``data_dir``) are accepted for backward compatibility with the
    existing CLI code.
    """
    # Resolve optional overrides
    client_id = kwargs.get("client_id") or os.environ.get("YOUTUBE_CLIENT_ID", "")
    client_secret = kwargs.get("client_secret") or os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    data_dir = kwargs.get("data_dir") or str(_DATA_DIR)

    # --- Validate inputs ---------------------------------------------------

    if not client_id or not client_secret:
        msg = (
            "[YOUTUBE] YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set "
            "in the environment or passed as extra kwargs."
        )
        print(msg)
        return None

    video_path = Path(file_path)
    if not video_path.exists():
        print(f"[YOUTUBE] File not found: {file_path}")
        return None

    # --- Obtain a valid token ----------------------------------------------

    token = _get_valid_token(client_id, client_secret, data_dir)
    if not token:
        print("[YOUTUBE] Not authenticated — token missing or expired.")
        return None

    # --- Build request -----------------------------------------------------

    metadata: dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description or "",
            "tags": tags or [],
            "categoryId": "22",  # Gaming
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    boundary = "----boundary" + os.urandom(16).hex()
    body = _build_multipart(metadata, file_path, boundary)
    api_url = "https://www.googleapis.com/upload/youtube/v3/videos?part=snippet,status"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f'multipart/related; boundary="{boundary}"',
    }

    # --- Send upload request -----------------------------------------------

    try:
        resp = httpx.post(api_url, headers=headers, content=body, timeout=600)
    except httpx.RequestError as exc:
        print(f"[YOUTUBE] Network error: {exc}")
        return None

    # Retry once on 401 (stale token)
    if resp.status_code == 401:
        new_token = _get_valid_token(client_id, client_secret, data_dir)
        if new_token:
            headers["Authorization"] = f"Bearer {new_token}"
            try:
                resp = httpx.post(api_url, headers=headers, content=body, timeout=600)
            except httpx.RequestError as exc:
                print(f"[YOUTUBE] Network error on retry: {exc}")
                return None

    if resp.status_code == 403:
        print(f"[YOUTUBE] Quota / permission error: {resp.text}")
        return None

    if resp.is_error:
        print(f"[YOUTUBE] HTTP {resp.status_code}: {resp.text}")
        return None

    # --- Parse response ----------------------------------------------------

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"[YOUTUBE] Invalid JSON in response: {resp.text[:500]}")
        return None

    video_id = data.get("id")
    if not video_id:
        print(f"[YOUTUBE] No video ID in response: {data}")
        return None

    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }
