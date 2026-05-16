import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src.models.enhanced_video import CaptionStyle, EnhancedVideo, Thumbnail


class EnhancementService:
    def __init__(self, data_dir: str, config_path: str):
        self.data_dir = Path(data_dir)
        self.enhanced_dir = self.data_dir / "enhanced"
        self.enhanced_dir.mkdir(parents=True, exist_ok=True)

        with open(Path(config_path) / "pipeline.json") as f:
            self.config = json.load(f)

    def generate_captions(
        self,
        video_path: str,
        language: str = "pt-BR",
        model_size: str = "base",
    ) -> Optional[str]:
        try:
            import whisper
        except ImportError:
            return None

        model = whisper.load_model(model_size)
        audio_path = video_path.replace(".mp4", ".wav")
        from src.utils.audio import extract_audio
        extract_audio(video_path, audio_path)

        result = model.transcribe(audio_path, language=language.split("-")[0])

        srt_path = str(self.enhanced_dir / f"{Path(video_path).stem}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(result["segments"], 1):
                start = self._format_srt_time(segment["start"])
                end = self._format_srt_time(segment["end"])
                text = segment["text"].strip()
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

        ass_path = str(self.enhanced_dir / f"{Path(video_path).stem}.ass")
        self._generate_ass(result["segments"], ass_path)

        return srt_path

    def _format_srt_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _generate_ass(self, segments: list[dict], output_path: str) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("[Script Info]\n")
            f.write("ScriptType: v4.00+\n")
            f.write("PlayResX: 1080\n")
            f.write("PlayResY: 1920\n\n")
            f.write("[V4+ Styles]\n")
            f.write("Format: Name, Fontname, Fontsize, PrimaryColour, "
                    "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                    "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
                    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
                    "MarginV, Encoding\n")
            f.write("Style: Karaoke,Arial,56,&H00FFFFFF,&H000000FF,"
                    "&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,"
                    "2,30,30,30,1\n\n")
            f.write("[Events]\n")
            f.write("Format: Layer, Start, End, Style, Name, MarginL, "
                    "MarginR, MarginV, Effect, Text\n")
            for seg in segments:
                start = self._format_ass_time(seg["start"])
                end = self._format_ass_time(seg["end"])
                text = seg["text"].strip().replace("\n", "\\N")
                f.write(f"Dialogue: 0,{start},{end},Karaoke,,0,0,0,,{text}\n")

    def _format_ass_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h:01d}:{m:02d}:{s:05.2f}"

    def apply_captions(
        self,
        video_path: str,
        captions_path: str,
        ass_path: Optional[str] = None,
    ) -> str:
        output = str(self.enhanced_dir / f"{Path(video_path).stem}_captioned.mp4")

        ass_path = str(Path(ass_path).resolve()) if ass_path else None
        if ass_path and Path(ass_path).exists():
            local_ass = str(Path(video_path).parent / "_sub.ass")
            shutil.copy2(ass_path, local_ass)
            filter_chain = "ass=_sub.ass"
        elif Path(captions_path).exists():
            local_srt = str(Path(video_path).parent / "_sub.srt")
            shutil.copy2(captions_path, local_srt)
            filter_chain = "subtitles=_sub.srt"
        else:
            return video_path

        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", filter_chain,
            "-c:a", "copy",
            "-y",
            output,
        ]
        subprocess.run(cmd, check=True, capture_output=True, cwd=str(Path(video_path).parent))
        return output

    def generate_thumbnail(
        self,
        video_path: str,
        text: str = "",
        style: str = "text_overlay",
    ) -> Optional[Thumbnail]:
        thumb_path = str(self.enhanced_dir / f"{Path(video_path).stem}_thumb.jpg")

        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-ss", "00:00:02",
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            thumb_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        if text:
            try:
                img = Image.open(thumb_path).convert("RGBA")
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)

                box_height = int(img.height * 0.3)
                draw.rectangle(
                    [(0, img.height - box_height), (img.width, img.height)],
                    fill=(0, 0, 0, 180),
                )

                font_size = int(img.width * 0.06)
                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except (OSError, IOError):
                    font = ImageFont.load_default()

                lines = self._wrap_text(text, font, img.width - 80)
                y_offset = img.height - box_height + 20
                for line in lines:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_w = bbox[2] - bbox[0]
                    x = (img.width - text_w) // 2
                    draw.text((x, y_offset), line, fill="white", font=font)
                    y_offset += font_size + 5

                img = Image.alpha_composite(img, overlay).convert("RGB")
                img.save(thumb_path, "JPEG", quality=85)
            except Exception:
                pass

        return Thumbnail(path=thumb_path, style=style, description=text)

    def _wrap_text(self, text: str, font, max_width: int) -> list[str]:
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            bbox = font.getbbox(test)
            if bbox and (bbox[2] - bbox[0]) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [text]

    def build_overlay_text(
        self,
        video_path: str,
        hook_text: str,
        duration_ms: int = 1500,
    ) -> str:
        output = str(self.enhanced_dir / f"{Path(video_path).stem}_hooked.mp4")

        textfile = str(self.enhanced_dir / "_hook.txt")
        with open(textfile, "w", encoding="utf-8") as f:
            f.write(hook_text)

        fontfile = str(self.enhanced_dir / "_arial.ttf")
        if not Path(fontfile).exists():
            shutil.copy2(r"C:\Windows\Fonts\arial.ttf", fontfile)

        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", (
                f"drawtext=textfile=_hook.txt:"
                f"fontfile=_arial.ttf:"
                f"fontsize=64:fontcolor=white:"
                f"box=1:boxcolor=black@0.6:"
                f"x=(w-text_w)/2:y=h*0.15:"
                f"enable=between(t\\,0\\,{duration_ms/1000})"
            ),
            "-c:a", "copy",
            "-y",
            output,
        ]
        subprocess.run(cmd, check=True, capture_output=True, cwd=str(self.enhanced_dir))
        return output

    def enhance(
        self,
        clip_path: str,
        hook_text: str = "",
        title: str = "",
        hashtags: list[str] = None,
        caption_style: Optional[CaptionStyle] = None,
    ) -> EnhancedVideo:
        style = caption_style or CaptionStyle()

        captions_path = self.generate_captions(clip_path)
        final_path = clip_path

        ass_path = str(self.enhanced_dir / f"{Path(clip_path).stem}.ass")
        if captions_path and Path(ass_path).exists():
            final_path = self.apply_captions(clip_path, captions_path, ass_path)

        if hook_text:
            final_path = self.build_overlay_text(final_path, hook_text)

        thumb = self.generate_thumbnail(final_path, text=hook_text or title)

        return EnhancedVideo(
            clip_path=final_path,
            captions_path=captions_path,
            thumbnails=[thumb] if thumb else [],
            title=title,
            hashtags=hashtags or [],
            hook_text=hook_text,
        )
