from pathlib import Path
from datetime import datetime

from src.models.clip_candidate import ClipCandidate, StreamInfo, ViralScore
from src.models.enhanced_video import EnhancedVideo, CaptionStyle, Thumbnail
from src.models.metrics import VideoMetrics, PlatformMetrics


class TestResearchService:
    def test_load_streamers(self):
        from src.services.research import ResearchService

        config_path = Path(__file__).parent.parent / "config"
        service = ResearchService(
            config_path=str(config_path),
            data_dir="/tmp/test_data",
        )
        streamers = service.load_streamers()
        assert len(streamers) > 0
        assert streamers[0]["name"] == "alanzoka"
        assert streamers[0]["platform"] == "twitch"

    def test_find_highlight_moments(self):
        from src.services.research import ResearchService

        service = ResearchService(
            config_path="config",
            data_dir="/tmp/test_data",
        )
        energy = [0.5, 0.6, 0.7, 2.5, 3.0, 2.8, 0.8, 0.5, 0.4, 2.0, 2.5, 0.5]

        highlights = service.find_highlight_moments(energy, sample_rate=2)
        assert isinstance(highlights, list)
        if highlights:
            start, end = highlights[0]
            assert end > start


class TestCurationService:
    def test_score_by_audio_energy(self):
        from src.services.curation import CurationService

        service = CurationService(data_dir="/tmp/test_data")
        energy = [0.5, 0.8, 1.2, 2.5, 3.0, 1.8, 0.9, 0.4, 0.3, 2.0, 2.8]
        score = service.score_by_audio_energy(energy)
        assert 0 <= score.overall <= 100
        assert score.reasoning

    def test_score_by_audio_energy_empty(self):
        from src.services.curation import CurationService
        service = CurationService(data_dir="/tmp")
        score = service.score_by_audio_energy([])
        assert score.overall == 50

    def test_score_by_transcript(self):
        from src.services.curation import CurationService
        service = CurationService(data_dir="/tmp")
        transcript = "Nossa! Olha isso! Cê viu? Que loucura! hahaha kkkkk não acredito!"
        score = service.score_by_transcript(transcript)
        assert 0 <= score.overall <= 100
        assert score.humor > 0

    def test_score_by_transcript_empty(self):
        from src.services.curation import CurationService
        service = CurationService(data_dir="/tmp")
        score = service.score_by_transcript("")
        assert score.overall == 50

    def test_rank_candidates(self):
        from src.services.curation import CurationService
        service = CurationService(data_dir="/tmp")
        scores = [
            ViralScore(overall=85, reasoning="good"),
            ViralScore(overall=45, reasoning="bad"),
            ViralScore(overall=92, reasoning="great"),
            ViralScore(overall=60, reasoning="ok"),
        ]
        ranked = service.rank_candidates(scores, min_score=60, max_results=2)
        assert len(ranked) == 2
        assert ranked[0][1].overall == 92
        assert ranked[1][1].overall == 85

    def test_select_daily_picks(self):
        from src.services.curation import CurationService
        service = CurationService(data_dir="/tmp")
        stream = StreamInfo(name="test", platform="twitch", channel_id="test")
        candidates = [
            (ClipCandidate(stream=stream, start_time=datetime(2026, 1, 1, 0, 0),
                           end_time=datetime(2026, 1, 1, 0, 0, 30), raw_url="a.mp4"),
             ViralScore(overall=90, reasoning="a")),
            (ClipCandidate(stream=stream, start_time=datetime(2026, 1, 1, 0, 0),
                           end_time=datetime(2026, 1, 1, 0, 1, 0), raw_url="b.mp4"),
             ViralScore(overall=80, reasoning="b")),
            (ClipCandidate(stream=stream, start_time=datetime(2026, 1, 1, 0, 0),
                           end_time=datetime(2026, 1, 1, 0, 1, 15), raw_url="c.mp4"),
             ViralScore(overall=95, reasoning="c")),
        ]
        picks = service.select_daily_picks(candidates, max_picks=2)
        assert len(picks) == 2
        assert picks[0][1].overall == 95


