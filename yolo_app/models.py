from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Track:
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def w(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass(slots=True)
class DetectionObject:
    track_id: int | None
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    cx: float
    cy: float
    w: float
    h: float
    ex: float
    ey: float
    target_size: float

    @classmethod
    def from_track(
        cls,
        track: Track,
        image_width: int,
        image_height: int,
    ) -> "DetectionObject":
        width = max(1, int(image_width))
        height = max(1, int(image_height))
        return cls(
            track_id=track.track_id,
            class_id=int(track.class_id),
            class_name=str(track.class_name),
            confidence=float(track.confidence),
            x1=float(track.x1),
            y1=float(track.y1),
            x2=float(track.x2),
            y2=float(track.y2),
            cx=float(track.cx),
            cy=float(track.cy),
            w=float(track.w),
            h=float(track.h),
            ex=_normalize_error(track.cx, width),
            ey=_normalize_error(track.cy, height),
            target_size=max(track.w / width, track.h / height),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SceneDetections:
    timestamp: float
    frame_id: int
    image_width: int
    image_height: int
    detections: list[DetectionObject] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CurrentTarget:
    timestamp: float
    frame_id: int
    target_valid: bool
    tracking_state: str
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    cx: float
    cy: float
    w: float
    h: float
    ex: float
    ey: float
    image_width: int
    image_height: int
    target_size: float
    lost_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CommandMessage:
    action: str
    track_id: int | None = None


@dataclass(slots=True)
class FramePacket:
    frame: Any
    frame_id: int
    timestamp: float


def _normalize_error(value: float, extent: int) -> float:
    safe_extent = max(1, int(extent))
    return (float(value) - safe_extent / 2.0) / (safe_extent / 2.0)
