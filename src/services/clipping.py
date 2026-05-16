import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models.clip_candidate import ClipCandidate
from src.utils.video import VideoProcessor, get_video_info


class ClippingService:
    def __init__(self, data_dir: str, config_path: str):
        self.data_dir = Path(data_dir)
        self.clips_dir = self.data_dir / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True)

        with open(Path(config_path) / "pipeline.json") as f:
            self.config = json.load(f)

        with open(Path(config_path) / "platforms.json") as f:
            self.platforms = json.load(f)

        self.processor = VideoProcessor(str(self.clips_dir))

    def extract_and_process(
        self,
        candidate: ClipCandidate,
        platform: str = "tiktok",
        center_x: float = 0.5,
    ) -> Optional[str]:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d_%H%M%S")
        clip_filename = f"{candidate.stream.name}_{ts}_{platform}.mp4"
        clip_path = str(self.clips_dir / clip_filename)

        duration = candidate.duration_seconds if candidate.duration_seconds > 0 else 60
        out = self.processor.extract_clip(
            input_path=candidate.raw_url,
            output_path=clip_path,
            start_time=0,
            duration=duration,
        )
        reframed = clip_path.replace(".mp4", "_vertical.mp4")
        out = self.processor.reframe_vertical(
            input_path=out,
            output_path=reframed,
            center_x=center_x,
        )

        cleaned = reframed.replace("_vertical.mp4", "_clean.mp4")
        out = self.processor.remove_silence(
            input_path=reframed,
            output_path=cleaned,
        )

        return out

    def get_platform_config(self, platform: str) -> dict:
        return self.platforms.get("platforms", {}).get(platform, {})

    def validate_clip(self, clip_path: str, platform: str) -> bool:
        try:
            info = get_video_info(clip_path)
            config = self.get_platform_config(platform)
            max_duration = config.get("max_duration_seconds", 180)
            if info["duration"] > max_duration:
                return False
            return True
        except (ValueError, KeyError):
            return False
