import json
import time
import webbrowser
from pathlib import Path
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

import httpx

REDIRECT_PORT = 3000
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"


class _CallbackHandler(BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    event = threading.Event()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]

        if error:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization failed.")
            return

        if code:
            self.__class__.auth_code = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization successful! You can close this tab.")
            self.__class__.event.set()
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code received.")

    def log_message(self, *a, **k):
        pass


class TwitchAuth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        data_dir: str,
        redirect_uri: str = REDIRECT_URI,
        scopes: list[str] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes or ["clips:edit"]
        self.token_file = Path(data_dir) / "twitch_user_token.json"
        self._app_token: Optional[str] = None
        self._user_token: Optional[str] = None
        self._token_expires: float = 0

    def get_app_token(self) -> str:
        if self._app_token and time.time() < self._token_expires:
            return self._app_token
        resp = httpx.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._app_token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600)
        return self._app_token

    def get_auth_url(self) -> str:
        scope_str = "+".join(self.scopes)
        return (
            f"https://id.twitch.tv/oauth2/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&response_type=code"
            f"&scope={scope_str}"
        )

    def exchange_code(self, code: str) -> str:
        resp = httpx.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        refresh = data.get("refresh_token", "")
        expires_in = data.get("expires_in", 3600)
        self._save_token(token, refresh, expires_in)
        self._user_token = token
        return token

    def _save_token(self, token: str, refresh: str, expires_in: int) -> None:
        data = {
            "access_token": token,
            "refresh_token": refresh,
            "expires_at": time.time() + expires_in,
        }
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps(data, indent=2))

    def _load_token(self) -> Optional[dict]:
        if self.token_file.exists():
            try:
                return json.loads(self.token_file.read_text())
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def get_user_token(self) -> Optional[str]:
        if self._user_token:
            return self._user_token
        data = self._load_token()
        if data:
            if time.time() < data.get("expires_at", 0):
                self._user_token = data["access_token"]
                return self._user_token
            if data.get("refresh_token"):
                return self._refresh_token(data["refresh_token"])
        return None

    def _refresh_token(self, refresh_token: str) -> Optional[str]:
        try:
            resp = httpx.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._save_token(
                data["access_token"],
                data.get("refresh_token", refresh_token),
                data.get("expires_in", 3600),
            )
            self._user_token = data["access_token"]
            return self._user_token
        except httpx.HTTPError:
            return None

    def is_authenticated(self) -> bool:
        return self.get_user_token() is not None

    def open_auth_url(self) -> str:
        url = self.get_auth_url()
        print(f"\n[TWITCH AUTH] Abrindo navegador...")
        webbrowser.open(url)
        return url

    def login_with_server(self) -> Optional[str]:
        _CallbackHandler.auth_code = None
        _CallbackHandler.event.clear()
        server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        url = self.get_auth_url()
        print(f"\n[TWITCH AUTH] Abrindo navegador...")
        print(f"[TWITCH AUTH] Aguardando autorização em {REDIRECT_URI} ...")
        webbrowser.open(url)

        _CallbackHandler.event.wait(timeout=120)
        server.shutdown()
        code = _CallbackHandler.auth_code
        if not code:
            print("[TWITCH AUTH] Timeout ou cancelado")
            return None
        return self.exchange_code(code)
