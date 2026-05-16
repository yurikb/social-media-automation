from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class VideoMetrics:
    """Performance metrics for a published video."""
    video_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    retention_rate: float = 0.0  # 0.0-1.0
    watch_time_seconds: int = 0
    published_at: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def engagement_rate(self) -> float:
        """Calculate engagement rate as (likes + comments + shares) / views."""
        if self.views == 0:
            return 0.0
        return (self.likes + self.comments + self.shares) / self.views

    @property
    def is_viral(self) -> bool:
        """A video is viral if it has >10K views and >5% engagement."""
        return self.views > 10000 and self.engagement_rate > 0.05

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "platform": self.platform,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "saves": self.saves,
            "retention_rate": self.retention_rate,
            "watch_time_seconds": self.watch_time_seconds,
            "engagement_rate": self.engagement_rate,
            "is_viral": self.is_viral,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass
class PlatformMetrics:
    """Aggregated metrics for a platform."""
    platform: str
    total_videos: int = 0
    total_views: int = 0
    total_engagement: int = 0
    avg_retention_rate: float = 0.0
    avg_engagement_rate: float = 0.0
    viral_videos: int = 0
    last_updated: datetime = field(default_factory=datetime.now)