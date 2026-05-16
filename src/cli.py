import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.services.pipeline import Pipeline
from src.services.review import ReviewService
from src.models.clip_candidate import ClipCandidate, StreamInfo, ViralScore
from src.services.twitch_auth import TwitchAuth

console = Console()


def load_env(env_path: str | None = None) -> dict:
    if env_path is None:
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = Path(env_path)
    env_vars = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()
    return env_vars


def cmd_scan(args: argparse.Namespace) -> None:
    pipeline = _create_pipeline(args)
    console.print("[bold]Scanning for live streams...[/]")
    live = pipeline.research.get_live_streamers()
    if not live:
        console.print("[yellow]No live streamers found[/]")
        return
    table = Table(title="Live Streamers")
    table.add_column("Name", style="cyan")
    table.add_column("Platform")
    table.add_column("Game")
    table.add_column("Viewers")
    table.add_column("Broadcaster ID")
    for s in live:
        info = s.get("stream_info", {})
        table.add_row(
            s["name"],
            s["platform"],
            info.get("game_name", "-"),
            str(info.get("viewer_count", 0)),
            str(info.get("user_id", "-")),
        )
    console.print(table)


def cmd_run(args: argparse.Namespace) -> None:
    pipeline = _create_pipeline(args)
    console.print(Panel.fit("[bold cyan]Social Media Automation Pipeline[/]"))
    results = pipeline.run_cycle(dry_run=args.dry_run)
    console.print(f"[green]Completed: {len(results)} videos processed[/]")


def cmd_report(args: argparse.Namespace) -> None:
    from src.services.analytics import AnalyticsService
    analytics = AnalyticsService(data_dir=_get_data_dir(args))
    report = analytics.generate_report(days=args.days)

    panel = Panel.fit(
        f"[bold]Period:[/] {report['period_days']} days\n"
        f"[bold]Total videos:[/] {report['total_videos']}\n"
        f"[bold]Total views:[/] {report['total_views']}\n"
        f"[bold]Total engagement:[/] {report['total_engagement']}\n"
        f"[bold]Viral videos:[/] {report['viral_count']}",
        title="Analytics Report",
    )
    console.print(panel)

    if report["platforms"]:
        table = Table(title="Per-Platform")
        table.add_column("Platform")
        table.add_column("Videos")
        table.add_column("Views")
        table.add_column("Engagement")
        table.add_column("Viral")
        for name, data in report["platforms"].items():
            table.add_row(
                name,
                str(data.get("total_videos", 0)),
                str(data.get("total_views", 0)),
                str(data.get("total_engagement", 0)),
                str(data.get("viral_videos", 0)),
            )
        console.print(table)


def cmd_score(args: argparse.Namespace) -> None:
    from src.services.curation import CurationService

    curation = CurationService(data_dir=_get_data_dir(args))
    stream = StreamInfo(name="test", platform="twitch", channel_id="test")
    energy = [round(x, 1) for x in [0.5, 0.8, 1.2, 2.5, 3.0, 1.8, 0.9, 0.4, 0.3, 2.0, 2.8]]
    score_audio = curation.score_by_audio_energy(energy)
    console.print(f"[bold]Audio energy score:[/] {score_audio.overall}")
    console.print(f"  humor={score_audio.humor} emotion={score_audio.emotion} "
                  f"hook={score_audio.hook_strength}")

    transcript = "Nossa! Olha isso! Cê viu? Que loucura! hahaha kkkkk não acredito!"
    score_text = curation.score_by_transcript(transcript)
    console.print(f"[bold]Transcript score:[/] {score_text.overall}")
    console.print(f"  humor={score_text.humor} emotion={score_text.emotion} "
                  f"hook={score_text.hook_strength}")


