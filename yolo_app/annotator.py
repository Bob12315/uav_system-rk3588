from __future__ import annotations

import cv2

try:
    from .config import AppConfig
    from .models import CurrentTarget, Track
except ImportError:
    from config import AppConfig
    from models import CurrentTarget, Track


class Annotator:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def annotate(
        self,
        frame,
        tracks: list[Track],
        current_target: CurrentTarget,
        locked_track_id: int | None,
        fps: float = 0.0,
        latency_ms: float = 0.0,
    ):
        image = frame.copy()
        h, w = image.shape[:2]
        self._draw_crosshair(image, w, h)

        if self.cfg.show_all_tracks:
            for track in tracks:
                is_locked = locked_track_id is not None and track.track_id == locked_track_id
                self._draw_track(image, track, is_locked=is_locked)
                if is_locked:
                    self._draw_target_vector(image, w, h, track)

        self._draw_status(image, current_target, locked_track_id, fps, latency_ms)
        return image

    def _draw_track(self, image, track: Track, is_locked: bool) -> None:
        color = (0, 255, 255) if is_locked else (0, 200, 0)
        thickness = max(3, self.cfg.line_width + 1) if is_locked else self.cfg.line_width
        x1, y1, x2, y2 = map(int, [track.x1, track.y1, track.x2, track.y2])
        cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)

        prefix = "LOCKED " if is_locked else ""
        label = f"{prefix}{track.class_name} #{track.track_id} {track.confidence:.2f}"
        self._draw_label(image, label, x1, max(20, y1 - 8), color)
        if is_locked:
            cv2.circle(image, (int(track.cx), int(track.cy)), 4, color, -1)

    def _draw_status(
        self,
        image,
        current_target: CurrentTarget,
        locked_track_id: int | None,
        fps: float,
        latency_ms: float,
    ) -> None:
        rows = [
            f"NPU INT8: {fps:.1f} FPS  {latency_ms:.1f} ms",
            f"state: {current_target.tracking_state}",
            f"locked_track_id: {locked_track_id if locked_track_id is not None else -1}",
            f"lost_count: {current_target.lost_count}",
            f"bbox: {current_target.w:.0f}x{current_target.h:.0f}",
            f"target_size: {current_target.target_size:.3f}",
            f"ex: {current_target.ex:.3f}",
            f"ey: {current_target.ey:.3f}",
        ]
        y = 28
        for row in rows:
            self._draw_label(image, row, 12, y, (255, 255, 255), background=(20, 20, 20))
            y += 26

    def _draw_crosshair(self, image, width: int, height: int) -> None:
        center = (width // 2, height // 2)
        color = (255, 255, 255)
        cv2.drawMarker(
            image,
            center,
            color,
            markerType=cv2.MARKER_CROSS,
            markerSize=20,
            thickness=1,
        )

    def _draw_target_vector(self, image, width: int, height: int, track: Track) -> None:
        cv2.line(
            image,
            (width // 2, height // 2),
            (int(track.cx), int(track.cy)),
            (0, 255, 255),
            1,
        )

    def _draw_label(self, image, text: str, x: int, y: int, color, background=None) -> None:
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.6
        thickness = 1
        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        if background is not None:
            cv2.rectangle(image, (x - 4, y - th - 4), (x + tw + 4, y + baseline + 4), background, -1)
        cv2.putText(image, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)