class TestClippingService:
    def test_get_platform_config(self):
        from src.services.clipping import ClippingService

        config_path = Path(__file__).parent.parent / "config"
        service = ClippingService(data_dir="/tmp", config_path=str(config_path))
        config = service.get_platform_config("tiktok")
        assert config.get("max_duration_seconds") == 180
        assert config.get("aspect_ratio") == "9:16"


class TestEnhancementService:
    def test_format_srt_time(self):
        from src.services.enhancement import EnhancementService
        service = EnhancementService(data_dir="/tmp", config_path="config")
        result = service._format_srt_time(3661.5)
        assert result == "01:01:01,500"


class TestPublishingService:
    def test_get_enabled_platforms(self):
        from src.services.publishing import PublishingService

        config_path = Path(__file__).parent.parent / "config"
        service = PublishingService(config_path=str(config_path))
        platforms = service.get_enabled_platforms()
        assert "tiktok" in platforms


class TestAnalyticsService:
    def test_record_and_get_metrics(self, tmp_path):
        from src.services.analytics import AnalyticsService

        service = AnalyticsService(data_dir=str(tmp_path))
        metrics = VideoMetrics(
            video_id="test_123",
            platform="tiktok",
            views=1000,
            likes=100,
            comments=20,
            shares=30,
        )
        service.record_metrics(metrics)
        retrieved = service.get_video_metrics("test_123")
        assert retrieved is not None
        assert retrieved.views == 1000

    def test_get_platform_metrics(self, tmp_path):
        from src.services.analytics import AnalyticsService
        service = AnalyticsService(data_dir=str(tmp_path))

        service.record_metrics(VideoMetrics(
            video_id="v1", platform="tiktok", views=10000, likes=800,
            comments=100, shares=200, retention_rate=0.7,
        ))
        service.record_metrics(VideoMetrics(
            video_id="v2", platform="tiktok", views=20000, likes=1500,
            comments=300, shares=400, retention_rate=0.8,
        ))

        pm = service.get_platform_metrics("tiktok")
        assert pm.total_videos == 2
        assert pm.total_views == 30000
        assert pm.viral_videos == 1  # v2 has 20K views and 2200/20000=11% engagement

    def test_get_platform_metrics_empty(self, tmp_path):
        from src.services.analytics import AnalyticsService
        service = AnalyticsService(data_dir=str(tmp_path))
        pm = service.get_platform_metrics("tiktok")
        assert pm.total_videos == 0

    def test_generate_report(self, tmp_path):
        from src.services.analytics import AnalyticsService
        service = AnalyticsService(data_dir=str(tmp_path))

        service.record_metrics(VideoMetrics(
            video_id="v1", platform="tiktok", views=5000, likes=200,
            comments=50, shares=100,
        ))

        report = service.generate_report(days=7)
        assert report["total_videos"] == 1
        assert "tiktok" in report["platforms"]


class TestPipeline:
    def test_pipeline_initialization(self):
        from src.services.pipeline import Pipeline

        config_path = Path(__file__).parent.parent / "config"
        pipeline = Pipeline(
            data_dir="/tmp/test_pipeline",
            config_path=str(config_path),
        )
        assert pipeline.research is not None
        assert pipeline.curation is not None
        assert pipeline.clipping is not None
        assert pipeline.enhancement is not None
        assert pipeline.publishing is not None
        assert pipeline.analytics is not None

    def test_generate_hook_and_title(self):
        from src.services.pipeline import Pipeline
        from src.models.clip_candidate import ClipCandidate, StreamInfo

        config_path = Path(__file__).parent.parent / "config"
        pipeline = Pipeline(data_dir="/tmp", config_path=str(config_path))

        stream = StreamInfo(name="alanzoka", platform="twitch", channel_id="alanzoka")
        candidate = ClipCandidate(
            stream=stream,
            start_time=datetime(2026, 1, 1, 0, 0),
            end_time=datetime(2026, 1, 1, 0, 0, 30),
            raw_url="test.mp4",
        )
        score = ViralScore(overall=85, reasoning="test")

        hook = pipeline._generate_hook(candidate, score)
        assert "ALANZOKA" in hook

        title = pipeline._generate_title(candidate)
        assert candidate.stream.name in title