def cmd_list_streamers(args: argparse.Namespace) -> None:
    pipeline = _create_pipeline(args)
    streamers = pipeline.research.load_streamers()

    table = Table(title="Configured Streamers")
    table.add_column("Name", style="cyan")
    table.add_column("Platform")
    table.add_column("Channel")
    table.add_column("Priority")
    table.add_column("Categories")
    for s in streamers:
        table.add_row(
            s["name"],
            s["platform"],
            s["channel_id"],
            str(s.get("priority", "-")),
            ", ".join(s.get("categories", [])),
        )
    console.print(table)


def cmd_auth_login(args: argparse.Namespace) -> None:
    env = load_env(args.env)
    client_id = env.get("TWITCH_CLIENT_ID") or os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = env.get("TWITCH_CLIENT_SECRET") or os.getenv("TWITCH_CLIENT_SECRET", "")
    if not client_id:
        console.print("[red]TWITCH_CLIENT_ID not set in .env[/]")
        return

    data_dir = _get_data_dir(args)
    auth = TwitchAuth(
        client_id=client_id,
        client_secret=client_secret,
        data_dir=data_dir,
    )

    if auth.is_authenticated():
        console.print("[green]Already authenticated! Token is valid.[/]")
        return

    console.print("[yellow]Abrindo navegador pra autorizar...[/]")
    console.print("[dim]Certifique-se de adicionar http://localhost:3000 como Redirect URI no Twitch Dev Console[/]")
    try:
        token = auth.login_with_server()
        if token:
            console.print(f"[green]Authenticated! Token salvo em {auth.token_file}[/]")
        else:
            console.print("[red]Falha na autenticação[/]")
    except Exception as e:
        console.print(f"[red]Auth failed: {e}[/]")


def _auth_status_twitch(env: dict, data_dir: str) -> None:
    client_id = env.get("TWITCH_CLIENT_ID") or os.getenv("TWITCH_CLIENT_ID", "")
    if not client_id:
        return
    from src.services.twitch_auth import TwitchAuth
    auth = TwitchAuth(
        client_id=client_id,
        client_secret=env.get("TWITCH_CLIENT_SECRET") or os.getenv("TWITCH_CLIENT_SECRET", ""),
        data_dir=data_dir,
    )
    if auth.is_authenticated():
        console.print("[green]  Twitch: Authenticated[/]")
    else:
        console.print("[red]  Twitch: Not authenticated (sma auth login)[/]")


def _auth_status_youtube(env: dict, data_dir: str) -> None:
    cid = env.get("YOUTUBE_CLIENT_ID") or os.getenv("YOUTUBE_CLIENT_ID", "")
    if not cid:
        return
    from src.services.youtube_upload import YouTubeAuth
    auth = YouTubeAuth(
        client_id=cid,
        client_secret=env.get("YOUTUBE_CLIENT_SECRET") or os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        data_dir=data_dir,
    )
    if auth.is_authenticated():
        console.print("[green]  YouTube: Authenticated[/]")
    else:
        console.print("[red]  YouTube: Not authenticated (sma auth youtube)[/]")


def _auth_status_instagram(env: dict, data_dir: str) -> None:
    aid = env.get("INSTAGRAM_APP_ID") or os.getenv("INSTAGRAM_APP_ID", "")
    if not aid:
        return
    from src.services.instagram_upload import InstagramAuth
    auth = InstagramAuth(
        app_id=aid,
        app_secret=env.get("INSTAGRAM_APP_SECRET") or os.getenv("INSTAGRAM_APP_SECRET", ""),
        data_dir=data_dir,
    )
    if auth.is_authenticated():
        console.print("[green]  Instagram: Authenticated[/]")
    else:
        console.print("[red]  Instagram: Not authenticated (sma auth instagram)[/]")


def cmd_auth_status(args: argparse.Namespace) -> None:
    env = load_env(args.env)
    data_dir = _get_data_dir(args)
    console.print("Auth Status:")
    _auth_status_twitch(env, data_dir)
    _auth_status_youtube(env, data_dir)
    _auth_status_instagram(env, data_dir)


