import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.models.enhanced_video import EnhancedVideo


class PendingVideo:
    def __init__(
        self,
        video: EnhancedVideo,
        platforms: list[str],
        id: Optional[str] = None,
        created_at: Optional[str] = None,
    ):
        self.id = id or video.id
        self.video = video
        self.platforms = platforms
        self.created_at = created_at or datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "video": self.video.to_dict(),
            "platforms": self.platforms,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PendingVideo":
        video_data = data["video"].copy()
        video_data.pop("id", None)  # Remove 'id' if present, not a dataclass field
        return cls(
            id=data["id"],
            video=EnhancedVideo.from_dict(video_data),
            platforms=data["platforms"],
            created_at=data.get("created_at"),
        )


class ReviewService:
    def __init__(self, data_dir: str):
        self.pending_dir = Path(data_dir) / "pending"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.pending_dir / "queue.json"
        self._queue: list[PendingVideo] = []
        self._load()

    def _load(self) -> None:
        if self.queue_file.exists():
            try:
                data = json.loads(self.queue_file.read_text())
                self._queue = [PendingVideo.from_dict(item) for item in data]
            except (json.JSONDecodeError, TypeError, KeyError):
                self._queue = []

    def _save(self) -> None:
        self.queue_file.write_text(
            json.dumps([item.to_dict() for item in self._queue], indent=2, default=str)
        )

    def add(self, video: EnhancedVideo, platforms: list[str]) -> str:
        pending = PendingVideo(video=video, platforms=platforms)
        self._queue.append(pending)
        self._save()
        return pending.id

    def list_pending(self) -> list[PendingVideo]:
        return list(self._queue)

    def get(self, video_id: str) -> Optional[PendingVideo]:
        for item in self._queue:
            if item.id == video_id:
                return item
        return None

    def approve(self, video_id: str) -> Optional[PendingVideo]:
        for i, item in enumerate(self._queue):
            if item.id == video_id:
                self._queue.pop(i)
                self._save()
                return item
        return None

    def reject(self, video_id: str) -> Optional[PendingVideo]:
        for i, item in enumerate(self._queue):
            if item.id == video_id:
                self._queue.pop(i)
                self._save()
                return item
        return None

    def count(self) -> int:
        return len(self._queue)
