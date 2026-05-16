#!/usr/bin/env python3
"""Standalone health check script for SMA.

Can be run directly without installing the package:
    python scripts/health_check.py
    python scripts/health_check.py --json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add src to path so we can import the health module
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root / "src"))

from services.health import run_health_check


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="health_check",
        description="SMA Health Check — validate dependencies, config, and data",
    )
    parser.add_argument(
        "--config",
        default=str(project_root / "config"),
        help="Config directory (default: ../config)",
    )
    parser.add_argument(
        "--data",
        default=str(project_root / "data"),
        help="Data directory (default: ../data)",
    )
    parser.add_argument(
        "--env",
        default=str(project_root / ".env"),
        help="Path to .env file (default: ../.env)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    args = parser.parse_args()

    report = run_health_check(
        config_dir=args.config,
        data_dir=args.data,
        env_path=args.env,
    )

    if args.json:
        import json
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status_icons = {"ok": "✓", "warn": "⚠", "error": "✗"}
        status_styles = {"ok": "\033[32m", "warn": "\033[33m", "error": "\033[31m"}
        reset = "\033[0m"

        print(f"\n{'='*60}")
        print(f"  SMA Health Check")
        print(f"{'='*60}")

        for check in report.checks:
            icon = status_icons.get(check.status, "?")
            color = status_styles.get(check.status, "")
            print(f"  {color}{icon}{reset} {check.name:20s} {color}{check.status}{reset}")
            print(f"    {check.message}")

        print(f"\n{'='*60}")
        if report.overall == "ok":
            print(f"  {status_styles['ok']}All checks passed — SMA is healthy{reset}")
        elif report.overall == "warn":
            print(f"  {status_styles['warn']}Some checks have warnings — review above{reset}")
        else:
            print(f"  {status_styles['error']}Some checks failed — SMA may not work correctly{reset}")
        print(f"{'='*60}\n")

    sys.exit(report.exit_code)


if __name__ == "__main__":
    main()