def cmd_auth_test(args: argparse.Namespace) -> None:
    env = load_env(args.env)
    client_id = env.get("TWITCH_CLIENT_ID") or os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = env.get("TWITCH_CLIENT_SECRET") or os.getenv("TWITCH_CLIENT_SECRET", "")

    data_dir = _get_data_dir(args)
    auth = TwitchAuth(
        client_id=client_id,
        client_secret=client_secret,
        data_dir=data_dir,
    )
    user_token = auth.get_user_token()
    if not user_token:
        console.print("[red]Not authenticated. Run: sma auth login[/]")
        return

    from src.services.research import ResearchService
    research = ResearchService(
        config_path=args.config,
        data_dir=str(data_dir),
        twitch_client_id=client_id,
        twitch_client_secret=client_secret,
    )
    live = research.get_live_streamers()
    if not live:
        console.print("[yellow]No live streamers to test with[/]")
        return

    from src.services.clip_creator import ClipCreator
    creator = ClipCreator(
        client_id=client_id,
        user_token=user_token,
        data_dir=str(data_dir),
    )

    for s in live:
        bid = s.get("stream_info", {}).get("user_id")
        console.print(f"\n[cyan]Testing clip creation for {s['name']} (broadcaster: {bid})[/]")
        try:
            clip_info = creator.create_clip(bid)
            if clip_info:
                console.print(f"[green]Clip created: {clip_info['id']}[/]")
                console.print(f"  URL: https://clips.twitch.tv/{clip_info['id']}")
                clip_data = creator.poll_clip(clip_info["id"])
                if clip_data:
                    console.print(f"  Duration: {clip_data.get('duration', '?')}s")
                    out = creator.download_clip(clip_data)
                    if out:
                        console.print(f"  Downloaded: {out}")
                    else:
                        console.print("[red]  Download failed[/]")
                else:
                    console.print("[red]  Clip not ready after polling[/]")
            else:
                console.print("[red]  Failed to create clip[/]")
        except Exception as e:
            console.print(f"[red]  Error: {e}[/]")


def _create_twitch_auth(args: argparse.Namespace) -> TwitchAuth | None:
    env = load_env(args.env)
    client_id = env.get("TWITCH_CLIENT_ID") or os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = env.get("TWITCH_CLIENT_SECRET") or os.getenv("TWITCH_CLIENT_SECRET", "")
    if not client_id:
        return None
    return TwitchAuth(
        client_id=client_id,
        client_secret=client_secret,
        data_dir=_get_data_dir(args),
    )


def _create_pipeline(args: argparse.Namespace) -> Pipeline:
    env = load_env(args.env)
    twitch_user_token = None
    auth = _create_twitch_auth(args)
    if auth:
        twitch_user_token = auth.get_user_token()
    return Pipeline(
        data_dir=_get_data_dir(args),
        config_path=str(Path(args.config).resolve()),
        twitch_client_id=env.get("TWITCH_CLIENT_ID") or os.getenv("TWITCH_CLIENT_ID"),
        twitch_client_secret=env.get("TWITCH_CLIENT_SECRET") or os.getenv("TWITCH_CLIENT_SECRET"),
        twitch_user_token=twitch_user_token,
        tiktok_api_key=env.get("TIKTOK_API_KEY") or os.getenv("TIKTOK_API_KEY", ""),
        tiktok_api_secret=env.get("TIKTOK_API_SECRET") or os.getenv("TIKTOK_API_SECRET", ""),
        youtube_api_key=env.get("YOUTUBE_API_KEY") or os.getenv("YOUTUBE_API_KEY", ""),
        instagram_access_token=env.get("INSTAGRAM_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN", ""),
        youtube_client_id=env.get("YOUTUBE_CLIENT_ID") or os.getenv("YOUTUBE_CLIENT_ID"),
        youtube_client_secret=env.get("YOUTUBE_CLIENT_SECRET") or os.getenv("YOUTUBE_CLIENT_SECRET"),
        instagram_app_id=env.get("INSTAGRAM_APP_ID") or os.getenv("INSTAGRAM_APP_ID"),
        instagram_app_secret=env.get("INSTAGRAM_APP_SECRET") or os.getenv("INSTAGRAM_APP_SECRET"),
    )


