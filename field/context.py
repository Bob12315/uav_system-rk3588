from __future__ import annotations

import logging
import math
import time
from field.coordinates import gps_to_field_from_origin
from field.models import FieldReference
from field.calibration import (
    validate_runtime_field_binding_candidate,
)


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class RuntimeContextBuilder:
    """Builds the action-lab context dict from a web-status snapshot.

    Extracted from SystemRunner so that arm-heading tracking and
    perception-to-context mapping live in one focused place.
    """

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._field_reference = FieldReference()
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._last_vehicle_armed: bool | None = None
        self.pre_arm_yaw_rad: float | None = None
        self.pre_arm_yaw_time: float | None = None
        self.arm_heading_yaw_rad: float | None = None
        self.arm_heading_time: float | None = None
        self.arm_heading_fallback = False
        self.field_reference_mode: str = ""
        self.field_baseline_m: float | None = None
        self.field_gps_sample_count: int | None = None
        self.field_gps_rejected_sample_count: int | None = None
        self.field_gps_duplicate_sample_count: int | None = None
        self.field_gps_sample_duration_s: float | None = None
        self.field_gps_horizontal_spread_m: float | None = None
        self.field_gps_fix_type: int | None = None
        self.field_gps_satellites: int | None = None
        self.field_gps_eph: float | None = None
        self.field_gps_epv: float | None = None
        self.field_runtime_profile_id: str = ""

    def bind_field_reference(self, reference: FieldReference) -> None:
        """Use the FieldService-owned object as the only reference state."""
        if not isinstance(reference, FieldReference):
            raise TypeError("reference must be FieldReference")
        self._field_reference = reference

    @property
    def field_reference(self) -> FieldReference:
        return self._field_reference

    @property
    def field_heading_yaw_rad(self) -> float | None:
        return self._field_reference.field_heading_yaw_rad

    @property
    def field_heading_time(self) -> float | None:
        return self._field_reference.confirmed_at_s

    @property
    def field_heading_confirmed(self) -> bool:
        return self._field_reference.is_confirmed

    @property
    def field_heading_source(self) -> str:
        return self._field_reference.heading_source or ""

    @property
    def field_origin_lat(self) -> float | None:
        return self._field_reference.origin_lat

    @property
    def field_origin_lon(self) -> float | None:
        return self._field_reference.origin_lon

    @property
    def field_origin_time(self) -> float | None:
        return self._field_reference.confirmed_at_s

    @property
    def field_origin_gps_confirmed(self) -> bool:
        return self._field_reference.is_ready_for_field_to_gps()

    @property
    def field_forward_marker_lat(self) -> float | None:
        return self._field_reference.forward_marker_lat

    @property
    def field_forward_marker_lon(self) -> float | None:
        return self._field_reference.forward_marker_lon

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
            "field_reference": snapshot.get("field_reference", {}),
        }
        if self.field_heading_yaw_rad is not None:
            context["field_heading_yaw_rad"] = self.field_heading_yaw_rad
            context["field_heading_time"] = self.field_heading_time
        context["field_heading_confirmed"] = bool(self.field_heading_confirmed)
        context["field_heading_source"] = self.field_heading_source
        context["field_origin_gps_confirmed"] = bool(self.field_origin_gps_confirmed)
        context["field_gps_transform_confirmed"] = self.field_gps_transform_ready()
        if self.field_origin_gps_confirmed:
            context["field_origin_lat"] = self.field_origin_lat
            context["field_origin_lon"] = self.field_origin_lon
            context["field_origin_time"] = self.field_origin_time
            context["field_reference_mode"] = self.field_reference_mode
            context["field_forward_marker_lat"] = self.field_forward_marker_lat
            context["field_forward_marker_lon"] = self.field_forward_marker_lon
            context["field_baseline_m"] = self.field_baseline_m
            context["field_runtime_profile_id"] = self.field_runtime_profile_id
            context["field_gps_sample_count"] = self.field_gps_sample_count
            context["field_gps_horizontal_spread_m"] = self.field_gps_horizontal_spread_m
            context["field_gps_fix_type"] = self.field_gps_fix_type
            context["field_gps_satellites"] = self.field_gps_satellites
            context["field_gps_eph"] = self.field_gps_eph
            context["field_gps_epv"] = self.field_gps_epv
            context["field_gps_sample_count"] = self.field_gps_sample_count
            context["field_gps_rejected_sample_count"] = self.field_gps_rejected_sample_count
            context["field_gps_duplicate_sample_count"] = self.field_gps_duplicate_sample_count
            context["field_gps_sample_duration_s"] = self.field_gps_sample_duration_s
            context["field_gps_horizontal_spread_m"] = self.field_gps_horizontal_spread_m
        context["field_gps_transform"] = self.field_gps_transform()

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
            context["field_origin_gps_confirmed"] = bool(self.field_origin_gps_confirmed)
            context["field_gps_transform_confirmed"] = self.field_gps_transform_ready()
            if self.field_origin_gps_confirmed:
                context["field_forward_marker_lat"] = self.field_forward_marker_lat
                context["field_forward_marker_lon"] = self.field_forward_marker_lon
                context["field_baseline_m"] = self.field_baseline_m
            context["field_gps_transform"] = self.field_gps_transform()

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
            local_z = self._float_or_none(drone.get("local_z"))
            local_altitude_valid = bool(drone.get("local_position_valid") is True and local_z is not None and local_z <= 0.0)
            context["local_altitude_valid"] = local_altitude_valid
            if local_altitude_valid:
                context["local_altitude_m"] = max(0.0, -local_z)
                context["local_altitude_source"] = "local_position_ned_z"

        return self.json_safe(context)

    def field_gps_transform_ready(self) -> bool:
        """True when ready for FIELD → GLOBAL GPS transform."""
        return self._field_reference.is_ready_for_field_to_gps()

    def field_gps_transform(self) -> dict[str, object]:
        return {
            "heading_yaw_rad": self.field_heading_yaw_rad,
            "origin_lat": self.field_origin_lat,
            "origin_lon": self.field_origin_lon,
            "forward_marker_lat": self.field_forward_marker_lat,
            "forward_marker_lon": self.field_forward_marker_lon,
            "baseline_m": self.field_baseline_m,
            "confirmed": self.field_gps_transform_ready(),
            "mode": self.field_reference_mode,
            "profile_id": self.field_runtime_profile_id,
            "convention": "field_y_forward_field_x_right",
        }

    def gps_to_field_xy(self, lat: object, lon: object) -> tuple[float, float] | None:
        """Convert drone GPS lat/lon to FIELD x/y using runtime GPS reference.

        Returns None when the GPS transform is not ready or inputs are invalid.
        """
        if not self.field_gps_transform_ready():
            return None
        la = self._float_or_none(lat)
        lo = self._float_or_none(lon)
        if la is None or lo is None:
            return None
        try:
            result = gps_to_field_from_origin(
                la,
                lo,
                altitude_m=0.0,
                origin_lat=float(self.field_origin_lat),
                origin_lon=float(self.field_origin_lon),
                field_heading_yaw_rad=float(self.field_heading_yaw_rad),
            )
        except Exception:
            return None
        return (result.field_x_m, result.field_y_m)

    def field_position_from_drone(self, drone: object) -> dict[str, object] | None:
        if not isinstance(drone, dict):
            return None

        # ── Priority 1: GPS → FIELD (runtime GPS reference) ──
        if self.field_gps_transform_ready() and bool(drone.get("global_position_valid", False)):
            gps_converted = self.gps_to_field_xy(drone.get("lat"), drone.get("lon"))
            if gps_converted is not None:
                field_x, field_y = gps_converted
                return {
                    "x": field_x,
                    "y": field_y,
                    "z": self._float_or_none(drone.get("local_z")),
                    "lat": self._float_or_none(drone.get("lat")),
                    "lon": self._float_or_none(drone.get("lon")),
                    "local_x": self._float_or_none(drone.get("local_x")),
                    "local_y": self._float_or_none(drone.get("local_y")),
                    "local_z": self._float_or_none(drone.get("local_z")),
                    "source": "runtime_gps",
                    "confirmed": True,
                }

        return None

    def set_calibration_metadata(self, candidate: object) -> bool:
        """Store non-coordinate calibration diagnostics for Action/Web context.

        The coordinate reference itself is owned by FieldService and shared by
        this builder; this method never writes heading or origin fields.
        """
        errs = validate_runtime_field_binding_candidate(candidate)
        if errs:
            return False
        c = candidate
        self.field_reference_mode = c.field_reference_mode
        self.field_baseline_m = float(c.baseline_m)
        self.field_runtime_profile_id = c.profile_id
        self.field_gps_sample_count = c.sample_count
        self.field_gps_rejected_sample_count = c.rejected_sample_count
        self.field_gps_duplicate_sample_count = c.duplicate_sample_count
        self.field_gps_sample_duration_s = float(c.sample_duration_s)
        self.field_gps_horizontal_spread_m = float(c.horizontal_spread_m)
        self.field_gps_fix_type = c.gps_fix_type
        self.field_gps_satellites = c.gps_satellites
        self.field_gps_eph = float(c.gps_eph)
        self.field_gps_epv = float(c.gps_epv)
        return True

    def clear_field_heading(self) -> None:
        """Clear all field-heading and origin fields."""
        self._field_reference.reset()
        self.field_reference_mode = ""
        self.field_baseline_m = None
        self.field_gps_sample_count = None
        self.field_gps_rejected_sample_count = None
        self.field_gps_duplicate_sample_count = None
        self.field_gps_sample_duration_s = None
        self.field_gps_horizontal_spread_m = None
        self.field_gps_fix_type = None
        self.field_gps_satellites = None
        self.field_gps_eph = None
        self.field_gps_epv = None
        self.field_runtime_profile_id = ""
        self.logger.info("field heading cleared via FieldReference reset")

    # ------------------------------------------------------------------
    # snapshot / restore (5B.1)
    # ------------------------------------------------------------------

    _CALIBRATION_METADATA_KEYS = (
        "field_reference_mode", "field_baseline_m",
        "field_gps_sample_count", "field_gps_rejected_sample_count", "field_gps_duplicate_sample_count",
        "field_gps_sample_duration_s", "field_gps_horizontal_spread_m",
        "field_gps_fix_type", "field_gps_satellites", "field_gps_eph", "field_gps_epv",
        "field_runtime_profile_id",
    )

    def snapshot_calibration_metadata(self) -> dict[str, object]:
        return {key: getattr(self, key) for key in self._CALIBRATION_METADATA_KEYS}

    def restore_calibration_metadata(self, snapshot: object) -> bool:
        if not isinstance(snapshot, dict) or set(snapshot) != set(self._CALIBRATION_METADATA_KEYS):
            return False
        for key in self._CALIBRATION_METADATA_KEYS:
            setattr(self, key, snapshot[key])
        return True

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
    @classmethod
    def json_safe(cls, value):
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(key): cls.json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls.json_safe(item) for item in value]
        return value
