from __future__ import annotations

import math
from typing import Any

from app.coordinate_transform import field_to_gps, field_to_local_ned
from app.field_reference import FieldReference
from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT, LOCAL_NED

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
        # GLOBAL lat/lon input support (new path)
        lat_raw = data.get("lat")
        lon_raw = data.get("lon")
        target_frame = str(data.get("target_frame", "local")).strip().lower()
        if target_frame not in {"local", "global"}:
            raise ValueError("target_frame must be local or global")
        use_global_latlon = target_frame == "global" and lat_raw is not None and lon_raw is not None
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
            raw_x_check = lat_raw if use_global_latlon else x_raw
            raw_y_check = lon_raw if use_global_latlon else y_raw
            if self._is_invalid_coord(raw_x_check) or self._is_invalid_coord(raw_y_check) or self._is_invalid_coord(altitude_raw):
                self._skipped = True
                self.started = True
                self.stopped = False
                return

        if use_global_latlon:
            x = self._required_float({"v": lat_raw}, "v")
            y = self._required_float({"v": lon_raw}, "v")
        else:
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
        require_velocity_valid = bool(data.get("require_velocity_valid", False))
        max_horizontal_speed_mps = float(data.get("max_horizontal_speed_mps", 0.15))
        max_vertical_speed_mps = float(data.get("max_vertical_speed_mps", 0.10))
        for name, value in (
            ("max_horizontal_speed_mps", max_horizontal_speed_mps),
            ("max_vertical_speed_mps", max_vertical_speed_mps),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")

        self.target_x = x
        self.target_y = y
        self.altitude_m = altitude_m
        self.target_z = -altitude_m
        self.waypoint_mode = waypoint_mode
        self.target_frame = target_frame
        self.yaw_mode = yaw_mode
        self.yaw_rad = yaw_rad
        default_frame = GLOBAL_RELATIVE_ALT_INT if target_frame == "global" else LOCAL_NED
        self.frame = int(data.get("frame", default_frame))
        self.tolerance_xy_m = tolerance_xy_m
        self.tolerance_z_m = tolerance_z_m
        self.min_hold_updates = min_hold_updates
        self.require_velocity_valid = require_velocity_valid
        self.max_horizontal_speed_mps = max_horizontal_speed_mps
        self.max_vertical_speed_mps = max_vertical_speed_mps
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
        target = self._target(context_data)
        if target is None:
            detail = self._detail(None, None, None, context_data)
            detail["note"] = (
                "field waypoint rejected: confirm field heading/origin before coordinate conversion"
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

        distance_xy_m, z_error_m = self._target_error(target, current)
        velocity_gate_passed = self._velocity_status(context_data)["velocity_gate_passed"]
        reached = (
            distance_xy_m <= self.tolerance_xy_m
            and z_error_m <= self.tolerance_z_m
            and velocity_gate_passed
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
        self.target_frame = "local"
        self.yaw_mode = "arm_heading"
        self.yaw_rad: float | None = None
        self.frame = LOCAL_NED
        self.tolerance_xy_m = 0.3
        self.tolerance_z_m = 0.3
        self.min_hold_updates = 1
        self.require_velocity_valid = False
        self.max_horizontal_speed_mps = 0.15
        self.max_vertical_speed_mps = 0.10
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
        target_data = target or self._raw_target()
        context_data = context or {}
        if self.target_frame == "global":
            params: dict[str, Any] = {
                "lat": target_data["lat"],
                "lon": target_data["lon"],
                "alt": target_data["alt"],
                "frame": self.frame,
            }
            if self.yaw_mode == "fixed":
                params["yaw"] = self.yaw_rad
            elif self.yaw_mode == "arm_heading":
                params["yaw"] = arm_heading_yaw_rad
            elif self.yaw_mode == "field_heading":
                params["yaw"] = field_heading_yaw_rad
            elif self.yaw_mode == "hold":
                current_yaw = self._current_yaw_from_context(context_data)
                if current_yaw is not None:
                    params["yaw"] = current_yaw
            action = {
                "action_type": "global_goto",
                "params": params,
                "input_frame": "field" if self.waypoint_mode == "field" else "global",
                "input_target": {"x": self.target_x, "y": self.target_y, "z": self.target_z},
                "global_target": dict(target_data),
                "key": self.key,
                "once": False,
                "priority": self.priority,
            }
            action["field_origin_lat"] = self._float_context(context_data, "field_origin_lat")
            action["field_origin_lon"] = self._float_context(context_data, "field_origin_lon")
            action["field_heading_yaw_rad"] = field_heading_yaw_rad
            return action

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
            "target_frame": self.target_frame,
            "input_frame": (
                "field" if self.waypoint_mode == "field"
                else ("global" if self.target_frame == "global" else "local_ned")
            ),
            "input_target": {"x": self.target_x, "y": self.target_y, "z": self.target_z},
            "field_origin_local_x": self._float_context(context_data, "field_origin_local_x"),
            "field_origin_local_y": self._float_context(context_data, "field_origin_local_y"),
            "field_origin_lat": self._float_context(context_data, "field_origin_lat"),
            "field_origin_lon": self._float_context(context_data, "field_origin_lon"),
            **self._velocity_status(context_data),
        }
        target = self._target(context_data)
        if target is not None:
            if self.target_frame == "global":
                detail["global_target"] = target
            else:
                detail["local_target"] = target
            detail["note"] = (
                "field -> GPS converted" if self.waypoint_mode == "field" and self.target_frame == "global"
                else "field -> LOCAL_NED converted" if self.waypoint_mode == "field"
                else "GPS input used directly" if self.target_frame == "global"
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

    def _velocity_status(self, context: dict[str, Any]) -> dict[str, Any]:
        required = self.target_frame == "global" and self.require_velocity_valid
        drone = context.get("drone")
        velocity_valid = False
        horizontal_speed_mps: float | None = None
        vertical_speed_mps: float | None = None
        if isinstance(drone, dict) and drone.get("velocity_valid") is True:
            try:
                vx = float(drone["vx"])
                vy = float(drone["vy"])
                vz = float(drone["vz"])
            except (KeyError, TypeError, ValueError):
                pass
            else:
                if all(math.isfinite(value) for value in (vx, vy, vz)):
                    velocity_valid = True
                    horizontal_speed_mps = math.hypot(vx, vy)
                    vertical_speed_mps = abs(vz)
        gate_passed = not required or (
            velocity_valid
            and horizontal_speed_mps is not None
            and vertical_speed_mps is not None
            and horizontal_speed_mps <= self.max_horizontal_speed_mps
            and vertical_speed_mps <= self.max_vertical_speed_mps
        )
        return {
            "velocity_required": required,
            "velocity_valid": velocity_valid,
            "horizontal_speed_mps": horizontal_speed_mps,
            "vertical_speed_mps": vertical_speed_mps,
            "velocity_gate_passed": gate_passed,
        }

    def _raw_target(self) -> dict[str, float]:
        if self.target_frame == "global":
            return {"lat": self.target_x, "lon": self.target_y, "alt": self.altitude_m}
        return {"x": self.target_x, "y": self.target_y, "z": self.target_z}

    def _arm_heading_yaw(self, context: dict[str, Any]) -> float | None:
        value = context.get("arm_heading_yaw_rad")
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _target(self, context: dict[str, Any]) -> dict[str, float] | None:
        if self.target_frame == "global":
            return self._global_target(context)
        return self._local_target(context)

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

    def _global_target(self, context: dict[str, Any]) -> dict[str, float] | None:
        if self.waypoint_mode == "absolute":
            return {"lat": self.target_x, "lon": self.target_y, "alt": self.altitude_m}

        gps_origin_confirmed = context.get("field_origin_gps_confirmed")
        if gps_origin_confirmed is None:
            # Compatibility for contexts produced before the GPS-specific flag.
            gps_origin_confirmed = context.get("field_origin_confirmed", False)
        if not bool(context.get("field_heading_confirmed", False)) or not bool(gps_origin_confirmed):
            return None
        field_heading_yaw_rad = self._field_heading_yaw(context)
        origin_lat = self._float_context(context, "field_origin_lat")
        origin_lon = self._float_context(context, "field_origin_lon")
        if field_heading_yaw_rad is None or origin_lat is None or origin_lon is None:
            return None

        ref = FieldReference()
        ref.is_confirmed = True
        ref.origin_lat = origin_lat
        ref.origin_lon = origin_lon
        ref.field_heading_yaw_rad = field_heading_yaw_rad

        result = field_to_gps(
            self.target_x, self.target_y, self.altitude_m, reference=ref,
        )
        return {"lat": result.lat, "lon": result.lon, "alt": result.alt_m}

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

    @staticmethod
    def _current_yaw_from_context(context: dict[str, Any]) -> float | None:
        """Extract the best available current yaw from context for yaw_mode=hold."""
        for name in ("arm_heading_yaw_rad", "field_heading_yaw_rad", "yaw"):
            value = context.get(name)
            if value is not None:
                try:
                    result = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(result):
                    return result
        drone = context.get("drone")
        if isinstance(drone, dict):
            try:
                yaw = float(drone.get("yaw", float("nan")))
                if math.isfinite(yaw):
                    return yaw
            except (TypeError, ValueError):
                pass
        return None

    def _current_position(self, context: dict[str, Any]) -> dict[str, float] | None:
        if self.target_frame == "global":
            return self._current_global_position(context)
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

    def _current_global_position(self, context: dict[str, Any]) -> dict[str, float] | None:
        drone = context.get("drone")
        if not isinstance(drone, dict) or not bool(drone.get("global_position_valid", False)):
            return None
        try:
            lat = float(drone["lat"])
            lon = float(drone["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        alt = None
        for name in ("relative_altitude", "relative_altitude_m", "altitude_m"):
            if name not in drone:
                continue
            try:
                alt = float(drone[name])
                break
            except (TypeError, ValueError):
                continue
        if alt is None or not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(alt)):
            return None
        return {"lat": lat, "lon": lon, "alt": alt}

    def _target_error(
        self,
        target: dict[str, float],
        current: dict[str, float],
    ) -> tuple[float, float]:
        if self.target_frame == "global":
            distance_xy_m = self._gps_distance_m(
                current["lat"], current["lon"], target["lat"], target["lon"]
            )
            return distance_xy_m, abs(target["alt"] - current["alt"])

        dx = target["x"] - current["x"]
        dy = target["y"] - current["y"]
        dz = target["z"] - current["z"]
        return math.sqrt(dx * dx + dy * dy), abs(dz)

    @staticmethod
    def _gps_distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
        lat_a_rad = math.radians(lat_a)
        d_north = (math.radians(lat_b) - lat_a_rad) * 6371000.0
        d_east = (
            (math.radians(lon_b) - math.radians(lon_a))
            * 6371000.0
            * math.cos(lat_a_rad)
        )
        return math.sqrt(d_north * d_north + d_east * d_east)

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