def _get_data_dir(args: argparse.Namespace) -> str:
    env = load_env(args.env)
    return env.get("DATA_DIR") or args.data


def cmd_auth_youtube(args: argparse.Namespace) -> None:
    env = load_env(args.env)
    client_id = env.get("YOUTUBE_CLIENT_ID") or os.getenv("YOUTUBE_CLIENT_ID", "")
    client_secret = env.get("YOUTUBE_CLIENT_SECRET") or os.getenv("YOUTUBE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        console.print("[red]YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env[/]")
        console.print("[yellow]1. Go to https://console.cloud.google.com/apis/credentials[/]")
        console.print("[yellow]2. Create OAuth 2.0 Client ID (Desktop app)[/]")
        console.print("[yellow]3. Add http://localhost:3001 as Authorized Redirect URI[/]")
        console.print("[yellow]4. Enable YouTube Data API v3[/]")
        return

    data_dir = _get_data_dir(args)
    from src.services.youtube_upload import YouTubeAuth
    auth = YouTubeAuth(
        client_id=client_id,
        client_secret=client_secret,
        data_dir=data_dir,
    )

    if auth.is_authenticated():
        console.print("[green]YouTube já autenticado![/]")
        return

    console.print("[yellow]Abrindo navegador pra autorizar YouTube...[/]")
    console.print("[dim]Redirect URI: http://localhost:3011[/]")
    try:
        token = auth.login()
        if token:
            console.print(f"[green]YouTube authenticated! Token salvo em {auth.token_file}[/]")
        else:
            console.print("[red]Falha na autenticação do YouTube[/]")
    except Exception as e:
        console.print(f"[red]YouTube auth failed: {e}[/]")


def cmd_auth_instagram(args: argparse.Namespace) -> None:
    env = load_env(args.env)
    app_id = env.get("INSTAGRAM_APP_ID") or os.getenv("INSTAGRAM_APP_ID", "")
    app_secret = env.get("INSTAGRAM_APP_SECRET") or os.getenv("INSTAGRAM_APP_SECRET", "")
    if not app_id or not app_secret:
        console.print("[red]INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET must be set in .env[/]")
        console.print("[yellow]1. Go to https://developers.facebook.com/apps/[/]")
        console.print("[yellow]2. Create an app or use existing[/]")
        console.print("[yellow]3. Add Instagram Graph API product[/]")
        console.print("[yellow]4. Add http://localhost:3002 as Valid OAuth Redirect URI[/]")
        return

    data_dir = _get_data_dir(args)
    from src.services.instagram_upload import InstagramAuth
    auth = InstagramAuth(
        app_id=app_id,
        app_secret=app_secret,
        data_dir=data_dir,
    )

    if auth.is_authenticated():
        console.print("[green]Instagram já autenticado![/]")
        return

    console.print("[yellow]Abrindo navegador pra autorizar Instagram...[/]")
    console.print("[dim]Redirect URI: http://localhost:3002[/]")
    try:
        token = auth.login()
        if token:
            console.print(f"[green]Instagram authenticated! Token salvo em {auth.token_file}[/]")
        else:
            console.print("[red]Falha na autenticação do Instagram[/]")
    except Exception as e:
        console.print(f"[red]Instagram auth failed: {e}[/]")


def cmd_preview(args: argparse.Namespace) -> None:
    pipeline = _create_pipeline(args)
    review = ReviewService(data_dir=_get_data_dir(args))

    pending_list = review.list_pending()
    if not pending_list:
        console.print("[yellow]No pending videos to review[/]")
        console.print("[dim]Run 'sma run' first to generate content[/]")
        return

    table = Table(title=f"Pending Review ({len(pending_list)} videos)")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Platforms")
    table.add_column("Duration", justify="right")
    table.add_column("Created")

    for p in pending_list:
        platforms = ", ".join(p.platforms)
        table.add_row(
            p.id[:20],
            p.video.title or "-",
            platforms,
            "-",
            p.created_at[:19] if p.created_at else "-",
        )
    console.print(table)

    console.print("\n[bold]Commands:[/]")
    console.print("  [cyan]sma preview <id>[/]  - Show full details of a video")
    console.print("  [cyan]sma approve <id>[/]   - Approve and publish")
    console.print("  [cyan]sma approve --all[/]  - Approve all pending")
    console.print("  [cyan]sma reject <id>[/]    - Remove from queue")


def cmd_preview_detail(args: argparse.Namespace) -> None:
    review = ReviewService(data_dir=_get_data_dir(args))
    pending = review.get(args.video_id)
    if not pending:
        console.print(f"[red]Video '{args.video_id}' not found in pending queue[/]")
        return

    v = pending.video
    panel = Panel.fit(
        f"[bold]Title:[/] {v.title or '-'}\n"
        f"[bold]Hook:[/] {v.hook_text or '-'}\n"
        f"[bold]Hashtags:[/] {' '.join(v.hashtags) if v.hashtags else '-'}\n"
        f"[bold]Description:[/] {v.description or '-'}\n"
        f"[bold]Platforms:[/] {', '.join(pending.platforms)}\n"
        f"[bold]Video file:[/] {v.clip_path or '-'}\n"
        f"[bold]Captions:[/] {v.captions_path or '-'}\n"
        f"[bold]Thumbnails:[/] {v.thumbnails[0].path if v.thumbnails else '-'}\n"
        f"[bold]Created:[/] {pending.created_at[:19] if pending.created_at else '-'}\n",
        title=f"Preview: {pending.id[:30]}",
    )
    console.print(panel)

    from pathlib import Path
    clip = Path(v.clip_path)
    if clip.exists():
        size_mb = clip.stat().st_size / 1024 / 1024
        console.print(f"[dim]Video file exists: {clip.name} ({size_mb:.1f} MB)[/]")
    else:
        console.print("[red]Video file not found on disk[/]")


def cmd_approve(args: argparse.Namespace) -> None:
    pipeline = _create_pipeline(args)
    review = ReviewService(data_dir=_get_data_dir(args))

    if args.all:
        pending_list = review.list_pending()
        if not pending_list:
            console.print("[yellow]No pending videos to approve[/]")
            return
        approved = 0
        for p in list(pending_list):
            item = review.approve(p.id)
            if item:
                console.print(f"[green]Publishing:[/] {item.video.title or item.id}")
                platform_results = pipeline.publishing.publish(item.video, item.platforms)
                for platform, metrics in platform_results.items():
                    if metrics:
                        pipeline.analytics.record_metrics(metrics)
                        console.print(f"  [green]Posted to {platform}:[/] {metrics.video_id}")
                    else:
                        console.print(f"  [red]Failed to post to {platform}[/]")
                approved += 1
        console.print(f"\n[bold green]{approved} videos approved and published[/]")
        return

    if not args.video_id:
        console.print("[red]Specify a video ID or use --all[/]")
        return

    item = review.approve(args.video_id)
    if not item:
        console.print(f"[red]Video '{args.video_id}' not found in pending queue[/]")
        return

    console.print(f"[green]Publishing:[/] {item.video.title or item.id}")
    platform_results = pipeline.publishing.publish(item.video, item.platforms)
    for platform, metrics in platform_results.items():
        if metrics:
            pipeline.analytics.record_metrics(metrics)
            console.print(f"  [green]Posted to {platform}:[/] {metrics.video_id}")
        else:
            console.print(f"  [red]Failed to post to {platform}[/]")
    console.print("[bold green]Published[/]")


def cmd_reject(args: argparse.Namespace) -> None:
    review = ReviewService(data_dir=_get_data_dir(args))

    if args.all:
        count = review.count()
        for p in list(review.list_pending()):
            review.reject(p.id)
        console.print(f"[yellow]Rejected all {count} pending videos[/]")
        return

    if not args.video_id:
        console.print("[red]Specify a video ID or use --all[/]")
        return

    item = review.reject(args.video_id)
    if not item:
        console.print(f"[red]Video '{args.video_id}' not found in pending queue[/]")
        return
    console.print(f"[yellow]Rejected:[/] {item.video.title or item.id}")
    from pathlib import Path
    clip = Path(item.video.clip_path)
    if clip.exists():
        console.print(f"  [dim]Video file still at: {clip}[/]")
    console.print("[dim]Use 'sma preview' to see remaining[/]")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sma",
        description="Social Media Automation — clip, enhance & publish",
    )
    parser.add_argument(
        "--data",
        default=os.path.join(os.path.dirname(__file__), "..", "data"),
        help="Data directory",
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "..", "config"),
        help="Config directory",
    )
    parser.add_argument(
        "--env",
        default=os.path.join(os.path.dirname(__file__), "..", ".env"),
        help="Path to .env file",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    sub.add_parser("scan", help="Scan for live streamers")
    sub.add_parser("list-streamers", help="List configured streamers")

    run_parser = sub.add_parser("run", help="Run the full pipeline")
    run_parser.add_argument("--dry-run", action="store_true", help="Process without actual publishing")

    report_parser = sub.add_parser("report", help="Show analytics report")
    report_parser.add_argument("--days", type=int, default=7, help="Report period in days")

    preview_parser = sub.add_parser("preview", help="Preview pending videos before publishing")
    preview_parser.add_argument("video_id", nargs="?", help="Show full details of a specific video")

    approve_parser = sub.add_parser("approve", help="Approve and publish pending videos")
    approve_parser.add_argument("video_id", nargs="?", help="Video ID to approve")
    approve_parser.add_argument("--all", action="store_true", help="Approve all pending")

    reject_parser = sub.add_parser("reject", help="Reject pending videos")
    reject_parser.add_argument("video_id", nargs="?", help="Video ID to reject")
    reject_parser.add_argument("--all", action="store_true", help="Reject all pending")

    sub.add_parser("score", help="Test scoring with sample data")

    auth_parser = sub.add_parser("auth", help="Authentication commands (Twitch, YouTube, Instagram)")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", help="Auth commands")
    auth_sub.add_parser("login", help="Authorize with Twitch (opens browser)")
    auth_sub.add_parser("status", help="Check auth status")
    auth_sub.add_parser("test", help="Test clip creation with live streamers")
    auth_sub.add_parser("youtube", help="Authorize YouTube uploads (opens browser)")
    auth_sub.add_parser("instagram", help="Authorize Instagram uploads (opens browser)")

    args = parser.parse_args()

    if args.command == "auth":
        if args.auth_command == "login":
            cmd_auth_login(args)
        elif args.auth_command == "status":
            cmd_auth_status(args)
        elif args.auth_command == "test":
            cmd_auth_test(args)
        elif args.auth_command == "youtube":
            cmd_auth_youtube(args)
        elif args.auth_command == "instagram":
            cmd_auth_instagram(args)
        else:
            print("Usage: sma auth {login|status|test|youtube|instagram}")
        return

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "score":
        cmd_score(args)
    elif args.command == "preview":
        if args.video_id:
            cmd_preview_detail(args)
        else:
            cmd_preview(args)
    elif args.command == "approve":
        cmd_approve(args)
    elif args.command == "reject":
        cmd_reject(args)
    elif args.command == "list-streamers":
        cmd_list_streamers(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
