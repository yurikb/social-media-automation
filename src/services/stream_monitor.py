import subprocess
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

import numpy as np

from src.models.clip_candidate import ClipCandidate, StreamInfo
from src.services.clip_creator import ClipCreator


class StreamMonitor:
    def __init__(
        self,
        clip_creator: ClipCreator,
        data_dir: str,
        energy_threshold_std: float = 1.5,
        min_peak_duration: float = 3.0,
        cooldown_seconds: int = 120,
    ):
        self.clip_creator = clip_creator
        self.audio_dir = Path(data_dir) / "audio_buffer"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.energy_threshold_std = energy_threshold_std
        self.min_peak_duration = min_peak_duration
        self.cooldown_seconds = cooldown_seconds
        self._running = False
        self._threads: list[threading.Thread] = []
        self._last_clip_time: dict[str, float] = {}

    def monitor_streamer(
        self,
        streamer_name: str,
        channel_id: str,
        broadcaster_id: str,
        on_clip: Optional[Callable] = None,
    ) -> None:
        channel_url = f"https://www.twitch.tv/{channel_id}"

        streamlink_cmd = [
            "streamlink",
            channel_url,
            "audio_only",
            "--stdout",
        ]

        try:
            proc = subprocess.Popen(
                streamlink_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=10 ** 8,
            )
        except FileNotFoundError:
            print(f"[MONITOR] streamlink not found for {streamer_name}")
            return

        buffer = []
        sample_rate = 16000
        window_samples = int(sample_rate * 0.5)

        while self._running:
            try:
                raw = proc.stdout.read(window_samples * 2)
                if not raw:
                    break
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                energy = float(np.sqrt(np.mean(samples ** 2)))
                buffer.append(energy)
                if len(buffer) > 200:
                    buffer.pop(0)
                if len(buffer) >= 20:
                    self._check_for_peak(buffer, streamer_name, broadcaster_id, on_clip)
            except (OSError, ValueError):
                break

        proc.kill()

    def _check_for_peak(
        self,
        buffer: list[float],
        streamer_name: str,
        broadcaster_id: str,
        on_clip: Optional[Callable],
    ) -> None:
        if len(buffer) < 10:
            return
        arr = np.array(buffer[-50:])
        mean = float(np.mean(arr))
        std = float(np.std(arr))
        if std < 0.1:
            return
        threshold = mean + std * self.energy_threshold_std
        current = buffer[-1]
        if current <= threshold:
            return
        now = time.time()
        last = self._last_clip_time.get(streamer_name, 0)
        if now - last < self.cooldown_seconds:
            return

        peak_count = sum(1 for v in buffer[-int(self.min_peak_duration / 0.5):] if v > threshold)
        if peak_count < self.min_peak_duration / 0.5 * 0.5:
            return

        print(f"[MONITOR] PEAK detected for {streamer_name} (energy: {current:.1f} > {threshold:.1f})")
        self._last_clip_time[streamer_name] = now

        if on_clip:
            candidate = self.clip_creator.capture_moment(
                broadcaster_id=broadcaster_id,
                streamer_name=streamer_name,
            )
            if candidate:
                on_clip(candidate)

    def start(self, streamers: list[dict]) -> None:
        self._running = True
        for s in streamers:
            t = threading.Thread(
                target=self.monitor_streamer,
                args=(s["name"], s["channel_id"], s.get("broadcaster_id", ""), None),
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        print(f"[MONITOR] Monitoring {len(streamers)} streamers")

    def stop(self) -> None:
        self._running = False
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()
