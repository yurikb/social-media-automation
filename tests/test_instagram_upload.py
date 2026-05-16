import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.services.instagram_upload import InstagramAuth, InstagramPublisher


class TestInstagramAuth:
    def test_auth_url_contains_scopes(self):
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir="/tmp")
        url = auth.auth_url
        assert "client_id=test_app" in url
        assert "instagram_basic" in url
        assert "instagram_content_publish" in url
        assert "pages_show_list" in url

    def test_is_authenticated_returns_false_without_token(self, tmp_path):
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        assert not auth.is_authenticated()

    def test_is_authenticated_with_valid_token(self, tmp_path):
        data = {"access_token": "valid_token", "expires_at": time.time() + 5000000}
        Path(tmp_path / "instagram_token.json").write_text(json.dumps(data))
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        assert auth.is_authenticated()
        assert auth.get_token() == "valid_token"

    def test_expired_token_returns_none(self, tmp_path):
        data = {"access_token": "expired", "expires_at": time.time() - 1000}
        Path(tmp_path / "instagram_token.json").write_text(json.dumps(data))
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        assert not auth.is_authenticated()
        assert auth.get_token() is None

    def test_save_token(self, tmp_path):
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        auth._save("saved_token")
        assert Path(tmp_path / "instagram_token.json").exists()
        data = json.loads(Path(tmp_path / "instagram_token.json").read_text())
        assert data["access_token"] == "saved_token"

    @patch("httpx.get")
    def test_exchange_code(self, mock_get, tmp_path):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "short_token"})
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        with patch.object(auth, '_exchange_long_token', return_value=None):
            result = auth._exchange_code("code_123")
            assert result == "short_token"
            assert Path(tmp_path / "instagram_token.json").exists()

    @patch("httpx.get")
    def test_exchange_long_token(self, mock_get, tmp_path):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "long_lived_token"})
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        result = auth._exchange_long_token("short_token")
        assert result == "long_lived_token"

    def test_exchange_long_token_fails(self, tmp_path):
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        with patch("httpx.get") as mock_get:
            mock_get.side_effect = httpx.HTTPError("fail")
            result = auth._exchange_long_token("short_token")
            assert result is None

    @patch("httpx.get")
    def test_get_pages(self, mock_get, tmp_path):
        data = {"access_token": "valid", "expires_at": time.time() + 5000000}
        Path(tmp_path / "instagram_token.json").write_text(json.dumps(data))
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {
            "data": [{"id": "page123", "name": "My Page"}],
        })
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        pages = auth.get_pages()
        assert len(pages) == 1
        assert pages[0]["id"] == "page123"

    def test_get_pages_no_auth(self, tmp_path):
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        assert auth.get_pages() == []

    @patch("httpx.get")
    def test_get_instagram_account(self, mock_get, tmp_path):
        data = {"access_token": "valid", "expires_at": time.time() + 5000000}
        Path(tmp_path / "instagram_token.json").write_text(json.dumps(data))
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {
            "instagram_business_account": {"id": "ig123"},
        })
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        ig = auth.get_instagram_account("page123")
        assert ig["id"] == "ig123"

    def test_get_instagram_account_no_auth(self, tmp_path):
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        assert auth.get_instagram_account("page123") is None


class TestInstagramPublisher:
    def test_publish_returns_none_without_auth(self, tmp_path):
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        publisher = InstagramPublisher(auth)
        result = publisher.publish(video_path="test.mp4", caption="Test")
        assert result is None

    @patch("httpx.get")
    @patch("httpx.post")
    def test_publish_full_flow(self, mock_post, mock_get, tmp_path):
        token_data = {"access_token": "valid", "expires_at": time.time() + 5000000}
        Path(tmp_path / "instagram_token.json").write_text(json.dumps(token_data))
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))

        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: {"data": [{"id": "page123"}]}),
            MagicMock(status_code=200, json=lambda: {"instagram_business_account": {"id": "ig123"}}),
            MagicMock(status_code=200, json=lambda: {"status_code": "FINISHED"}),
        ]
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"id": "media_container_1"}),
            MagicMock(status_code=200, json=lambda: {"id": "published_media_1"}),
        ]

        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        publisher = InstagramPublisher(auth)
        publisher.public_base_url = "http://example.com"
        publisher._serve_video = lambda p: f"{publisher.public_base_url}/video"
        result = publisher.publish(video_path=str(video), caption="Test caption #game")
        assert result == "published_media_1"

    def test_publish_retries_on_pending_status(self, tmp_path):
        token_data = {"access_token": "valid", "expires_at": time.time() + 5000000}
        Path(tmp_path / "instagram_token.json").write_text(json.dumps(token_data))
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))

        with patch.object(auth, 'get_pages', return_value=[{"id": "page123"}]):
            with patch.object(auth, 'get_instagram_account', return_value={"id": "ig123"}):
                publisher = InstagramPublisher(auth)
                publisher.public_base_url = "http://example.com"
                with patch.object(publisher, '_serve_video', return_value="http://example.com/video.mp4"):
                    with patch.object(publisher, '_create_media', return_value={"id": "container1"}):
                        with patch.object(publisher, '_poll_status', return_value=True):
                            with patch.object(publisher, '_publish_media', return_value="pub123"):
                                result = publisher.publish(video_path="test.mp4", caption="Test")
                                assert result == "pub123"

    def test_poll_status_times_out(self, tmp_path):
        token_data = {"access_token": "valid", "expires_at": time.time() + 5000000}
        Path(tmp_path / "instagram_token.json").write_text(json.dumps(token_data))
        auth = InstagramAuth(app_id="test_app", app_secret="test_secret", data_dir=str(tmp_path))
        publisher = InstagramPublisher(auth)

        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status_code": "IN_PROGRESS"})
            result = publisher._poll_status("ig123", "container1", "token", max_retries=2)
            assert result is False
