from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Any

import cv2


@dataclass(slots=True)
class RawFrameRecorderStatus:
    recording: bool
    path: str
    frames: int
    error: str


class RawFrameRecorder:
    DEFAULT_MAX_DURATION_S = 10.0 * 60.0

    def __init__(
        self,
        output_dir: str,
        fps: float,
        *,
        max_duration_s: float = DEFAULT_MAX_DURATION_S,
        monotonic: Any = time.monotonic,
    ) -> None:
        self.output_dir = Path(output_dir).expanduser()
        self.fps = fps if fps > 0 else 30.0
        self.max_duration_s = max(0.0, float(max_duration_s))
        self._monotonic = monotonic
        self._deadline_monotonic: float | None = None
        self.writer: cv2.VideoWriter | None = None
        self.path = ""
        self.frames = 0
        self.error = ""

    @property
    def recording(self) -> bool:
        return self.writer is not None

    def handle_command(self, action: str, frame_shape: tuple[int, ...]) -> None:
        if action == "recording_start":
            self.start(frame_shape)
        elif action == "recording_stop":
            self.stop()

    def start(self, frame_shape: tuple[int, ...]) -> RawFrameRecorderStatus:
        if self.writer is not None:
            self._refresh_deadline()
            return self.status()
        height, width = int(frame_shape[0]), int(frame_shape[1])
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.error = f"failed to create recording directory: {exc}"
            return self.status()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.output_dir / f"camera_{timestamp}.mp4"
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self.fps,
            (width, height),
        )
        if not writer.isOpened():
            writer.release()
            self.error = f"failed to open recording writer: {path}"
            return self.status()
        self.writer = writer
        self.path = str(path)
        self.frames = 0
        self.error = ""
        self._refresh_deadline()
        return self.status()

    def write(self, frame: Any) -> None:
        self.stop_if_expired()
        if self.writer is None:
            return
        self.writer.write(frame)
        self.frames += 1

    def stop(self) -> RawFrameRecorderStatus:
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        self._deadline_monotonic = None
        return self.status()

    def stop_if_expired(self, *, now_monotonic: float | None = None) -> bool:
        if self.writer is None or self._deadline_monotonic is None:
            return False
        now = self._monotonic() if now_monotonic is None else float(now_monotonic)
        if now < self._deadline_monotonic:
            return False
        self.stop()
        return True

    def _refresh_deadline(self) -> None:
        self._deadline_monotonic = self._monotonic() + self.max_duration_s

    def status(self) -> RawFrameRecorderStatus:
        return RawFrameRecorderStatus(
            recording=self.recording,
            path=self.path,
            frames=self.frames,
            error=self.error,
        )

    def close(self) -> None:
        self.stop()
