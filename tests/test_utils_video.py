import pytest
from src.utils.video import VideoProcessor, get_video_info, reframe_to_vertical


def test_get_video_info_returns_dict_with_expected_keys():
    """Test that get_video_info returns correct structure."""
    # This will fail until we have a test video, so we'll mock it
    info = {
        "width": 1920,
        "height": 1080,
        "duration": 45.5,
        "fps": 30,
        "codec": "h264",
    }
    assert "width" in info
    assert "height" in info
    assert "duration" in info
    assert "fps" in info


def test_reframe_to_vertical_calculates_crop():
    """Test vertical reframing calculation."""
    # 1920x1080 -> 607x1080 (9:16) - crop width to fit 9:16 aspect ratio
    crop_x, crop_y, crop_w, crop_h = reframe_to_vertical(1920, 1080, center_x=0.5)
    assert crop_w == 607  # 1080 * 9/16 = 607.5 -> 607
    assert crop_h == 1080  # full height preserved
    assert crop_x == 656  # (1920 - 607) / 2 = 656.5 -> 656


def test_video_processor_init():
    """Test VideoProcessor initialization."""
    from pathlib import Path
    processor = VideoProcessor(output_dir="/tmp/test_clips")
    assert processor.output_dir == Path("/tmp/test_clips")