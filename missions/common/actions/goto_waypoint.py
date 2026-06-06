from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult


class GotoWaypointAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        x = self._required_float(data, "x")
        y = self._required_float(data, "y")
        altitude_m = self._required_float(data, "altitude_m")
        if altitude_m <= 0.0:
            raise ValueError("altitude_m must be positive")

        yaw_mode = str(data.get("yaw_mode", "hold")).strip().lower()
        if yaw_mode not in {"hold", "fixed", "arm_heading"}:
            raise ValueError("yaw_mode must be hold, fixed, or arm_heading")
        yaw_rad = None
        if yaw_mode == "fixed":
            yaw_rad = self._required_float(data, "yaw_rad")

        tolerance_xy_m = float(data.get("tolerance_xy_m", 0.3))
        tolerance_z_m = float(data.get("tolerance_z_m", 0.3))
        if tolerance_xy_m <= 0.0:
            raise ValueError("tolerance_xy_m must be positive")
        if tolerance_z_m <= 0.0:
            raise ValueError("tolerance_z_m must be positive")

        min_hold_updates = int(data.get("min_hold_updates", 1))
        if min_hold_updates < 1:
            min_hold_updates = 1

        self.target_x = x
        self.target_y = y
        self.altitude_m = altitude_m
        self.target_z = -altitude_m
        self.yaw_mode = yaw_mode
        self.yaw_rad = yaw_rad
        self.frame = int(data.get("frame", 1))
        self.tolerance_xy_m = tolerance_xy_m
        self.tolerance_z_m = tolerance_z_m
        self.min_hold_updates = min_hold_updates
        self.priority = int(data.get("priority", 4))
        self.key = str(data.get("key") or f"goto_waypoint_{x:.2f}_{y:.2f}_{altitude_m:.2f}")
        self.started = True
        self.stopped = False
        self.reached_updates = 0

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")

        context_data = context or {}
        arm_heading_yaw_rad = self._arm_heading_yaw(context_data)
        if self.yaw_mode == "arm_heading" and arm_heading_yaw_rad is None:
            detail = self._detail(None, None, None)
            detail["note"] = "yaw_mode arm_heading requires arm_heading_yaw_rad from vehicle context"
            return ActionResult(
                failed=True,
                reason="missing_arm_heading_yaw",
                detail=detail,
            )

        current = self._current_position(context_data)
        if current is None:
            self.reached_updates = 0
            return ActionResult(
                actions=[self._action_dict(arm_heading_yaw_rad)],
                reason="waiting_for_position",
                detail=self._detail(None, None, None, context_data),
            )

        dx = self.target_x - current["x"]
        dy = self.target_y - current["y"]
        dz = self.target_z - current["z"]
        distance_xy_m = math.sqrt(dx * dx + dy * dy)
        z_error_m = abs(dz)
        reached = (
            distance_xy_m <= self.tolerance_xy_m
            and z_error_m <= self.tolerance_z_m
        )
        if reached:
            self.reached_updates += 1
        else:
            self.reached_updates = 0

        detail = self._detail(current, distance_xy_m, z_error_m, context_data)
        if self.reached_updates >= self.min_hold_updates:
            return ActionResult(done=True, reason="waypoint_reached", detail=detail)
        return ActionResult(
            actions=[self._action_dict(arm_heading_yaw_rad)],
            reason="goto_active",
            detail=detail,
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.started = False
        self.stopped = False
        self.target_x = 0.0
        self.target_y = 0.0
        self.target_z = 0.0
        self.altitude_m = 0.0
        self.yaw_mode = "hold"
        self.yaw_rad: float | None = None
        self.frame = 1
        self.tolerance_xy_m = 0.3
        self.tolerance_z_m = 0.3
        self.min_hold_updates = 1
        self.priority = 4
        self.key = ""
        self.reached_updates = 0

    def _action_dict(self, arm_heading_yaw_rad: float | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "x": self.target_x,
            "y": self.target_y,
            "z": self.target_z,
            "frame": self.frame,
        }
        if self.yaw_mode == "fixed":
            params["yaw"] = self.yaw_rad
        elif self.yaw_mode == "arm_heading":
            params["yaw"] = arm_heading_yaw_rad
        return {
            "action_type": "local_position",
            "params": params,
            "key": self.key,
            "once": False,
            "priority": self.priority,
        }

    def _detail(
        self,
        current: dict[str, float] | None,
        distance_xy_m: float | None,
        z_error_m: float | None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context_data = context or {}
        detail = {
            "target": {
                "x": self.target_x,
                "y": self.target_y,
                "z": self.target_z,
                "altitude_m": self.altitude_m,
            },
            "current": current,
            "distance_xy_m": distance_xy_m,
            "z_error_m": z_error_m,
            "reached_updates": self.reached_updates,
            "yaw_mode": self.yaw_mode,
        }
        arm_heading_yaw_rad = self._arm_heading_yaw(context_data)
        if arm_heading_yaw_rad is not None:
            detail["arm_heading_yaw_rad"] = arm_heading_yaw_rad
        if context_data.get("arm_heading_fallback"):
            detail["arm_heading_fallback"] = True
        return detail

    def _arm_heading_yaw(self, context: dict[str, Any]) -> float | None:
        value = context.get("arm_heading_yaw_rad")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _current_position(self, context: dict[str, Any]) -> dict[str, float] | None:
        value = context.get("local_position")
        if value is None:
            drone = context.get("drone")
            if isinstance(drone, dict):
                value = drone.get("local_position")
        if not isinstance(value, dict):
            return None
        try:
            return {
                "x": float(value["x"]),
                "y": float(value["y"]),
                "z": float(value["z"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def _required_float(self, params: dict[str, Any], name: str) -> float:
        if name not in params:
            raise ValueError(f"{name} is required")
        try:
            return float(params[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
