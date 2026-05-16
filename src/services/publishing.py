import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from src.models.enhanced_video import EnhancedVideo
from src.models.metrics import VideoMetrics


class BasePublisher(ABC):
    @abstractmethod
    def publish(self, video: EnhancedVideo) -> Optional[VideoMetrics]:
        ...

    @abstractmethod
    def get_metrics(self, video_id: str) -> Optional[VideoMetrics]:
        ...


class TikTokPublisher(BasePublisher):
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://open-api.tiktok.com"

    def publish(self, video: EnhancedVideo) -> Optional[VideoMetrics]:
        if not self.api_key or not self.api_secret:
            return None
        try:
            with open(video.clip_path, "rb") as f:
                files = {"video": f}
                data = {
                    "access_token": self.api_key,
                    "description": f"{video.title}\n{' '.join(video.hashtags)}",
                }
                resp = httpx.post(
                    f"{self.base_url}/video/publish/",
                    data=data,
                    files=files,
                    timeout=300,
                )
                resp.raise_for_status()
                result = resp.json()
                if result.get("data", {}).get("video_id"):
                    return self.get_metrics(result["data"]["video_id"])
        except (httpx.HTTPError, OSError):
            pass
        return None

    def get_metrics(self, video_id: str) -> Optional[VideoMetrics]:
        try:
            resp = httpx.get(
                f"{self.base_url}/video/query/",
                params={"video_id": video_id, "access_token": self.api_key},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            stats = data.get("statistics", {})
            return VideoMetrics(
                video_id=video_id,
                platform="tiktok",
                views=stats.get("view_count", 0),
                likes=stats.get("like_count", 0),
                comments=stats.get("comment_count", 0),
                shares=stats.get("share_count", 0),
                published_at=datetime.now(),
            )
        except (httpx.HTTPError, KeyError):
            return None


class YouTubePublisher(BasePublisher):
    def __init__(self, auth: Optional["YouTubeAuth"] = None, api_key: str = ""):
        self.auth = auth
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"

    def publish(self, video: EnhancedVideo) -> Optional[VideoMetrics]:
        if not self.auth or not self.auth.is_authenticated():
            return None
        from src.services.youtube_upload import YouTubeUploader
        uploader = YouTubeUploader(self.auth)
        desc = f"{video.title}\n{' '.join(video.hashtags)}" if video.hashtags else video.title
        video_id = uploader.publish(
            video_path=video.clip_path,
            title=video.title,
            description=desc,
            tags=video.hashtags,
        )
        if video_id:
            video.platform_video_ids["youtube_shorts"] = video_id
            return self.get_metrics(video_id)
        return None

    def get_metrics(self, video_id: str) -> Optional[VideoMetrics]:
        try:
            resp = httpx.get(
                f"{self.base_url}/videos",
                params={
                    "part": "statistics",
                    "id": video_id,
                    "key": self.api_key,
                },
                timeout=30,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if not items:
                return None
            stats = items[0].get("statistics", {})
            return VideoMetrics(
                video_id=video_id,
                platform="youtube_shorts",
                views=int(stats.get("viewCount", 0)),
                likes=int(stats.get("likeCount", 0)),
                comments=int(stats.get("commentCount", 0)),
                published_at=datetime.now(),
            )
        except (httpx.HTTPError, KeyError, IndexError):
            return None


class InstagramPublisher(BasePublisher):
    def __init__(self, auth: Optional["InstagramAuth"] = None, access_token: str = ""):
        self.auth = auth
        self.access_token = access_token
        self.base_url = "https://graph.instagram.com"

    def publish(self, video: EnhancedVideo) -> Optional[VideoMetrics]:
        if not self.auth or not self.auth.is_authenticated():
            return None
        from src.services.instagram_upload import InstagramPublisher as IGPublisher
        pub = IGPublisher(self.auth)
        caption = f"{video.title}\n{' '.join(video.hashtags)}" if video.hashtags else video.title
        ig_media_id = pub.publish(video_path=video.clip_path, caption=caption)
        if ig_media_id:
            video.platform_video_ids["instagram_reels"] = ig_media_id
            return self.get_metrics(ig_media_id)
        return None

    def get_metrics(self, video_id: str) -> Optional[VideoMetrics]:
        return None


class PublishingService:
    def __init__(self, config_path: str):
        with open(Path(config_path) / "platforms.json") as f:
            self.config = json.load(f)

        self._publishers: dict[str, BasePublisher] = {}

    def register_publisher(self, platform: str, publisher: BasePublisher) -> None:
        self._publishers[platform] = publisher

    def publish(
        self,
        video: EnhancedVideo,
        platforms: Optional[list[str]] = None,
    ) -> dict[str, Optional[VideoMetrics]]:
        if platforms is None:
            platforms = [
                p for p, cfg in self.config.get("platforms", {}).items()
                if cfg.get("enabled", False)
            ]

        results = {}
        for platform in platforms:
            publisher = self._publishers.get(platform)
            if not publisher:
                continue
            metrics = publisher.publish(video)
            if metrics:
                time.sleep(15)
            results[platform] = metrics

        return results

    def get_enabled_platforms(self) -> list[str]:
        return [
            p for p, cfg in self.config.get("platforms", {}).items()
            if cfg.get("enabled", False)
        ]
