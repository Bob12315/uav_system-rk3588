"""Shared safety primitives for GPS target sequences.

Drop and recon sequences deliberately share these helpers so every terminal
flight-control exit emits the same BODY_NED stop and clears stale continuous
commands.  Target-operation policy stays in the thin action wrappers.
"""

from __future__ import annotations

import math
from typing import Any


class GpsTargetSequenceCore:
    """Internal, unregistered core for GPS target-sequence safety behaviour."""

    @staticmethod
    def zero_velocity_command() -> dict[str, Any]:
        return {"action_type": "flight_command", "params": {
            "type": "flight_command", "valid": True, "active": True,
            "enable_body": True, "vx_cmd": 0.0, "vy_cmd": 0.0,
            "vz_cmd": 0.0, "yaw_rate_cmd": 0.0, "yaw_rate_rad_s": 0.0,
            "priority": 3}, "once": False}

    @staticmethod
    def clear_continuous_command(key_suffix: str = "") -> dict[str, Any]:
        return {"action_type": "clear_continuous_commands", "params": {
            "clear_pending_local_position": False, "send_stop_first": True},
            "once": True, "key": f"gps_target_clear_{key_suffix}"}

    @staticmethod
    def current_altitude_m(context: dict[str, Any]) -> float | None:
        drone = context.get("drone", {})
        sources = [drone] if isinstance(drone, dict) else []
        sources.append(context)
        for source in sources:
            # Keep da05c0f's exact source order.  In particular,
            # drone.altitude_m was never an accepted climb gate source.
            names = ("relative_altitude", "relative_altitude_m") if source is drone else (
                "relative_altitude", "relative_altitude_m", "altitude_m"
            )
            for name in names:
                try:
                    value = float(source[name])
                    if math.isfinite(value) and value >= 0.0:
                        return value
                except (KeyError, TypeError, ValueError):
                    pass
        return None
