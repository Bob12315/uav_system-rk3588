from __future__ import annotations

import logging
import math
import time
from typing import Any


class RuntimeContextBuilder:
    """Builds the action-lab context dict from a web-status snapshot.

    Extracted from SystemRunner so that arm-heading tracking and
    perception-to-context mapping live in one focused place.
    """

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._last_vehicle_armed: bool | None = None
        self.arm_heading_yaw_rad: float | None = None
        self.arm_heading_time: float | None = None
        self.arm_heading_fallback = False

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def build_action_context(self, snapshot: dict[str, object]) -> dict[str, object]:
        context: dict[str, object] = {
            "timestamp": time.time(),
            "drone": snapshot.get("drone", {}),
            "scene": snapshot.get("scene", {}),
            "perception": snapshot.get("perception", {}),
        }

        drone = context["drone"]
        if isinstance(drone, dict):
            self._update_arm_heading(drone)

            if self.arm_heading_yaw_rad is not None:
                context["arm_heading_yaw_rad"] = self.arm_heading_yaw_rad
                context["arm_heading_time"] = self.arm_heading_time
                if self.arm_heading_fallback:
                    context["arm_heading_fallback"] = True

            if all(name in drone for name in ("local_x", "local_y", "local_z")):
                context["local_position"] = {
                    "x": drone.get("local_x"),
                    "y": drone.get("local_y"),
                    "z": drone.get("local_z"),
                }

            perception = context.get("perception")
            for source, target in (
                ("target_valid", "target_valid"),
                ("tracking_state", "tracking_state"),
                ("track_id", "track_id"),
                ("ex", "ex_cam"),
                ("ey", "ey_cam"),
            ):
                if isinstance(perception, dict) and source in perception:
                    context[target] = perception[source]

            if "target_locked" not in context:
                if isinstance(perception, dict):
                    context["target_locked"] = (
                        str(perception.get("tracking_state", "")).lower() == "locked"
                    )

            if "control_allowed" in drone:
                context["control_allowed"] = drone.get("control_allowed")

            if "relative_altitude" in drone:
                context["relative_altitude"] = drone.get("relative_altitude")

        return self.json_safe(context)

    # ------------------------------------------------------------------
    # arm-heading tracking
    # ------------------------------------------------------------------

    def _update_arm_heading(self, drone: dict[str, object]) -> None:
        vehicle_armed = bool(drone.get("armed", False))
        yaw = self._float_or_none(drone.get("yaw"))
        if (
            vehicle_armed
            and self._last_vehicle_armed is False
            and yaw is not None
        ):
            self.arm_heading_yaw_rad = yaw
            self.arm_heading_time = time.time()
            self.arm_heading_fallback = False
            self.logger.info("arm heading yaw recorded yaw_rad=%s", yaw)
        elif (
            vehicle_armed
            and self.arm_heading_yaw_rad is None
            and yaw is not None
        ):
            self.arm_heading_yaw_rad = yaw
            self.arm_heading_time = time.time()
            self.arm_heading_fallback = True
            self.logger.info("arm heading yaw fallback recorded yaw_rad=%s", yaw)
        self._last_vehicle_armed = vehicle_armed

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def json_safe(cls, value):
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(key): cls.json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls.json_safe(item) for item in value]
        return value
