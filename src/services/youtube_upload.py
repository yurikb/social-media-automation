import json
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Event, Thread
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx

REDIRECT_PORT = 3011
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"


class _CallbackHandler(BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    event = Event()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        if error:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Auth failed.")
            return
        if code:
            self.__class__.auth_code = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"You can close this tab.")
            self.__class__.event.set()
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code.")

    def log_message(self, *a, **k):
        pass


class YouTubeAuth:
    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    def __init__(self, client_id: str, client_secret: str, data_dir: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = Path(data_dir) / "youtube_token.json"

    @property
    def auth_url(self) -> str:
        scope_str = "+".join(self.SCOPES)
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={self.client_id}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope={scope_str}"
            f"&access_type=offline"
            f"&prompt=consent"
        )

    def login(self) -> Optional[str]:
        _CallbackHandler.auth_code = None
        _CallbackHandler.event.clear()
        server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        print(f"\n[YOUTUBE AUTH] Opening browser for authorization...")
        webbrowser.open(self.auth_url)
        print(f"[YOUTUBE AUTH] Waiting for callback on {REDIRECT_URI}...")
        _CallbackHandler.event.wait(timeout=120)
        server.shutdown()

        code = _CallbackHandler.auth_code
        if not code:
            print("[YOUTUBE AUTH] Timeout or cancelled")
            return None
        return self._exchange_code(code)

    def _exchange_code(self, code: str) -> str:
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        refresh = data.get("refresh_token", "")
        self._save(token, refresh, data.get("expires_in", 3600))
        return token

    def _save(self, token: str, refresh: str, expires_in: int) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({
            "access_token": token,
            "refresh_token": refresh,
            "expires_at": time.time() + expires_in,
        }, indent=2))

    def get_token(self) -> Optional[str]:
        if not self.token_file.exists():
            return None
        try:
            data = json.loads(self.token_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() < data.get("expires_at", 0):
            return data["access_token"]
        if data.get("refresh_token"):
            return self._refresh(data["refresh_token"])
        return None

    def _refresh(self, refresh_token: str) -> Optional[str]:
        try:
            resp = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._save(data["access_token"], refresh_token, data.get("expires_in", 3600))
            return data["access_token"]
        except httpx.HTTPError:
            return None

    def is_authenticated(self) -> bool:
        return self.get_token() is not None

    def get_channel_info(self) -> dict:
        token = self.get_token()
        if not token:
            return {}
        resp = httpx.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("items"):
            return data["items"][0]
        return {}


class YouTubeUploader:
    def __init__(self, auth: YouTubeAuth):
        self.auth = auth
        self.api = "https://www.googleapis.com/upload/youtube/v3/videos"

    def publish(self, video_path: str, title: str, description: str = "",
                tags: list[str] = None, category_id: str = "22") -> Optional[str]:
        token = self.auth.get_token()
        if not token:
            return None

        import os
        file_size = os.path.getsize(video_path)

        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags or [],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        boundary = "----boundary" + os.urandom(16).hex()
        body = self._build_multipart(metadata, video_path, boundary)

        resp = httpx.post(
            f"{self.api}?part=snippet,status",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f'multipart/related; boundary="{boundary}"',
            },
            content=body,
            timeout=600,
        )

        if resp.status_code == 401:
            new_token = self.auth.get_token()
            if new_token:
                resp = httpx.post(
                    f"{self.api}?part=snippet,status",
                    headers={
                        "Authorization": f"Bearer {new_token}",
                        "Content-Type": f'multipart/related; boundary="{boundary}"',
                    },
                    content=body,
                    timeout=600,
                )
        if resp.status_code == 403:
            print(f"[YOUTUBE] Quota exceeded or permission denied: {resp.text}")
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("id")

    def _build_multipart(self, metadata: dict, video_path: str, boundary: str) -> bytes:
        import json as _json
        parts = []
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
        parts.append(_json.dumps(metadata).encode())
        parts.append(b"\r\n")
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(b"Content-Type: video/mp4\r\n\r\n")
        with open(video_path, "rb") as f:
            parts.append(f.read())
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)
