from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MissionStageInput:
    timestamp: float = 0.0
    dt: float = 0.0

    fused_valid: bool = False
    target_valid: bool = False
    target_locked: bool = False
    vision_valid: bool = False
    drone_valid: bool = False
    gimbal_valid: bool = False
    control_allowed: bool = False

    track_id: int | None = None
    track_switched: bool = False
    target_stable: bool = False
    tracking_state: str = "lost"

    ex_cam: float = 0.0
    ey_cam: float = 0.0
    ex_body: float = 0.0
    ey_body: float = 0.0

    gimbal_yaw: float = 0.0
    gimbal_pitch: float = 0.0

    yaw_rate: float = 0.0

    target_size: float = 0.0
    target_size_valid: bool = False

    fusion_age_s: float = float("inf")
    vision_age_s: float = float("inf")
    drone_age_s: float = float("inf")
    gimbal_age_s: float = float("inf")


@dataclass(slots=True)
class MissionStageStatus:
    mode_name: str = ""
    active: bool = False
    valid: bool = False
    hold_reason: str = ""
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class FlightCommand:
    vx_cmd: float = 0.0
    vy_cmd: float = 0.0
    vz_cmd: float = 0.0
    yaw_rate_cmd: float = 0.0
    gimbal_yaw_rate_cmd: float = 0.0
    gimbal_pitch_rate_cmd: float = 0.0
    gimbal_yaw_angle_cmd: float | None = None
    gimbal_pitch_angle_cmd: float | None = None
    enable_body: bool = False
    enable_gimbal: bool = False
    enable_gimbal_angle: bool = False
    enable_approach: bool = False
    active: bool = False
    valid: bool = False
