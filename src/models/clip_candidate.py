from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class StreamInfo:
    """Information about a streamer and their channel."""
    name: str
    platform: str  # "twitch", "kick", "youtube"
    channel_id: str
    categories: list[str] = field(default_factory=list)
    priority: int = 1  # 1 = highest priority


@dataclass
class ViralScore:
    """Viral potential scoring for a clip candidate."""
    overall: float  # 0-100
    humor: float = 0.0  # 0-100
    emotion: float = 0.0  # 0-100
    relevance: float = 0.0  # 0-100
    hook_strength: float = 0.0  # 0-100
    reasoning: str = ""

    def __post_init__(self):
        if not 0 <= self.overall <= 100:
            raise ValueError(f"Overall score must be 0-100, got {self.overall}")


@dataclass
class ClipCandidate:
    """A candidate clip from a stream, ready for curation."""
    stream: StreamInfo
    start_time: datetime
    end_time: datetime
    raw_url: str  # URL or local path to raw stream segment
    context: str = ""  # Description of what happens in the clip

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def id(self) -> str:
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        return f"{self.stream.name}_{timestamp}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stream": {
                "name": self.stream.name,
                "platform": self.stream.platform,
                "channel_id": self.stream.channel_id,
            },
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
            "raw_url": self.raw_url,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClipCandidate":
        return cls(
            stream=StreamInfo(**data["stream"]),
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            raw_url=data["raw_url"],
            context=data.get("context", ""),
        )