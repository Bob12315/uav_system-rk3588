from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FixedDownwardHoldConfig:
    kp_vy: float = 1.0
    kd_vy: float = 0.0
    use_derivative_vy: bool = False
    deadband_ex_cam: float = 0.02
    max_vy: float = 1.0
    vy_sign: float = 1.0

    kp_vx: float = 1.0
    kd_vx: float = 0.0
    use_derivative_vx: bool = False
    deadband_ey_cam: float = 0.02
    max_forward_vx: float = 0.8
    max_backward_vx: float = 0.2
    allow_backward: bool = True
    vx_sign: float = -1.0

    max_vision_age_s: float = 0.3
    max_drone_age_s: float = 0.3
    require_target_locked: bool = True
    dt_min: float = 1e-3
