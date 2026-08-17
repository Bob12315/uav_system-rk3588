from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FusionConfig:
    require_gimbal_feedback: bool = True


@dataclass(slots=True)
class PerceptionTarget:
    timestamp: float = 0.0
    frame_id: int = 0
    target_valid: bool = False
    tracking_state: str = "lost"
    track_id: int = -1
    class_name: str = ""
    confidence: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    w: float = 0.0
    h: float = 0.0
    image_width: float = 0.0
    image_height: float = 0.0
    target_size: float = 0.0
    ex: float = 0.0
    ey: float = 0.0
    lost_count: int = 0


@dataclass(slots=True)
class SceneObject:
    track_id: int | None = None
    class_id: int = -1
    class_name: str = ""
    confidence: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    w: float = 0.0
    h: float = 0.0
    ex: float = 0.0
    ey: float = 0.0
    target_size: float = 0.0


@dataclass(slots=True)
class SceneDetections:
    timestamp: float = 0.0
    frame_id: int = 0
    image_width: int = 0
    image_height: int = 0
    detections: list[SceneObject] = field(default_factory=list)
    valid: bool = False


@dataclass(slots=True)
class FusedState:
    timestamp: float = 0.0
    perception_timestamp: float = 0.0
    drone_timestamp: float = 0.0
    gimbal_timestamp: float = 0.0
    frame_id: int = 0
    target_valid: bool = False
    target_locked: bool = False
    track_id: int = -1
    tracking_state: str = "lost"
    ex_cam: float = 0.0
    ey_cam: float = 0.0
    bbox_w: float | None = None
    bbox_h: float | None = None
    bbox_area: float | None = None
    image_width: float | None = None
    image_height: float | None = None
    target_size: float | None = None
    gimbal_valid: bool = False
    gimbal_yaw: float = 0.0
    gimbal_pitch: float = 0.0
    ex_body: float = 0.0
    ey_body: float = 0.0
    vision_valid: bool = False
    drone_valid: bool = False
    yaw: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw_rate: float = 0.0
    # vx/vy/vz are body-frame velocities.
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    altitude: float = 0.0
    control_allowed: bool = False
    control_enabled: bool = False
    state_valid: bool = False
    fusion_valid: bool = False
