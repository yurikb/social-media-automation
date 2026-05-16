from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Thumbnail:
    """A generated thumbnail for a video."""
    path: str
    style: str = "text_overlay"  # "text_overlay", "ai_generated", "hybrid"
    description: str = ""


@dataclass
class CaptionStyle:
    """Caption styling configuration."""
    style: str = "karaoke"  # "karaoke", "static", "none"
    font: str = "Arial Bold"
    font_size: int = 48
    color: str = "#FFFFFF"
    background_color: str = "#00000080"
    position: str = "bottom"  # "bottom", "center", "top"


@dataclass
class EnhancedVideo:
    """A fully processed video ready for publishing."""
    clip_path: str
    captions_path: Optional[str] = None
    thumbnails: list[Thumbnail] = field(default_factory=list)
    title: str = ""
    hashtags: list[str] = field(default_factory=list)
    description: str = ""
    hook_text: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def id(self) -> str:
        from pathlib import Path
        return Path(self.clip_path).stem

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "clip_path": self.clip_path,
            "captions_path": self.captions_path,
            "thumbnails": [{"path": t.path, "style": t.style} for t in self.thumbnails],
            "title": self.title,
            "hashtags": self.hashtags,
            "description": self.description,
            "hook_text": self.hook_text,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EnhancedVideo":
        thumbnails = [Thumbnail(**t) for t in data.get("thumbnails", [])]
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = datetime.now()
        return cls(
            clip_path=data.get("clip_path", ""),
            captions_path=data.get("captions_path"),
            thumbnails=thumbnails,
            title=data.get("title", ""),
            hashtags=data.get("hashtags", []),
            description=data.get("description", ""),
            hook_text=data.get("hook_text", ""),
            created_at=created_at or datetime.now(),
        )