"""Pure waypoint-frame math used by Action adapters."""
from __future__ import annotations

import math


def field_xy_to_enu(field_x_m: float, field_y_m: float, heading_yaw_rad: float) -> tuple[float, float]:
    """Return (east, north) offsets for FIELD (+right, +forward)."""
    values = (field_x_m, field_y_m, heading_yaw_rad)
    if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
        raise ValueError("FIELD waypoint values must be finite numbers")
    sin_h = math.sin(float(heading_yaw_rad))
    cos_h = math.cos(float(heading_yaw_rad))
    north = float(field_y_m) * cos_h - float(field_x_m) * sin_h
    east = float(field_y_m) * sin_h + float(field_x_m) * cos_h
    return east, north
