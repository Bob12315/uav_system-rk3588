from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class OverheadGimbalConfig:
    downward_pitch_rad: float = -1.5707963267948966
    deadband_yaw: float = 0.02
    deadband_pitch: float = 0.03
    kp_yaw: float = 0.0
    kp_pitch: float = 1.5
    max_yaw_rate: float = 0.3
    max_pitch_rate: float = 0.8
    yaw_sign: float = 1.0
    pitch_sign: float = -1.0


@dataclass(slots=True)
class OverheadBodyConfig:
    kp_vy: float = 1.0
    kd_vy: float = 0.0
    use_derivative_vy: bool = False
    deadband_ex_cam: float = 0.02
    kp_yaw: float = 0.0
    deadband_yaw: float = 0.05
    max_vy: float = 1.0
    max_yaw_rate: float = 1.0
    vy_sign: float = 1.0
    yaw_sign: float = 1.0
    dt_min: float = 1e-3


@dataclass(slots=True)
class OverheadApproachConfig:
    kp_vx: float = 1.0
    kd_vx: float = 0.0
    use_derivative: bool = False
    deadband_ey_cam: float = 0.02
    vx_sign: float = 1.0
    allow_backward: bool = False
    max_forward_vx: float = 0.8
    max_backward_vx: float = 0.2
    dt_min: float = 1e-3


@dataclass(slots=True)
class OverheadHoldConfig:
    gimbal: OverheadGimbalConfig = field(default_factory=OverheadGimbalConfig)
    body: OverheadBodyConfig = field(default_factory=OverheadBodyConfig)
    approach: OverheadApproachConfig = field(default_factory=OverheadApproachConfig)
    max_vision_age_s: float = 0.3
    max_drone_age_s: float = 0.3
    max_gimbal_age_s: float = 0.3
    require_gimbal_fresh_for_gimbal: bool = False
    require_gimbal_fresh_for_body: bool = True
    require_gimbal_fresh_for_approach: bool = True
