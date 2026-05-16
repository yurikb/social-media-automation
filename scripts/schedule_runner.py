#!/usr/bin/env python3
"""Standalone schedule runner for the SMA pipeline.

Usage:
    python scripts/schedule_runner.py --interval 60

Runs the main pipeline at a fixed interval, logging output to data/schedule.log.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path so `src` is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging(data_dir: str) -> logging.Logger:
    log_dir = Path(data_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "schedule.log"

    logger = logging.getLogger("sma_schedule")
    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

    # Also log to stdout
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(stream)

    return logger


def run_pipeline(dry_run: bool = False) -> int:
    """Run the SMA pipeline and return the number of videos processed."""
    from src.services.pipeline import Pipeline

    data_dir = os.environ.get(
        "DATA_DIR", str(PROJECT_ROOT / "data")
    )
    config_path = str(PROJECT_ROOT / "config")

    pipeline = Pipeline(
        data_dir=data_dir,
        config_path=config_path,
    )
    results = pipeline.run_cycle(dry_run=dry_run)
    return len(results)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SMA Schedule Runner — run the pipeline at a fixed interval"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Interval in minutes between runs (default: 60)",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("DATA_DIR", str(PROJECT_ROOT / "data")),
        help="Data directory (default: project data/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process without actual publishing",
    )
    args = parser.parse_args()

    logger = setup_logging(args.data_dir)
    logger.info("SMA Schedule Runner started — interval=%d minute(s), dry_run=%s", args.interval, args.dry_run)

    import schedule as schedule_lib

    def job() -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info("[%s] Starting pipeline run...", ts)
        try:
            count = run_pipeline(dry_run=args.dry_run)
            logger.info("[%s] Completed: %d videos processed", ts, count)
        except Exception as e:
            logger.error("[%s] Pipeline error: %s", ts, e, exc_info=True)

    schedule_lib.every(args.interval).minutes.do(job)

    # Run immediately on start
    job()

    logger.info("Scheduler running. Press Ctrl+C to stop.")
    try:
        while True:
            schedule_lib.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped. Goodbye!")


if __name__ == "__main__":
    main()
