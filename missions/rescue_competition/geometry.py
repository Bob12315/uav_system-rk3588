from __future__ import annotations

import math
from dataclasses import dataclass

from fusion.models import SceneObject


@dataclass(frozen=True, slots=True)
class CameraGeometryConfig:
    fov_x_deg: float = 75.0
    fov_y_deg: float = 75.0
    image_x_sign: float = 1.0
    image_y_sign: float = 1.0


def image_offset_to_ground(
    *,
    nx: float,
    ny: float,
    altitude_m: float,
    config: CameraGeometryConfig,
) -> tuple[float, float]:
    """Return mission-frame forward/right offsets in meters."""
    altitude = max(0.0, float(altitude_m))
    half_x = altitude * math.tan(math.radians(float(config.fov_x_deg)) / 2.0)
    half_y = altitude * math.tan(math.radians(float(config.fov_y_deg)) / 2.0)
    offset_right = float(config.image_y_sign) * float(nx) * half_x
    offset_forward = float(config.image_x_sign) * float(ny) * half_y
    return offset_forward, offset_right


def detection_to_mission_xy(
    detection: SceneObject,
    *,
    drone_mission_x: float,
    drone_mission_y: float,
    altitude_m: float,
    config: CameraGeometryConfig,
) -> tuple[float, float]:
    offset_forward, offset_right = image_offset_to_ground(
        nx=float(detection.ex),
        ny=float(detection.ey),
        altitude_m=altitude_m,
        config=config,
    )
    return (
        float(drone_mission_x) + offset_forward,
        float(drone_mission_y) + offset_right,
    )
