import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.services.youtube_upload import YouTubeAuth, YouTubeUploader


class TestYouTubeAuth:
    def test_auth_url_contains_scopes(self):
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir="/tmp")
        url = auth.auth_url
        assert "client_id=test_id" in url
        assert "youtube.upload" in url
        assert "youtube.readonly" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url

    def test_is_authenticated_returns_false_without_token(self, tmp_path):
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        assert not auth.is_authenticated()

    def test_is_authenticated_returns_true_with_valid_token(self, tmp_path):
        data = {"access_token": "valid", "refresh_token": "refresh", "expires_at": time.time() + 3600}
        Path(tmp_path / "youtube_token.json").write_text(json.dumps(data))
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        assert auth.is_authenticated()
        assert auth.get_token() == "valid"

    def test_get_token_returns_none_for_expired_token(self, tmp_path):
        data = {"access_token": "expired", "refresh_token": "refresh", "expires_at": time.time() - 100}
        Path(tmp_path / "youtube_token.json").write_text(json.dumps(data))
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        assert auth.is_authenticated() is False

    def test_save_and_load_token(self, tmp_path):
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        auth._save("token123", "refresh123", 3600)
        assert Path(tmp_path / "youtube_token.json").exists()
        data = json.loads(Path(tmp_path / "youtube_token.json").read_text())
        assert data["access_token"] == "token123"
        assert data["refresh_token"] == "refresh123"

    @patch("httpx.post")
    def test_exchange_code(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "access_token": "new_token", "refresh_token": "new_refresh", "expires_in": 3600,
        })
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        result = auth._exchange_code("auth_code_123")
        assert result == "new_token"
        assert Path(tmp_path / "youtube_token.json").exists()

    @patch("httpx.post")
    def test_refresh_token(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "access_token": "refreshed_token", "expires_in": 3600,
        })
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        result = auth._refresh("old_refresh")
        assert result == "refreshed_token"

    @patch("httpx.get")
    def test_get_channel_info(self, mock_get, tmp_path):
        data = {"access_token": "valid", "refresh_token": "r", "expires_at": time.time() + 3600}
        Path(tmp_path / "youtube_token.json").write_text(json.dumps(data))
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {
            "items": [{"id": "UC123", "snippet": {"title": "My Channel"}}],
        })
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        info = auth.get_channel_info()
        assert info["id"] == "UC123"
        assert info["snippet"]["title"] == "My Channel"

    def test_get_channel_info_no_auth(self, tmp_path):
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        assert auth.get_channel_info() == {}


class TestYouTubeUploader:
    def test_publish_returns_none_without_auth(self, tmp_path):
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        uploader = YouTubeUploader(auth)
        result = uploader.publish(video_path="nonexistent.mp4", title="Test")
        assert result is None

    @patch("httpx.post")
    def test_publish_success(self, mock_post, tmp_path):
        data = {"access_token": "valid", "refresh_token": "r", "expires_at": time.time() + 3600}
        Path(tmp_path / "youtube_token.json").write_text(json.dumps(data))
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        uploader = YouTubeUploader(auth)

        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video content")
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"id": "video123"})
        result = uploader.publish(video_path=str(video), title="Test Video", description="Test desc", tags=["game", "clip"])
        assert result == "video123"
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer valid"

    @patch("httpx.post")
    def test_publish_retry_on_401(self, mock_post, tmp_path):
        data = {"access_token": "expired", "refresh_token": "r", "expires_at": time.time() + 3600}
        Path(tmp_path / "youtube_token.json").write_text(json.dumps(data))
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))

        def _get_token():
            return "new_token"
        auth.get_token = _get_token

        uploader = YouTubeUploader(auth)
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        mock_post.side_effect = [
            MagicMock(status_code=401, json=lambda: {"error": "unauthorized"}),
            MagicMock(status_code=200, json=lambda: {"id": "video456"}),
        ]
        result = uploader.publish(video_path=str(video), title="Test")
        assert result == "video456"

    @patch("httpx.post")
    def test_publish_handles_403(self, mock_post, tmp_path):
        data = {"access_token": "valid", "refresh_token": "r", "expires_at": time.time() + 3600}
        Path(tmp_path / "youtube_token.json").write_text(json.dumps(data))
        auth = YouTubeAuth(client_id="test_id", client_secret="test_secret", data_dir=str(tmp_path))
        uploader = YouTubeUploader(auth)
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        mock_post.return_value = MagicMock(status_code=403, json=lambda: {"error": "quotaExceeded"})
        result = uploader.publish(video_path=str(video), title="Test")
        assert result is None

    def test_build_multipart(self, tmp_path):
        auth = YouTubeAuth(client_id="id", client_secret="secret", data_dir=str(tmp_path))
        uploader = YouTubeUploader(auth)
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video data here")
        boundary = "testboundary123"
        body = uploader._build_multipart(
            {"snippet": {"title": "Test"}, "status": {"privacyStatus": "public"}},
            str(video), boundary,
        )
        assert boundary.encode() in body
        assert b"video/mp4" in body
        assert b"video data here" in body
        assert b"application/json" in body
        assert b'"privacyStatus": "public"' in body
