from __future__ import annotations

import logging
import math
import time
from typing import Any

from .coordinate_transform import field_to_local_ned, local_ned_to_field
from .field_reference import FieldReference


class RuntimeContextBuilder:
    """Builds the action-lab context dict from a web-status snapshot.

    Extracted from SystemRunner so that arm-heading tracking and
    perception-to-context mapping live in one focused place.
    """

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._last_vehicle_armed: bool | None = None
        self.pre_arm_yaw_rad: float | None = None
        self.pre_arm_yaw_time: float | None = None
        self.arm_heading_yaw_rad: float | None = None
        self.arm_heading_time: float | None = None
        self.arm_heading_fallback = False
        self.field_heading_yaw_rad: float | None = None
        self.field_heading_time: float | None = None
        self.field_heading_confirmed: bool = False
        self.field_heading_source: str = ""
        self.field_origin_local_x: float | None = None
        self.field_origin_local_y: float | None = None
        self.field_origin_local_z: float | None = None
        self.field_origin_time: float | None = None
        self.field_origin_confirmed: bool = False

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def build_action_context(self, snapshot: dict[str, object]) -> dict[str, object]:
        context: dict[str, object] = {
            "timestamp": time.time(),
            "drone": snapshot.get("drone", {}),
            "scene": snapshot.get("scene", {}),
            "perception": snapshot.get("perception", {}),
            "gimbal": snapshot.get("gimbal", {}),
            "link": snapshot.get("link", {}),
            "health": snapshot.get("health", {}),
            "command": snapshot.get("command", {}),
            "mission_detail": snapshot.get("mission_detail", {}),
        }
        if self.field_heading_yaw_rad is not None:
            context["field_heading_yaw_rad"] = self.field_heading_yaw_rad
            context["field_heading_time"] = self.field_heading_time
        context["field_heading_confirmed"] = bool(self.field_heading_confirmed)
        context["field_heading_source"] = self.field_heading_source
        if self.field_origin_confirmed:
            context["field_origin_local_x"] = self.field_origin_local_x
            context["field_origin_local_y"] = self.field_origin_local_y
            context["field_origin_local_z"] = self.field_origin_local_z
            context["field_origin_time"] = self.field_origin_time
        context["field_origin_confirmed"] = bool(self.field_origin_confirmed)
        context["field_transform"] = self.field_transform()

        drone = context["drone"]
        if isinstance(drone, dict):
            self._update_arm_heading(drone)

            if self.arm_heading_yaw_rad is not None:
                context["arm_heading_yaw_rad"] = self.arm_heading_yaw_rad
                context["arm_heading_time"] = self.arm_heading_time
                if self.arm_heading_fallback:
                    context["arm_heading_fallback"] = True
            if self.pre_arm_yaw_rad is not None:
                context["pre_arm_yaw_rad"] = self.pre_arm_yaw_rad
                context["pre_arm_yaw_time"] = self.pre_arm_yaw_time
            if self.field_heading_yaw_rad is not None:
                context["field_heading_yaw_rad"] = self.field_heading_yaw_rad
                context["field_heading_time"] = self.field_heading_time
            context["field_heading_confirmed"] = bool(self.field_heading_confirmed)
            context["field_heading_source"] = self.field_heading_source
            if self.field_origin_confirmed:
                context["field_origin_local_x"] = self.field_origin_local_x
                context["field_origin_local_y"] = self.field_origin_local_y
                context["field_origin_local_z"] = self.field_origin_local_z
                context["field_origin_time"] = self.field_origin_time
            context["field_origin_confirmed"] = bool(self.field_origin_confirmed)

            if all(name in drone for name in ("local_x", "local_y", "local_z")):
                context["local_position"] = {
                    "x": drone.get("local_x"),
                    "y": drone.get("local_y"),
                    "z": drone.get("local_z"),
                }
            field_position = self.field_position_from_drone(drone)
            if field_position is not None:
                context["field_position"] = field_position

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

    def field_transform_ready(self) -> bool:
        return bool(
            self.field_heading_confirmed
            and self.field_origin_confirmed
            and self._float_or_none(self.field_heading_yaw_rad) is not None
            and self._float_or_none(self.field_origin_local_x) is not None
            and self._float_or_none(self.field_origin_local_y) is not None
        )

    def field_transform(self) -> dict[str, object]:
        return {
            "heading_yaw_rad": self.field_heading_yaw_rad,
            "origin_local_x": self.field_origin_local_x,
            "origin_local_y": self.field_origin_local_y,
            "origin_local_z": self.field_origin_local_z,
            "confirmed": self.field_transform_ready(),
            "convention": "field_y_forward_field_x_right",
        }

    def local_to_field_xy(self, local_x: object, local_y: object) -> tuple[float, float] | None:
        ref = self._build_field_reference_from_runtime_state()
        if ref is None:
            return None
        lx = self._float_or_none(local_x)
        ly = self._float_or_none(local_y)
        if lx is None or ly is None:
            return None
        result = local_ned_to_field(lx, ly, z_down_m=0.0, reference=ref)
        return (result.field_x_m, result.field_y_m)

    def field_to_local_xy(self, field_x: object, field_y: object) -> tuple[float, float] | None:
        ref = self._build_field_reference_from_runtime_state()
        if ref is None:
            return None
        fx = self._float_or_none(field_x)
        fy = self._float_or_none(field_y)
        if fx is None or fy is None:
            return None
        result = field_to_local_ned(fx, fy, altitude_m=0.0, reference=ref)
        return (result.north_m, result.east_m)

    def field_position_from_drone(self, drone: object) -> dict[str, object] | None:
        if not isinstance(drone, dict) or not bool(drone.get("local_position_valid", False)):
            return None
        converted = self.local_to_field_xy(drone.get("local_x"), drone.get("local_y"))
        if converted is None:
            return None
        field_x, field_y = converted
        return {
            "x": field_x,
            "y": field_y,
            "z": self._float_or_none(drone.get("local_z")),
            "local_x": self._float_or_none(drone.get("local_x")),
            "local_y": self._float_or_none(drone.get("local_y")),
            "local_z": self._float_or_none(drone.get("local_z")),
            "source": "field_heading",
            "confirmed": True,
        }

    def confirm_field_heading(
        self,
        yaw_rad: float | None = None,
        *,
        drone: dict[str, object] | None = None,
        source: str = "manual",
    ) -> bool:
        if yaw_rad is None and isinstance(drone, dict):
            yaw_rad = self._float_or_none(drone.get("yaw"))
        yaw = self._float_or_none(yaw_rad)
        if yaw is None or not math.isfinite(yaw):
            return False
        if not isinstance(drone, dict) or not bool(drone.get("local_position_valid", False)):
            return False
        origin_x = self._float_or_none(drone.get("local_x"))
        origin_y = self._float_or_none(drone.get("local_y"))
        origin_z = self._float_or_none(drone.get("local_z"))
        if origin_x is None or origin_y is None or origin_z is None:
            return False
        normalized = self._normalize_yaw(yaw)
        now = time.time()
        self.field_heading_yaw_rad = normalized
        self.field_heading_time = now
        self.field_heading_confirmed = True
        self.field_heading_source = source
        self.field_origin_local_x = origin_x
        self.field_origin_local_y = origin_y
        self.field_origin_local_z = origin_z
        self.field_origin_time = now
        self.field_origin_confirmed = True
        self.logger.info(
            "field heading confirmed yaw_rad=%s origin=(%s,%s,%s) source=%s",
            normalized,
            origin_x,
            origin_y,
            origin_z,
            source,
        )
        return True

    def confirm_field_reference(
        self,
        field_heading_yaw_rad: float,
        origin_local_x: float,
        origin_local_y: float,
        origin_local_z: float | None = None,
        source: str = "field_reference",
        timestamp: float | None = None,
    ) -> bool:
        """Write FieldReference sync result into legacy RuntimeContextBuilder fields.

        This is the bridge from the new FieldReferenceService back to the
        existing Action context / GotoWaypoint / CoordinateTransform chain.
        ``origin_local_z`` is stored only for status display; it is not used
        by the XY FIELD→LOCAL_NED transform.
        """
        yaw = self._float_or_none(field_heading_yaw_rad)
        ox = self._float_or_none(origin_local_x)
        oy = self._float_or_none(origin_local_y)
        if yaw is None or ox is None or oy is None:
            return False
        now = timestamp if timestamp is not None else time.time()
        self.field_heading_yaw_rad = self._normalize_yaw(yaw)
        self.field_heading_time = now
        self.field_heading_confirmed = True
        self.field_heading_source = source
        self.field_origin_local_x = ox
        self.field_origin_local_y = oy
        self.field_origin_local_z = self._float_or_none(origin_local_z)
        self.field_origin_time = now
        self.field_origin_confirmed = True
        self.logger.info(
            "field reference synced yaw_rad=%s origin=(%s,%s,%s) source=%s",
            self.field_heading_yaw_rad,
            ox, oy, self.field_origin_local_z,
            source,
        )
        return True

    def clear_field_heading(self) -> None:
        """Clear all legacy field-heading fields (used by FieldReference reset)."""
        self.field_heading_yaw_rad = None
        self.field_heading_time = None
        self.field_heading_confirmed = False
        self.field_heading_source = ""
        self.field_origin_local_x = None
        self.field_origin_local_y = None
        self.field_origin_local_z = None
        self.field_origin_time = None
        self.field_origin_confirmed = False
        self.logger.info("field heading cleared via FieldReference reset")

    # ------------------------------------------------------------------
    # arm-heading tracking
    # ------------------------------------------------------------------

    def _update_arm_heading(self, drone: dict[str, object]) -> None:
        vehicle_armed = bool(drone.get("armed", False))
        attitude_valid = bool(drone.get("attitude_valid", False))
        yaw = self._float_or_none(drone.get("yaw"))
        if not vehicle_armed and attitude_valid and yaw is not None:
            self.pre_arm_yaw_rad = self._normalize_yaw(yaw)
            self.pre_arm_yaw_time = time.time()
        if (
            vehicle_armed
            and self._last_vehicle_armed is False
            and attitude_valid
            and yaw is not None
        ):
            self.arm_heading_yaw_rad = (
                self.pre_arm_yaw_rad if self.pre_arm_yaw_rad is not None else self._normalize_yaw(yaw)
            )
            self.arm_heading_time = time.time()
            self.arm_heading_fallback = False
            self.logger.info("arm heading yaw recorded yaw_rad=%s", self.arm_heading_yaw_rad)
        elif (
            vehicle_armed
            and self.arm_heading_yaw_rad is None
            and attitude_valid
            and yaw is not None
        ):
            self.arm_heading_yaw_rad = self._normalize_yaw(yaw)
            self.arm_heading_time = time.time()
            self.arm_heading_fallback = True
            self.logger.info("arm heading yaw fallback recorded yaw_rad=%s", self.arm_heading_yaw_rad)
        self._last_vehicle_armed = vehicle_armed

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_yaw(yaw: float) -> float:
        return math.atan2(math.sin(yaw), math.cos(yaw))

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    # ------------------------------------------------------------------
    # adapter: build FieldReference from legacy runtime state
    # ------------------------------------------------------------------

    def _build_field_reference_from_runtime_state(self) -> FieldReference | None:
        """Build a :class:`FieldReference` from the current runtime state
        for use by ``field_to_local_ned`` / ``local_ned_to_field``.

        Returns ``None`` when the runtime state is not ready (same guard
        as ``field_transform_ready()``).
        """
        if not self.field_transform_ready():
            return None
        ref = FieldReference()
        ref.is_confirmed = True  # guarded by field_transform_ready() above
        ref.origin_local_n_m = float(self.field_origin_local_x)
        ref.origin_local_e_m = float(self.field_origin_local_y)
        ref.field_heading_yaw_rad = float(self.field_heading_yaw_rad)
        # heading_source / origin_source are intentionally NOT mapped here:
        # the old runtime context uses free-form strings (e.g. "manual",
        # "takeoff_auto") that don't correspond 1:1 to the new enums.
        # These fields are not needed for the pure math transforms.
        return ref

    @classmethod
    def json_safe(cls, value):
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(key): cls.json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls.json_safe(item) for item in value]
        return value
