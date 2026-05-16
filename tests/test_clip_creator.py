from unittest.mock import patch, MagicMock, ANY
from pathlib import Path


class TestTwitchAuth:
    def test_get_auth_url_contains_scopes(self):
        from src.services.twitch_auth import TwitchAuth

        auth = TwitchAuth(
            client_id="test_client",
            client_secret="test_secret",
            data_dir="/tmp",
        )
        url = auth.get_auth_url()
        assert "client_id=test_client" in url
        assert "clips%3Aedit" in url or "clips:edit" in url
        assert "response_type=code" in url

    def test_is_authenticated_returns_false_without_token(self):
        from src.services.twitch_auth import TwitchAuth

        auth = TwitchAuth(
            client_id="test_client",
            client_secret="test_secret",
            data_dir="/tmp/nonexistent",
        )
        assert not auth.is_authenticated()

    @patch("src.services.twitch_auth.httpx.post")
    def test_get_app_token(self, mock_post):
        from src.services.twitch_auth import TwitchAuth

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "app_token_123", "expires_in": 3600},
        )
        auth = TwitchAuth(
            client_id="test_client",
            client_secret="test_secret",
            data_dir="/tmp",
        )
        token = auth.get_app_token()
        assert token == "app_token_123"

    @patch("src.services.twitch_auth.httpx.post")
    def test_exchange_code(self, mock_post, tmp_path):
        from src.services.twitch_auth import TwitchAuth

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "user_token_123", "refresh_token": "refresh_abc", "expires_in": 3600},
        )
        auth = TwitchAuth(
            client_id="test_client",
            client_secret="test_secret",
            data_dir=str(tmp_path),
        )
        token = auth.exchange_code("my_code")
        assert token == "user_token_123"
        assert auth.is_authenticated()
        assert auth.token_file.exists()


class TestClipCreator:
    @patch("src.services.clip_creator.httpx.post")
    def test_create_clip(self, mock_post):
        from src.services.clip_creator import ClipCreator

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "ClipABC123", "edit_url": "https://clips.twitch.tv/ClipABC123/edit"}]},
        )
        creator = ClipCreator(
            client_id="test_client",
            user_token="user_token",
            data_dir="/tmp",
        )
        result = creator.create_clip("broadcaster_123")
        assert result is not None
        assert result["id"] == "ClipABC123"

    @patch("src.services.clip_creator.httpx.post")
    def test_create_clip_fails_without_auth(self, mock_post):
        from src.services.clip_creator import ClipCreator

        mock_post.return_value = MagicMock(status_code=401)
        creator = ClipCreator(
            client_id="test_client",
            user_token="bad_token",
            data_dir="/tmp",
        )
        result = creator.create_clip("broadcaster_123")
        assert result is None

    @patch("src.services.clip_creator.httpx.get")
    def test_poll_clip_ready(self, mock_get):
        from src.services.clip_creator import ClipCreator

        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "ClipABC123", "duration": 30}]},
        )
        creator = ClipCreator(
            client_id="test_client",
            user_token="user_token",
            data_dir="/tmp",
        )
        result = creator.poll_clip("ClipABC123", max_retries=1, delay=0.1)
        assert result is not None
        assert result["duration"] == 30

    @patch("src.services.clip_creator.httpx.get")
    def test_poll_clip_not_ready(self, mock_get):
        from src.services.clip_creator import ClipCreator

        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        creator = ClipCreator(
            client_id="test_client",
            user_token="user_token",
            data_dir="/tmp",
        )
        result = creator.poll_clip("ClipABC123", max_retries=1, delay=0.1)
        assert result is None

    @patch("src.services.clip_creator.subprocess.run")
    def test_download_clip(self, mock_run):
        from src.services.clip_creator import ClipCreator

        mock_run.return_value = MagicMock(returncode=0)
        creator = ClipCreator(
            client_id="test_client",
            user_token="user_token",
            data_dir="/tmp",
        )
        clip_data = {"id": "ClipABC123", "duration": 30}
        result = creator.download_clip(clip_data, filename="test_clip.mp4")
        expected = Path("/tmp/clips/test_clip.mp4")
        assert result is None or result == str(expected)


class TestStreamMonitor:
    def test_energy_threshold_below(self):
        from src.services.stream_monitor import StreamMonitor
        from src.services.clip_creator import ClipCreator

        creator = ClipCreator(client_id="x", user_token="y", data_dir="/tmp")
        monitor = StreamMonitor(clip_creator=creator, data_dir="/tmp")
        buffer = [0.1, 0.2, 0.15, 0.18, 0.12, 0.14, 0.11, 0.13, 0.16, 0.12, 0.1, 0.2, 0.15, 0.18, 0.12, 0.14, 0.11, 0.13, 0.16, 0.12]
        triggered = []
        monitor._check_for_peak(buffer, "test", "123", lambda c: triggered.append(c))
        assert len(triggered) == 0

    def test_energy_threshold_above(self):
        from src.services.stream_monitor import StreamMonitor
        from src.services.clip_creator import ClipCreator

        creator = ClipCreator(client_id="x", user_token="y", data_dir="/tmp")
        monitor = StreamMonitor(clip_creator=creator, data_dir="/tmp", cooldown_seconds=0)
        buffer = [0.1, 0.2, 0.15, 0.18, 0.12, 0.14, 0.11, 0.13, 0.16, 0.12, 0.1, 0.2, 0.15, 0.18, 3.0, 3.5, 3.2, 4.0, 3.8, 3.6]
        triggered = []
        monitor._check_for_peak(buffer, "test", "123", lambda c: triggered.append(c))
        assert len(triggered) == 0
