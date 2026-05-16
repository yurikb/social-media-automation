import subprocess
import json
from pathlib import Path


def detect_silence(
    audio_path: str,
    threshold: float = -30.0,
    min_duration: float = 0.5,
) -> list[tuple[float, float]]:
    """Detect silent portions in an audio file.

    Args:
        audio_path: Path to audio file
        threshold: Silence threshold in dB
        min_duration: Minimum silence duration in seconds

    Returns:
        List of (start, end) tuples for silent portions
    """
    cmd = [
        "ffmpeg",
        "-i", audio_path,
        "-af", f"silencedetect=noise={threshold}dB:d={min_duration}",
        "-f", "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    silence_ranges = []
    start = None
    for line in result.stderr.split("\n"):
        if "silence_start:" in line:
            start = float(line.split(":")[1].strip())
        elif "silence_end:" in line and start is not None:
            end = float(line.split(":")[1].split("|")[0].strip())
            silence_ranges.append((start, end))
            start = None

    return silence_ranges


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from a video file.

    Args:
        video_path: Path to video file
        output_path: Path for output audio

    Returns:
        Path to the extracted audio
    """
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-y",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def analyze_audio_energy(audio_path: str, window_size: float = 0.1) -> list[float]:
    """Analyze audio energy over time for highlight detection.

    Args:
        audio_path: Path to audio file
        window_size: Analysis window in seconds

    Returns:
        List of energy values per window
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-f", "lavfi",
        "-i", f"amovie={audio_path},astats=metadata=1:reset={window_size}",
        "-show_entries", "frame_tags=lavfi.astats.Overall.RMS_level",
        "-of", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    try:
        data = json.loads(result.stdout)
        return [
            float(frame["tags"]["lavfi.astats.Overall.RMS_level"])
            for frame in data.get("frames", [])
            if "lavfi.astats.Overall.RMS_level" in frame.get("tags", {})
        ]
    except (json.JSONDecodeError, KeyError):
        return []