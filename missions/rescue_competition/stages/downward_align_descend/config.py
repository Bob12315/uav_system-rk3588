from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DownwardAlignDescendConfig:
    kp_vx: float = 0.8
    kp_vy: float = 0.8
    max_vx_mps: float = 0.4
    max_vy_mps: float = 0.4
    descend_speed_mps: float = 0.2
    max_ex_cam: float = 0.06
    max_ey_cam: float = 0.06
    deadband_ex_cam: float = 0.015
    deadband_ey_cam: float = 0.015
    max_vision_age_s: float = 0.3
    max_drone_age_s: float = 0.3
    require_target_locked: bool = True
    vx_sign: float = -1.0
    vy_sign: float = 1.0
    dt_min: float = 1e-3
