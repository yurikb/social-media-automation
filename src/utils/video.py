import subprocess
import json
from pathlib import Path
from typing import Optional


def get_video_info(video_path: str) -> dict:
    """Get video metadata using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    video_stream = next(
        (s for s in data["streams"] if s["codec_type"] == "video"),
        None
    )
    if not video_stream:
        raise ValueError(f"No video stream found in {video_path}")

    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "duration": float(data["format"]["duration"]),
        "fps": eval(video_stream["r_frame_rate"]),  # e.g., "30/1" -> 30.0
        "codec": video_stream["codec_name"],
    }


def reframe_to_vertical(src_width: int, src_height: int, center_x: float = 0.5) -> tuple[int, int, int, int]:
    """Calculate crop parameters to reframe a video to 9:16 vertical.

    Args:
        src_width: Source video width in pixels
        src_height: Source video height in pixels
        center_x: Horizontal center point (0.0-1.0) for cropping

    Returns:
        Tuple of (crop_x, crop_y, crop_width, crop_height)
    """
    target_ratio = 9 / 16
    src_ratio = src_width / src_height

    if src_ratio > target_ratio:
        # Source is wider, crop horizontally
        crop_h = src_height
        crop_w = int(src_height * target_ratio)
        crop_x = int((src_width - crop_w) * center_x)
        crop_y = 0
    else:
        # Source is taller or same ratio, crop vertically
        crop_w = src_width
        crop_h = int(src_width / target_ratio)
        crop_x = 0
        crop_y = int((src_height - crop_h) * center_x)

    return crop_x, crop_y, crop_w, crop_h


class VideoProcessor:
    """FFmpeg-based video processing for clip creation."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_clip(
        self,
        input_path: str,
        output_path: str,
        start_time: float,
        duration: float,
    ) -> str:
        """Extract a clip from a video file.

        Args:
            input_path: Path to source video
            output_path: Path for output clip
            start_time: Start time in seconds
            duration: Duration in seconds

        Returns:
            Path to the output clip
        """
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-ss", str(start_time),
            "-t", str(duration),
            "-c", "copy",
            "-y",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path

    def reframe_vertical(
        self,
        input_path: str,
        output_path: str,
        center_x: float = 0.5,
        resolution: str = "1080x1920",
    ) -> str:
        """Reframe a video to 9:16 vertical format.

        Args:
            input_path: Path to source video
            output_path: Path for output video
            center_x: Horizontal center for cropping (0.0-1.0)
            resolution: Output resolution (default: 1080x1920)

        Returns:
            Path to the reframed video
        """
        info = get_video_info(input_path)
        crop_x, crop_y, crop_w, crop_h = reframe_to_vertical(
            info["width"], info["height"], center_x
        )

        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={resolution},setsar=1",
            "-c:a", "copy",
            "-y",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path

    def remove_silence(
        self,
        input_path: str,
        output_path: str,
        threshold: float = -30.0,
    ) -> str:
        """Remove silent portions from a video.

        Args:
            input_path: Path to source video
            output_path: Path for output video
            threshold: Audio threshold in dB (default: -30dB)

        Returns:
            Path to the processed video
        """
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-af", f"silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold={threshold}dB",
            "-c:v", "copy",
            "-y",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path

    def add_text_overlay(
        self,
        input_path: str,
        output_path: str,
        text: str,
        font_size: int = 48,
        position: str = "top",
    ) -> str:
        """Add text overlay to a video.

        Args:
            input_path: Path to source video
            output_path: Path for output video
            text: Text to overlay
            font_size: Font size in pixels
            position: Text position ("top", "center", "bottom")

        Returns:
            Path to the video with overlay
        """
        positions = {
            "top": f"x=(w-text_w)/2:y=50",
            "center": f"x=(w-text_w)/2:y=(h-text_h)/2",
            "bottom": f"x=(w-text_w)/2:y=h-50-text_h",
        }
        pos = positions.get(position, positions["top"])

        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-vf", f"drawtext=text='{text}':fontsize={font_size}:fontcolor=white:box=1:boxcolor=black@0.5:{pos}",
            "-c:a", "copy",
            "-y",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path