import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from src.models.clip_candidate import ClipCandidate, StreamInfo


class ResearchService:
    def __init__(
        self,
        config_path: str,
        data_dir: str,
        twitch_client_id: Optional[str] = None,
        twitch_client_secret: Optional[str] = None,
    ):
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        config_path = Path(config_path) if isinstance(config_path, str) else config_path
        with open(config_path / "streamers.json", encoding="utf-8") as f:
            self.streamers_config = json.load(f)

        self.twitch_client_id = twitch_client_id
        self.twitch_client_secret = twitch_client_secret
        self._twitch_token: Optional[str] = None
        self._token_expires: float = 0

    def check_twitch_auth(self) -> str:
        if self._twitch_token and time.time() < self._token_expires:
            return self._twitch_token
        if not self.twitch_client_id or not self.twitch_client_secret:
            raise ValueError("Twitch credentials not configured")
        resp = httpx.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": self.twitch_client_id,
                "client_secret": self.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._twitch_token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600)
        return self._twitch_token

    def _check_stream_live(self, streamer: dict) -> Optional[dict]:
        platform = streamer["platform"]
        if platform != "twitch":
            return None
        token = self.check_twitch_auth()
        resp = httpx.get(
            "https://api.twitch.tv/helix/streams",
            params={"user_login": streamer["channel_id"]},
            headers={
                "Client-ID": self.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("data"):
            return data["data"][0]
        return None

    def get_live_streamers(self) -> list[dict]:
        live = []
        for streamer in self.streamers_config["streamers"]:
            info = self._check_stream_live(streamer)
            if info:
                live.append({**streamer, "stream_info": info})
        return live

    def _get_vod_id(self, user_id: str) -> Optional[str]:
        token = self.check_twitch_auth()
        resp = httpx.get(
            "https://api.twitch.tv/helix/videos",
            params={"user_id": user_id, "type": "archive", "first": 1},
            headers={
                "Client-ID": self.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("data"):
            return data["data"][0]["id"]
        return None

    def download_segment(
        self,
        streamer: dict,
        stream_info: dict,
        start_time: datetime,
        duration: int,
    ) -> Optional[str]:
        if streamer["platform"] != "twitch":
            return None
        vod_id = self._get_vod_id(stream_info["user_id"])
        if not vod_id:
            return None
        ts = start_time.strftime("%Y%m%d_%H%M%S")
        filename = f"{streamer['name']}_{ts}_{duration}s.mp4"
        output = str(self.raw_dir / filename)
        cmd = [
            "yt-dlp",
            "--downloader", "ffmpeg",
            "--download-sections", f"*{start_time.strftime('%H:%M:%S')}-{duration}",
            "--force-keyframes-at-cuts",
            "-o", output,
            f"https://www.twitch.tv/videos/{vod_id}",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            return output
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"  [DEBUG] yt-dlp error: {e}")
            return None

    def find_highlight_moments(
        self, audio_energy: list[float], sample_rate: float = 10
    ) -> list[tuple[float, float]]:
        if not audio_energy:
            return []
        mean = sum(audio_energy) / len(audio_energy)
        std = (sum((e - mean) ** 2 for e in audio_energy) / len(audio_energy)) ** 0.5
        threshold = mean + std * 1.5

        highlights = []
        in_peak = False
        peak_start = 0.0
        for i, energy in enumerate(audio_energy):
            if energy > threshold and not in_peak:
                peak_start = i / sample_rate
                in_peak = True
            elif energy <= threshold and in_peak:
                duration = (i / sample_rate) - peak_start
                if duration >= 5:
                    highlights.append((peak_start, i / sample_rate))
                in_peak = False
        if in_peak:
            highlights.append((peak_start, len(audio_energy) / sample_rate))
        return highlights

    def scan(
        self, duration_minutes: int = 60
    ) -> list[ClipCandidate]:
        streamers = self.load_streamers()
        live = []
        for s in streamers:
            info = self._check_stream_live(s)
            if info:
                live.append((s, info))
        candidates = []
        for streamer, stream_info in live:
            started_at = datetime.fromisoformat(
                stream_info["started_at"].replace("Z", "+00:00")
            )
            now = datetime.now(timezone.utc)
            scan_end = min(now, started_at + timedelta(minutes=duration_minutes))
            window_minutes = int((scan_end - started_at).total_seconds() // 60)
            if window_minutes < 15:
                continue
            video_path = self.download_segment(
                streamer, stream_info, started_at, window_minutes * 60
            )
            if not video_path:
                continue
            from src.utils.audio import extract_audio, analyze_audio_energy

            audio_path = extract_audio(video_path, video_path.replace(".mp4", ".wav"))
            energy = analyze_audio_energy(audio_path)
            highlights = self.find_highlight_moments(energy)
            for start, end in highlights:
                if end - start < 15 or end - start > 90:
                    continue
                candidates.append(
                    ClipCandidate(
                        stream=StreamInfo(
                            name=streamer["name"],
                            platform=streamer["platform"],
                            channel_id=streamer["channel_id"],
                        ),
                        start_time=started_at + timedelta(seconds=start),
                        end_time=started_at + timedelta(seconds=end),
                        raw_url=video_path,
                        context="Audio energy peak detected",
                    )
                )
        return candidates

    def load_streamers(self) -> list[dict]:
        return self.streamers_config["streamers"]
