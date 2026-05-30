from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ApproachGimbalConfig:
    kp_yaw: float = 5.0
    kp_pitch: float = 1.8
    ki_yaw: float = 0.02
    ki_pitch: float = 0.0
    kd_yaw: float = 0.2
    kd_pitch: float = 0.0
    use_derivative: bool = False
    deadband_x: float = 0.02
    deadband_y: float = 0.04
    center_hold_yaw_threshold: float = 0.018
    center_hold_pitch_threshold: float = 0.04
    integral_limit: float = 0.25
    derivative_limit_yaw: float | None = 1.5
    derivative_limit_pitch: float | None = 1.0
    max_yaw_rate: float = 20.0
    max_pitch_rate: float = 0.5
    yaw_sign: float = 1.0
    pitch_sign: float = -1.0
    dt_min: float = 1e-3


@dataclass(slots=True)
class ApproachBodyConfig:
    kp_vy: float = 0.0
    kd_vy: float = 0.0
    use_derivative_vy: bool = False
    kp_yaw: float = 0.2
    kp_ex_cam_yaw: float = 0.0
    kd_yaw: float = 0.0
    use_derivative_yaw: bool = False
    deadband_ex_body: float = 0.02
    deadband_gimbal_yaw: float = 0.02
    yaw_rate_damping: float = 0.8
    yaw_step_rate: float = 0.0
    max_vy: float = 0.0
    max_yaw_rate: float = 0.3
    vy_sign: float = 1.0
    yaw_sign: float = 1.0
    dt_min: float = 1e-3


@dataclass(slots=True)
class ApproachForwardConfig:
    target_size_ref: float = 0.2
    kp_vx: float = 2.0
    kd_vx: float = 0.0
    use_derivative: bool = False
    deadband_size: float = 0.02
    ex_cam_slowdown_start: float = 0.15
    max_ex_cam_for_approach: float = 0.35
    max_forward_vx: float = 0.8
    max_backward_vx: float = 0.0
    vx_sign: float = 1.0
    allow_backward: bool = False
    min_valid_target_size: float = 0.01
    dt_min: float = 1e-3


@dataclass(slots=True)
class ApproachTrackConfig:
    gimbal: ApproachGimbalConfig = field(default_factory=ApproachGimbalConfig)
    body: ApproachBodyConfig = field(default_factory=ApproachBodyConfig)
    approach: ApproachForwardConfig = field(default_factory=ApproachForwardConfig)
    max_vision_age_s: float = 0.3
    max_drone_age_s: float = 0.3
    max_gimbal_age_s: float = 0.3
    require_target_locked_for_body: bool = True
    require_target_stable_for_approach: bool = True
    require_yaw_aligned_for_approach: bool = True
    require_gimbal_fresh_for_gimbal: bool = False
    require_gimbal_fresh_for_body: bool = True
    require_gimbal_fresh_for_approach: bool = True
    yaw_align_thresh_rad: float = 0.35
    yaw_align_enter_thresh_rad: float = 0.15
    yaw_align_exit_thresh_rad: float = 0.30
    yaw_align_hold_s: float = 0.4
    min_yaw_quality: float = 0.0
