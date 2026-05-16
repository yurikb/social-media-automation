import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.models.metrics import PlatformMetrics, VideoMetrics


class AnalyticsService:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.metrics_file = self.data_dir / "metrics.json"
        self.metrics: list[VideoMetrics] = []
        self._load()

    def _load(self) -> None:
        if self.metrics_file.exists():
            try:
                data = json.loads(self.metrics_file.read_text())
                self.metrics = [VideoMetrics(**m) for m in data]
            except (json.JSONDecodeError, TypeError):
                self.metrics = []

    def _save(self) -> None:
        self.metrics_file.write_text(
            json.dumps([m.to_dict() for m in self.metrics], indent=2)
        )

    def record_metrics(self, metrics: VideoMetrics) -> None:
        for i, m in enumerate(self.metrics):
            if m.video_id == metrics.video_id and m.platform == metrics.platform:
                self.metrics[i] = metrics
                break
        else:
            self.metrics.append(metrics)
        self._save()

    def get_video_metrics(self, video_id: str) -> Optional[VideoMetrics]:
        for m in self.metrics:
            if m.video_id == video_id:
                return m
        return None

    def get_platform_metrics(self, platform: str) -> PlatformMetrics:
        platform_videos = [m for m in self.metrics if m.platform == platform]
        if not platform_videos:
            return PlatformMetrics(platform=platform)

        total = PlatformMetrics(platform=platform)
        total.total_videos = len(platform_videos)
        total.total_views = sum(m.views for m in platform_videos)
        total.total_engagement = sum(m.likes + m.comments + m.shares for m in platform_videos)
        total.avg_retention_rate = (
            sum(m.retention_rate for m in platform_videos) / len(platform_videos)
        )
        total.avg_engagement_rate = (
            sum(m.engagement_rate for m in platform_videos) / len(platform_videos)
        )
        total.viral_videos = sum(1 for m in platform_videos if m.is_viral)
        total.last_updated = datetime.now()
        return total

    def get_top_videos(self, platform: str, limit: int = 10) -> list[VideoMetrics]:
        videos = [m for m in self.metrics if m.platform == platform]
        videos.sort(key=lambda x: x.views, reverse=True)
        return videos[:limit]

    def generate_report(self, days: int = 7) -> dict:
        cutoff = datetime.now() - timedelta(days=days)
        recent = [m for m in self.metrics if m.last_updated >= cutoff]

        platforms = {}
        for m in recent:
            if m.platform not in platforms:
                platforms[m.platform] = PlatformMetrics(platform=m.platform)

        for m in recent:
            pm = platforms[m.platform]
            pm.total_videos += 1
            pm.total_views += m.views
            pm.total_engagement += m.likes + m.comments + m.shares
            pm.viral_videos += 1 if m.is_viral else 0

        for pm in platforms.values():
            if pm.total_videos > 0:
                pm.avg_engagement_rate = pm.total_engagement / pm.total_videos
                pm.avg_retention_rate = sum(
                    m.retention_rate for m in recent if m.platform == pm.platform
                ) / pm.total_videos

        return {
            "period_days": days,
            "total_videos": len(recent),
            "total_views": sum(m.views for m in recent),
            "total_engagement": sum(m.likes + m.comments + m.shares for m in recent),
            "viral_count": sum(1 for m in recent if m.is_viral),
            "platforms": {k: v.__dict__ for k, v in platforms.items()},
        }
