import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.models.clip_candidate import ClipCandidate, ViralScore, StreamInfo
from src.models.enhanced_video import EnhancedVideo
from src.models.metrics import VideoMetrics
from src.services.review import ReviewService


class Pipeline:
    def __init__(
        self,
        data_dir: str,
        config_path: str,
        twitch_client_id: Optional[str] = None,
        twitch_client_secret: Optional[str] = None,
        twitch_user_token: Optional[str] = None,
        tiktok_api_key: str = "",
        tiktok_api_secret: str = "",
        youtube_api_key: str = "",
        instagram_access_token: str = "",
        youtube_client_id: Optional[str] = None,
        youtube_client_secret: Optional[str] = None,
        instagram_app_id: Optional[str] = None,
        instagram_app_secret: Optional[str] = None,
    ):
        self.data_dir = Path(data_dir)
        self.config_path = Path(config_path)
        self.twitch_client_id = twitch_client_id
        self.config = json.loads((self.config_path / "pipeline.json").read_text())
        self.twitch_client_secret = twitch_client_secret
        self.twitch_user_token = twitch_user_token

        from src.services.research import ResearchService
        from src.services.curation import CurationService
        from src.services.clipping import ClippingService
        from src.services.enhancement import EnhancementService
        from src.services.publishing import PublishingService, TikTokPublisher, YouTubePublisher, InstagramPublisher
        from src.services.analytics import AnalyticsService

        self.research = ResearchService(
            config_path=str(self.config_path),
            data_dir=str(self.data_dir),
            twitch_client_id=self.twitch_client_id,
            twitch_client_secret=self.twitch_client_secret,
        )
        self.curation = CurationService(data_dir=str(self.data_dir))
        self.clipping = ClippingService(
            data_dir=str(self.data_dir),
            config_path=str(self.config_path),
        )
        self.enhancement = EnhancementService(
            data_dir=str(self.data_dir),
            config_path=str(self.config_path),
        )

        self.publishing = PublishingService(config_path=str(self.config_path))
        if tiktok_api_key:
            self.publishing.register_publisher(
                "tiktok", TikTokPublisher(tiktok_api_key, tiktok_api_secret)
            )
        if youtube_client_id and youtube_client_secret:
            from src.services.youtube_upload import YouTubeAuth
            yt_auth = YouTubeAuth(
                client_id=youtube_client_id,
                client_secret=youtube_client_secret,
                data_dir=str(self.data_dir),
            )
            self.publishing.register_publisher(
                "youtube_shorts", YouTubePublisher(auth=yt_auth, api_key=youtube_api_key or "")
            )
        elif youtube_api_key:
            self.publishing.register_publisher(
                "youtube_shorts", YouTubePublisher(api_key=youtube_api_key)
            )
        if instagram_app_id and instagram_app_secret:
            from src.services.instagram_upload import InstagramAuth
            ig_auth = InstagramAuth(
                app_id=instagram_app_id,
                app_secret=instagram_app_secret,
                data_dir=str(self.data_dir),
            )
            self.publishing.register_publisher(
                "instagram_reels", InstagramPublisher(auth=ig_auth)
            )

        self.analytics = AnalyticsService(data_dir=str(self.data_dir))

    def _log(self, msg: str) -> None:
        print(msg)

    def _generate_sample_candidates(self) -> list[ClipCandidate]:
        streamers = self.research.load_streamers()
        now = datetime.now(timezone.utc)
        candidates = []
        for s in streamers[:2]:
            for i in range(2):
                start = now - timedelta(minutes=30 * (i + 1))
                candidates.append(
                    ClipCandidate(
                        stream=StreamInfo(
                            name=s["name"],
                            platform=s["platform"],
                            channel_id=s["channel_id"],
                            categories=s.get("categories", []),
                            priority=s.get("priority", 1),
                        ),
                        start_time=start,
                        end_time=start + timedelta(seconds=30),
                        raw_url=f"sample_{s['name']}_{i}.mp4",
                        context=f"Sample highlight {i+1} from {s['name']}",
                    )
                )
        return candidates

    def _score_candidates(self, candidates: list[ClipCandidate]) -> list[tuple[ClipCandidate, ViralScore]]:
        scored = []
        for c in candidates:
            transcript = f"wow look at this incredible moment from {c.stream.name} hahaha kkkk"
            score_text = self.curation.score_by_transcript(transcript)
            scored.append((c, score_text))
        return scored

    def run_cycle(self, dry_run: bool = False) -> list[EnhancedVideo]:
        self._log("[PIPELINE] Starting cycle (dry_run=%s)" % dry_run)
        results = []

        has_twitch = bool(self.twitch_client_id and self.twitch_client_secret)

        if has_twitch:
            self._log("[RESEARCH] Scanning live streams...")
            try:
                live = self.research.get_live_streamers()
                self._log("[RESEARCH] Live: %s" % ", ".join(s["name"] for s in live))
            except Exception as e:
                self._log("[RESEARCH] Error checking live: %s" % e)

        if has_twitch and self.twitch_user_token:
            from src.services.clip_creator import ClipCreator
            creator = ClipCreator(
                client_id=self.twitch_client_id,
                user_token=self.twitch_user_token,
                data_dir=str(self.data_dir),
            )
            self._log("[RESEARCH] Creating clips from live streams...")
            candidates = []
            for s in live:
                bid = s.get("stream_info", {}).get("user_id")
                if not bid:
                    continue
                self._log("  Creating clip for %s (broadcaster: %s)" % (s["name"], bid))
                candidate = creator.capture_moment(bid, s["name"])
                if candidate:
                    candidates.append(candidate)
            if not candidates:
                self._log("[RESEARCH] No clips created - using sample data")
                candidates = self._generate_sample_candidates()
        elif has_twitch:
            try:
                candidates = self.research.scan(duration_minutes=60)
                if not candidates:
                    self._log("[RESEARCH] No candidates from live streams")
                    self._log("[HINT] Run: sma auth login for clip creation mode")
                    self._log("[RESEARCH] Falling back to sample data for demo")
                    candidates = self._generate_sample_candidates()
            except Exception as e:
                self._log("[RESEARCH] Error scanning: %s" % e)
                candidates = self._generate_sample_candidates()
        else:
            self._log("[RESEARCH] No Twitch credentials - using sample data")
            candidates = self._generate_sample_candidates()

        self._log("[RESEARCH] %d candidates found" % len(candidates))

        if not candidates:
            self._log("[CURATION] No candidates to score")
            return results

        self._log("[CURATION] Scoring clips...")
        scored = self._score_candidates(candidates)
        picks = self.curation.select_daily_picks(scored)
        self._log("[CURATION] %d picks selected" % len(picks))

        self._log("[CLIPPING] Processing %d clips..." % len(picks))
        for i, (candidate, score) in enumerate(picks):
            self._log("  [CLIP %d/%d] %s (score: %.1f)" % (
                i + 1, len(picks), candidate.stream.name, score.overall
            ))
            if dry_run:
                processed_path = "dry_run_%s.mp4" % candidate.id
            else:
                processed_path = self.clipping.extract_and_process(candidate)

            if processed_path:
                if not dry_run:
                    self._log("  [ENHANCE] Adding captions/thumbnails...")
                    enhanced = self.enhancement.enhance(
                        clip_path=processed_path,
                        hook_text=self._generate_hook(candidate, score),
                        title=self._generate_title(candidate),
                        hashtags=self._generate_hashtags(candidate),
                    )
                    results.append(enhanced)
                    self._log("  [ENHANCE] Done: %s" % enhanced.id)
                else:
                    self._log("  [ENHANCE] Skipped (dry-run)")

        if results and not dry_run:
            require_approval = self.config.get("publishing", {}).get("require_approval", True)
            if require_approval:
                self._log("[PUBLISH] require_approval=True - queueing for review")
                review = ReviewService(data_dir=str(self.data_dir))
                enabled = self.publishing.get_enabled_platforms()
                for v in results:
                    vid = review.add(v, enabled)
                    self._log("  Queued: %s -> %s" % (v.title, ", ".join(enabled)))
                self._log("[PUBLISH] %d videos queued for review" % len(results))
                self._log("[HINT] Run: sma preview   - to see pending videos")
                self._log("[HINT] Run: sma approve --all - to publish all")
            else:
                self._log("[PUBLISH] Posting to platforms...")
                platform_results = self.publishing.publish(results[0])
                for platform, metrics in platform_results.items():
                    if metrics:
                        self.analytics.record_metrics(metrics)
                self._log("[PUBLISH] Published to %d platforms" % len(platform_results))

        if results:
            report = self.analytics.generate_report(days=1)
            self._log("[ANALYTICS] Report: %d videos, %d views, %d engagements" % (
                report["total_videos"], report["total_views"], report["total_engagement"]
            ))

        self._log("[PIPELINE] Cycle complete: %d videos processed" % len(results))
        return results

    def _generate_hook(self, candidate: ClipCandidate, score: ViralScore) -> str:
        return "VOCE NAO VAI ACREDITAR NO QUE %s FEZ!" % candidate.stream.name.upper()

    def _generate_title(self, candidate: ClipCandidate) -> str:
        return "%s - Momento epico!" % candidate.stream.name

    def _generate_hashtags(self, candidate: ClipCandidate) -> list[str]:
        return ["#%s" % candidate.stream.name, "#gaming", "#clips", "#brasil"]
