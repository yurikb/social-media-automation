from datetime import datetime
from src.models.clip_candidate import ClipCandidate, StreamInfo, ViralScore
from src.models.enhanced_video import EnhancedVideo, CaptionStyle, Thumbnail
from src.models.metrics import VideoMetrics, PlatformMetrics

def test_clip_candidate_creation():
    stream = StreamInfo(name="alanzoka", platform="twitch", channel_id="alanzoka")
    candidate = ClipCandidate(
        stream=stream,
        start_time=datetime(2026, 5, 15, 20, 30, 0),
        end_time=datetime(2026, 5, 15, 20, 30, 45),
        raw_url="https://example.com/stream.mp4",
        context="Funny reaction to game moment"
    )
    assert candidate.duration_seconds == 45
    assert candidate.stream.name == "alanzoka"

def test_viral_score_creation():
    score = ViralScore(
        overall=85,
        humor=90,
        emotion=80,
        relevance=85,
        hook_strength=75,
        reasoning="High laughter detection + trending game"
    )
    assert score.overall == 85
    assert score.reasoning is not None

def test_enhanced_video_creation():
    thumbnail = Thumbnail(path="thumb.jpg", style="text_overlay")
    enhanced = EnhancedVideo(
        clip_path="clip.mp4",
        captions_path="captions.srt",
        thumbnails=[thumbnail],
        title="ALANZOKA SURTA com esse momento! 😱",
        hashtags=["#alanzoka", "#gaming", "#brasil"],
        hook_text="VOCÊ NÃO VAI ACREDITAR"
    )
    assert len(enhanced.thumbnails) == 1
    assert enhanced.title is not None

def test_video_metrics_creation():
    metrics = VideoMetrics(
        video_id="vid_123",
        platform="tiktok",
        views=10000,
        likes=800,
        comments=150,
        shares=200,
        saves=100,
        retention_rate=0.75,
        watch_time_seconds=22500,
        published_at=datetime(2026, 5, 15)
    )
    assert metrics.engagement_rate > 0
    assert metrics.retention_rate == 0.75