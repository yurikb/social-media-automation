import json
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Event, Thread
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx

REDIRECT_PORT = 3002
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


class InstagramAuth:
    SCOPES = [
        "instagram_basic",
        "instagram_content_publish",
        "pages_show_list",
    ]

    def __init__(self, app_id: str, app_secret: str, data_dir: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token_file = Path(data_dir) / "instagram_token.json"

    @property
    def auth_url(self) -> str:
        scope_str = ",".join(self.SCOPES)
        return (
            "https://www.facebook.com/v22.0/dialog/oauth"
            f"?client_id={self.app_id}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope={scope_str}"
        )

    def login(self) -> Optional[str]:
        _CallbackHandler.auth_code = None
        _CallbackHandler.event.clear()
        server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        webbrowser.open(self.auth_url)
        print(f"[INSTAGRAM AUTH] Waiting for callback on {REDIRECT_URI}...")
        _CallbackHandler.event.wait(timeout=120)
        server.shutdown()

        code = _CallbackHandler.auth_code
        if not code:
            return None
        return self._exchange_code(code)

    def _exchange_code(self, code: str) -> str:
        resp = httpx.get(
            "https://graph.facebook.com/v22.0/oauth/access_token",
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": REDIRECT_URI,
                "code": code,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        short_token = data["access_token"]
        long_token = self._exchange_long_token(short_token)
        if long_token:
            self._save(long_token)
            return long_token
        self._save(short_token)
        return short_token

    def _exchange_long_token(self, short_token: str) -> Optional[str]:
        try:
            resp = httpx.get(
                "https://graph.facebook.com/v22.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "fb_exchange_token": short_token,
                },
            )
            resp.raise_for_status()
            return resp.json().get("access_token")
        except httpx.HTTPError:
            return None

    def _save(self, token: str) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({
            "access_token": token,
            "expires_at": time.time() + 5184000,
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
        return None

    def is_authenticated(self) -> bool:
        return self.get_token() is not None

    def get_pages(self) -> list[dict]:
        token = self.get_token()
        if not token:
            return []
        resp = httpx.get(
            "https://graph.facebook.com/v22.0/me/accounts",
            params={"access_token": token},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])

    def get_instagram_account(self, page_id: str) -> Optional[dict]:
        token = self.get_token()
        if not token:
            return None
        resp = httpx.get(
            f"https://graph.facebook.com/v22.0/{page_id}",
            params={"fields": "instagram_business_account", "access_token": token},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("instagram_business_account")


SERVE_PORT = 3003


class _VideoServer(BaseHTTPRequestHandler):
    video_path: str = ""

    def do_GET(self):
        if not self.__class__.video_path or not Path(self.__class__.video_path).exists():
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.end_headers()
        with open(self.__class__.video_path, "rb") as f:
            self.wfile.write(f.read())

    def log_message(self, *a, **k):
        pass


class InstagramPublisher:
    def __init__(self, auth: InstagramAuth, public_base_url: str = ""):
        self.auth = auth
        self.public_base_url = public_base_url

    def publish(self, video_path: str, caption: str) -> Optional[str]:
        token = self.auth.get_token()
        if not token:
            return None

        pages = self.auth.get_pages()
        if not pages:
            print("[INSTAGRAM] No Facebook pages found")
            return None

        ig = None
        for page in pages:
            ig = self.auth.get_instagram_account(page["id"])
            if ig:
                break

        if not ig:
            print("[INSTAGRAM] No Instagram business account linked")
            return None

        ig_id = ig["id"]

        video_url = self._serve_video(video_path)
        if not video_url:
            print("[INSTAGRAM] No public URL available to serve video")
            return None

        media = self._create_media(ig_id, video_url, caption, token)
        if not media:
            return None

        creation_id = media.get("id")
        if not creation_id:
            print("[INSTAGRAM] No creation ID returned")
            return None

        status = self._poll_status(ig_id, creation_id, token)
        if not status:
            return None

        return self._publish_media(ig_id, creation_id, token)

    def _serve_video(self, video_path: str) -> Optional[str]:
        if self.public_base_url:
            _VideoServer.video_path = video_path
            return f"{self.public_base_url.rstrip('/')}/instagram_video"
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        _VideoServer.video_path = video_path
        server = HTTPServer(("0.0.0.0", SERVE_PORT), _VideoServer)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return f"http://{local_ip}:{SERVE_PORT}/instagram_video"

    def _create_media(self, ig_id: str, video_url: str, caption: str,
                      token: str) -> Optional[dict]:
        resp = httpx.post(
            f"https://graph.facebook.com/v22.0/{ig_id}/media",
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "access_token": token,
            },
            timeout=120,
        )
        if resp.status_code == 400:
            print(f"[INSTAGRAM] Create media failed: {resp.text}")
            return None
        resp.raise_for_status()
        return resp.json()

    def _poll_status(self, ig_id: str, creation_id: str, token: str,
                     max_retries: int = 30) -> bool:
        for _ in range(max_retries):
            resp = httpx.get(
                f"https://graph.facebook.com/v22.0/{creation_id}",
                params={
                    "fields": "status_code",
                    "access_token": token,
                },
            )
            if resp.status_code == 200:
                status = resp.json().get("status_code", "")
                if status == "FINISHED":
                    return True
                if status == "ERROR":
                    print(f"[INSTAGRAM] Media processing failed")
                    return False
            time.sleep(2)
        print("[INSTAGRAM] Media processing timed out")
        return False

    def _publish_media(self, ig_id: str, creation_id: str, token: str) -> Optional[str]:
        resp = httpx.post(
            f"https://graph.facebook.com/v22.0/{ig_id}/media_publish",
            params={
                "creation_id": creation_id,
                "access_token": token,
            },
            timeout=30,
        )
        if resp.status_code == 400:
            print(f"[INSTAGRAM] Publish failed: {resp.text}")
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("id")
