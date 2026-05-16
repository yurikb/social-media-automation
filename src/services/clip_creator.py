import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from src.models.clip_candidate import ClipCandidate, StreamInfo


class ClipCreator:
    def __init__(
        self,
        client_id: str,
        user_token: str,
        data_dir: str,
    ):
        self.client_id = client_id
        self.user_token = user_token
        self.clips_dir = Path(data_dir) / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    def create_clip(self, broadcaster_id: str, has_delay: bool = False) -> Optional[dict]:
        resp = httpx.post(
            "https://api.twitch.tv/helix/clips",
            params={"broadcaster_id": broadcaster_id, "has_delay": str(has_delay).lower()},
            headers={
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {self.user_token}",
            },
        )
        if resp.status_code == 401:
            print("[CLIP] Token expired or invalid")
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("data"):
            return data["data"][0]
        return None

    def poll_clip(self, clip_id: str, max_retries: int = 5, delay: float = 3.0) -> Optional[dict]:
        for i in range(max_retries):
            time.sleep(delay)
            resp = httpx.get(
                "https://api.twitch.tv/helix/clips",
                params={"id": clip_id},
                headers={
                    "Client-ID": self.client_id,
                    "Authorization": f"Bearer {self.user_token}",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("data"):
                return data["data"][0]
        return None

    def download_clip(self, clip_data: dict, filename: Optional[str] = None) -> Optional[str]:
        clip_url = f"https://clips.twitch.tv/{clip_data['id']}"
        if not filename:
            filename = f"{clip_data['id']}.mp4"
        output = str(self.clips_dir / filename)
        cmd = [
            "yt-dlp",
            "-f", "mp4",
            "-o", output,
            clip_url,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            if Path(output).exists():
                return output
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        return None

    def capture_moment(
        self, broadcaster_id: str, streamer_name: str, platform: str = "twitch",
    ) -> Optional[ClipCandidate]:
        clip_info = self.create_clip(broadcaster_id)
        if not clip_info:
            return None
        clip_id = clip_info["id"]
        print(f"[CLIP] Created clip: {clip_id}")
        clip_data = self.poll_clip(clip_id)
        if not clip_data:
            print(f"[CLIP] Clip {clip_id} not ready after polling")
            return None
        duration = clip_data.get("duration", 30)
        clip_path = self.download_clip(clip_data)
        if not clip_path:
            print(f"[CLIP] Failed to download clip {clip_id}")
            return None
        now = datetime.now(timezone.utc)
        return ClipCandidate(
            stream=StreamInfo(
                name=streamer_name,
                platform=platform,
                channel_id=broadcaster_id,
            ),
            start_time=now - timedelta(seconds=duration),
            end_time=now,
            raw_url=clip_path,
            context="Real-time clip via Twitch API",
        )
