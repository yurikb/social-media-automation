"""Health check service for SMA — validates dependencies, config, and data layout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import importlib.metadata


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    status: str  # "ok" | "warn" | "error"
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class HealthReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall(self) -> str:
        statuses = {c.status for c in self.checks}
        if "error" in statuses:
            return "error"
        if "warn" in statuses:
            return "warn"
        return "ok"

    @property
    def exit_code(self) -> int:
        return 0 if self.overall == "ok" else 1

    def add(self, check: CheckResult) -> None:
        self.checks.append(check)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "exit_code": self.exit_code,
            "checks": [asdict(c) for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_ffmpeg() -> CheckResult:
    """Verify ffmpeg binary is on PATH and executable."""
    path = shutil.which("ffmpeg")
    if path is None:
        return CheckResult("ffmpeg", "error", "ffmpeg not found on PATH")
    try:
        proc = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        first_line = proc.stdout.splitlines()[0] if proc.stdout else ""
        return CheckResult("ffmpeg", "ok", first_line, {"path": path})
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CheckResult("ffmpeg", "error", f"ffmpeg found at {path} but failed: {exc}")


def check_ffprobe() -> CheckResult:
    """Verify ffprobe binary is on PATH."""
    path = shutil.which("ffprobe")
    if path is None:
        return CheckResult("ffprobe", "error", "ffprobe not found on PATH")
    return CheckResult("ffprobe", "ok", f"ffprobe available at {path}", {"path": path})


def check_whisper() -> CheckResult:
    """Verify openai-whisper Python package is installed."""
    try:
        version = importlib.metadata.version("openai-whisper")
        return CheckResult("whisper", "ok", f"openai-whisper {version}", {"version": version})
    except importlib.metadata.PackageNotFoundError:
        return CheckResult("whisper", "error", "openai-whisper package not installed")


def check_python_packages() -> CheckResult:
    """Verify all required Python packages are installed."""
    required = [
        "httpx",
        "pydantic",
        "python-dotenv",
        "openai-whisper",
        "ffmpeg-python",
        "numpy",
        "pillow",
        "schedule",
        "rich",
    ]
    missing: list[str] = []
    found: dict[str, str] = {}
    for pkg in required:
        try:
            ver = importlib.metadata.version(pkg)
            found[pkg] = ver
        except importlib.metadata.PackageNotFoundError:
            missing.append(pkg)
    if missing:
        return CheckResult(
            "python_packages",
            "error",
            f"Missing packages: {', '.join(missing)}",
            {"missing": missing, "found": found},
        )
    return CheckResult(
        "python_packages",
        "ok",
        f"All {len(required)} required packages installed",
        {"found": found},
    )


def check_config_files(config_dir: str) -> CheckResult:
    """Verify config directory exists and all JSON files are valid."""
    config_path = Path(config_dir)
    if not config_path.is_dir():
        return CheckResult("config", "error", f"Config directory not found: {config_dir}")

    required_files = ["pipeline.json", "streamers.json", "platforms.json"]
    optional_files = ["ngrok.yml"]
    missing: list[str] = []
    invalid: list[str] = []
    valid: list[str] = []

    for fname in required_files:
        fpath = config_path / fname
        if not fpath.exists():
            missing.append(fname)
            continue
        if fname.endswith(".json"):
            try:
                json.loads(fpath.read_text(encoding="utf-8"))
                valid.append(fname)
            except (json.JSONDecodeError, OSError) as exc:
                invalid.append(f"{fname}: {exc}")
        else:
            valid.append(fname)

    for fname in optional_files:
        fpath = config_path / fname
        if fpath.exists():
            valid.append(f"{fname} (optional)")

    details: dict[str, Any] = {
        "config_dir": str(config_path),
        "valid": valid,
        "missing": missing,
        "invalid": invalid,
    }

    if missing and invalid:
        return CheckResult("config", "error", f"Missing: {', '.join(missing)}; Invalid: {', '.join(invalid)}", details)
    if missing:
        return CheckResult("config", "warn", f"Missing config files: {', '.join(missing)}", details)
    if invalid:
        return CheckResult("config", "error", f"Invalid config files: {', '.join(invalid)}", details)
    return CheckResult("config", "ok", f"All config files valid ({len(required_files)} files)", details)


def check_data_directory(data_dir: str) -> CheckResult:
    """Verify data directory and expected subdirectories exist."""
    data_path = Path(data_dir)
    if not data_path.is_dir():
        return CheckResult("data_dir", "error", f"Data directory not found: {data_dir}")

    expected_subdirs = ["clips", "enhanced", "pending", "raw"]
    missing: list[str] = []
    present: list[str] = []

    for subdir in expected_subdirs:
        if (data_path / subdir).is_dir():
            present.append(subdir)
        else:
            missing.append(subdir)

    details: dict[str, Any] = {
        "data_dir": str(data_path),
        "present": present,
        "missing": missing,
    }

    if missing:
        return CheckResult(
            "data_dir",
            "warn",
            f"Missing subdirectories: {', '.join(missing)}",
            details,
        )
    return CheckResult(
        "data_dir",
        "ok",
        f"Data directory OK ({len(present)} subdirectories)",
        details,
    )


def check_env_file(env_path: str) -> CheckResult:
    """Verify .env file exists and has basic structure."""
    env_p = Path(env_path)
    if not env_p.exists():
        return CheckResult("env_file", "warn", f".env file not found at {env_path}")

    try:
        content = env_p.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult("env_file", "error", f"Cannot read .env: {exc}")

    lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
    keys = [l.split("=", 1)[0].strip() for l in lines if "=" in l]

    has_twitch = any(k.startswith("TWITCH_") for k in keys)
    has_data = "DATA_DIR" in keys

    details: dict[str, Any] = {
        "path": str(env_p),
        "total_keys": len(keys),
        "has_twitch_keys": has_twitch,
        "has_data_dir": has_data,
    }

    if not keys:
        return CheckResult("env_file", "warn", ".env file exists but has no keys", details)

    return CheckResult("env_file", "ok", f".env file OK ({len(keys)} keys found)", details)


def check_disk_space(data_dir: str, min_mb: int = 500) -> CheckResult:
    """Check available disk space on the data directory's drive."""
    try:
        usage = shutil.disk_usage(data_dir)
        free_mb = usage.free / (1024 * 1024)
        total_mb = usage.free / (1024 * 1024)
        details = {
            "free_mb": round(free_mb, 1),
            "total_mb": round(total_mb, 1),
            "min_mb": min_mb,
        }
        if free_mb < min_mb:
            return CheckResult(
                "disk_space",
                "warn",
                f"Low disk space: {free_mb:.0f} MB free (min {min_mb} MB)",
                details,
            )
        return CheckResult(
            "disk_space",
            "ok",
            f"Disk space OK: {free_mb:.0f} MB free",
            details,
        )
    except OSError as exc:
        return CheckResult("disk_space", "warn", f"Cannot check disk space: {exc}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_health_check(
    config_dir: str | None = None,
    data_dir: str | None = None,
    env_path: str | None = None,
) -> HealthReport:
    """Run all health checks and return a report."""
    report = HealthReport()

    # Resolve defaults relative to project layout
    project_root = Path(__file__).resolve().parent.parent.parent

    if config_dir is None:
        config_dir = str(project_root / "config")
    if data_dir is None:
        data_dir = str(project_root / "data")
    if env_path is None:
        env_path = str(project_root / ".env")

    # Dependency checks
    report.add(check_ffmpeg())
    report.add(check_ffprobe())
    report.add(check_whisper())
    report.add(check_python_packages())

    # Config checks
    report.add(check_config_files(config_dir))
    report.add(check_env_file(env_path))

    # Data directory checks
    report.add(check_data_directory(data_dir))
    report.add(check_disk_space(data_dir))

    return report
