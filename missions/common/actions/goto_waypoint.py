from __future__ import annotations

import math
from typing import Any

from app.coordinate_transform import field_to_local_ned
from app.field_reference import FieldReference

from .base import ActionModule
from .result import ActionResult


class GotoWaypointAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.skip_if_invalid_target = bool(data.get("skip_if_invalid_target", False))
        x_raw = data.get("x")
        y_raw = data.get("y")
        altitude_raw = data.get("altitude_m")
        # when skip enabled, check target validity before float conversion
        if self.skip_if_invalid_target:
            target = data.get("target")
            if isinstance(target, dict) and target.get("valid") is False:
                self._skipped = True
                self.started = True
                self.stopped = False
                return
            target_valid = data.get("target_valid")
            if target_valid is False:
                self._skipped = True
                self.started = True
                self.stopped = False
                return
            if self._is_invalid_coord(x_raw) or self._is_invalid_coord(y_raw) or self._is_invalid_coord(altitude_raw):
                self._skipped = True
                self.started = True
                self.stopped = False
                return

        x = self._required_float(data, "x")
        y = self._required_float(data, "y")
        altitude_m = self._required_float(data, "altitude_m")
        if altitude_m <= 0.0:
            raise ValueError("altitude_m must be positive")
        waypoint_mode = str(data.get("waypoint_mode", "absolute")).strip().lower()
        if waypoint_mode not in {"absolute", "field"}:
            raise ValueError("waypoint_mode must be absolute or field")

        yaw_mode = str(data.get("yaw_mode", "arm_heading")).strip().lower()
        if yaw_mode not in {"hold", "fixed", "arm_heading", "field_heading"}:
            raise ValueError("yaw_mode must be hold, fixed, arm_heading, or field_heading")
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
        self.waypoint_mode = waypoint_mode
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
        if getattr(self, "_skipped", False):
            return ActionResult(done=True, reason="skipped_missing_target",
                                detail={"status": "skipped_missing_target"})

        context_data = context or {}
        arm_heading_yaw_rad = self._arm_heading_yaw(context_data)
        field_heading_yaw_rad = self._field_heading_yaw(context_data)
        if self.yaw_mode == "arm_heading" and arm_heading_yaw_rad is None:
            detail = self._detail(None, None, None)
            detail["note"] = "yaw_mode arm_heading requires arm_heading_yaw_rad from vehicle context"
            return ActionResult(
                failed=True,
                reason="missing_arm_heading_yaw",
                detail=detail,
            )
        if self.yaw_mode == "field_heading" and field_heading_yaw_rad is None:
            detail = self._detail(None, None, None, context_data)
            detail["note"] = "yaw_mode field_heading requires field_heading_yaw_rad from a confirmed field heading"
            return ActionResult(
                failed=True,
                reason="missing_field_heading_yaw",
                detail=detail,
            )
        target = self._local_target(context_data)
        if target is None:
            detail = self._detail(None, None, None, context_data)
            detail["note"] = (
                "field waypoint rejected: confirm field heading/origin before field -> LOCAL_NED conversion"
            )
            return ActionResult(
                failed=True,
                reason="missing_field_origin",
                detail=detail,
            )

        current = self._current_position(context_data)
        if current is None:
            self.reached_updates = 0
            return ActionResult(
                actions=[self._action_dict(target, arm_heading_yaw_rad, field_heading_yaw_rad, context_data)],
                reason="waiting_for_position",
                detail=self._detail(None, None, None, context_data),
            )

        dx = target["x"] - current["x"]
        dy = target["y"] - current["y"]
        dz = target["z"] - current["z"]
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
            actions=[self._action_dict(target, arm_heading_yaw_rad, field_heading_yaw_rad, context_data)],
            reason="goto_active",
            detail=detail,
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.started = False
        self.stopped = False
        self.skip_if_invalid_target = False
        self._skipped = False
        self.target_x = 0.0
        self.target_y = 0.0
        self.target_z = 0.0
        self.altitude_m = 0.0
        self.waypoint_mode = "absolute"
        self.yaw_mode = "arm_heading"
        self.yaw_rad: float | None = None
        self.frame = 1
        self.tolerance_xy_m = 0.3
        self.tolerance_z_m = 0.3
        self.min_hold_updates = 1
        self.priority = 4
        self.key = ""
        self.reached_updates = 0

    def _action_dict(
        self,
        target: dict[str, float] | None = None,
        arm_heading_yaw_rad: float | None = None,
        field_heading_yaw_rad: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_data = target or {"x": self.target_x, "y": self.target_y, "z": self.target_z}
        params: dict[str, Any] = {
            "x": target_data["x"],
            "y": target_data["y"],
            "z": target_data["z"],
            "frame": self.frame,
        }
        if self.yaw_mode == "fixed":
            params["yaw"] = self.yaw_rad
        elif self.yaw_mode == "arm_heading":
            params["yaw"] = arm_heading_yaw_rad
        elif self.yaw_mode == "field_heading":
            params["yaw"] = field_heading_yaw_rad
        action = {
            "action_type": "local_position",
            "params": params,
            "input_frame": "field" if self.waypoint_mode == "field" else "local_ned",
            "input_target": {"x": self.target_x, "y": self.target_y, "z": self.target_z},
            "local_target": dict(target_data),
            "key": self.key,
            "once": False,
            "priority": self.priority,
        }
        context_data = context or {}
        action["field_origin_local_x"] = self._float_context(context_data, "field_origin_local_x")
        action["field_origin_local_y"] = self._float_context(context_data, "field_origin_local_y")
        action["field_heading_yaw_rad"] = field_heading_yaw_rad
        return action

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
            "waypoint_mode": self.waypoint_mode,
            "input_frame": "field" if self.waypoint_mode == "field" else "local_ned",
            "input_target": {"x": self.target_x, "y": self.target_y, "z": self.target_z},
            "field_origin_local_x": self._float_context(context_data, "field_origin_local_x"),
            "field_origin_local_y": self._float_context(context_data, "field_origin_local_y"),
        }
        local_target = self._local_target(context_data)
        if local_target is not None:
            detail["local_target"] = local_target
            detail["note"] = (
                "field -> LOCAL_NED converted" if self.waypoint_mode == "field"
                else "LOCAL_NED input used directly"
            )
        arm_heading_yaw_rad = self._arm_heading_yaw(context_data)
        if arm_heading_yaw_rad is not None:
            detail["arm_heading_yaw_rad"] = arm_heading_yaw_rad
        if context_data.get("arm_heading_fallback"):
            detail["arm_heading_fallback"] = True
        field_heading_yaw_rad = self._field_heading_yaw(context_data)
        if field_heading_yaw_rad is not None:
            detail["field_heading_yaw_rad"] = field_heading_yaw_rad
        if "field_heading_confirmed" in context_data:
            detail["field_heading_confirmed"] = bool(context_data.get("field_heading_confirmed"))
        if "field_heading_source" in context_data:
            detail["field_heading_source"] = context_data.get("field_heading_source")
        return detail

    def _arm_heading_yaw(self, context: dict[str, Any]) -> float | None:
        value = context.get("arm_heading_yaw_rad")
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _field_heading_yaw(self, context: dict[str, Any]) -> float | None:
        value = context.get("field_heading_yaw_rad")
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _local_target(self, context: dict[str, Any]) -> dict[str, float] | None:
        if self.waypoint_mode == "absolute":
            return {"x": self.target_x, "y": self.target_y, "z": self.target_z}

        if not bool(context.get("field_heading_confirmed", False)) or not bool(
            context.get("field_origin_confirmed", False)
        ):
            return None
        field_heading_yaw_rad = self._field_heading_yaw(context)
        origin_x = self._float_context(context, "field_origin_local_x")
        origin_y = self._float_context(context, "field_origin_local_y")
        if field_heading_yaw_rad is None or origin_x is None or origin_y is None:
            return None

        ref = FieldReference()
        ref.is_confirmed = True  # guarded by the checks above
        ref.origin_local_n_m = origin_x
        ref.origin_local_e_m = origin_y
        ref.field_heading_yaw_rad = field_heading_yaw_rad

        result = field_to_local_ned(
            self.target_x, self.target_y, self.altitude_m, reference=ref,
        )
        return {"x": result.north_m, "y": result.east_m, "z": result.z_down_m}

    @staticmethod
    def _float_context(context: dict[str, Any], name: str) -> float | None:
        value = context.get(name)
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

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

    @staticmethod
    def _is_invalid_coord(value: Any) -> bool:
        """Return True if value is None or not a finite float."""
        if value is None:
            return True
        try:
            v = float(value)
        except (TypeError, ValueError):
            return True
        return not math.isfinite(v)

    def _required_float(self, params: dict[str, Any], name: str) -> float:
        if name not in params:
            raise ValueError(f"{name} is required")
        try:
            return float(params[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
