from __future__ import annotations

import logging
import math
import time
from typing import Any, Mapping

from .coordinate_transform import field_to_local_ned, gps_to_field_from_origin, local_ned_to_field
from .field_reference import FieldReference, WGS84_POLE_COS_EPS
from .runtime_field_binding import (
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
        self.field_origin_lat: float | None = None
        self.field_origin_lon: float | None = None
        self.field_origin_time: float | None = None
        self.field_origin_confirmed: bool = False
        self.field_origin_gps_confirmed: bool = False
        self.field_reference_mode: str = ""
        self.field_forward_marker_lat: float | None = None
        self.field_forward_marker_lon: float | None = None
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
        if self.field_origin_confirmed:
            context["field_origin_local_x"] = self.field_origin_local_x
            context["field_origin_local_y"] = self.field_origin_local_y
            context["field_origin_local_z"] = self.field_origin_local_z
            context["field_origin_lat"] = self.field_origin_lat
            context["field_origin_lon"] = self.field_origin_lon
            context["field_origin_time"] = self.field_origin_time
        context["field_origin_confirmed"] = bool(self.field_origin_confirmed)
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
        context["field_transform"] = self.field_transform()
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
            if self.field_origin_confirmed:
                context["field_origin_local_x"] = self.field_origin_local_x
                context["field_origin_local_y"] = self.field_origin_local_y
                context["field_origin_local_z"] = self.field_origin_local_z
                context["field_origin_lat"] = self.field_origin_lat
                context["field_origin_lon"] = self.field_origin_lon
                context["field_origin_time"] = self.field_origin_time
            context["field_origin_confirmed"] = bool(self.field_origin_confirmed)
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

        return self.json_safe(context)

    def field_transform_ready(self) -> bool:
        return bool(
            self.field_heading_confirmed
            and self.field_origin_confirmed
            and self._float_or_none(self.field_heading_yaw_rad) is not None
            and self._float_or_none(self.field_origin_local_x) is not None
            and self._float_or_none(self.field_origin_local_y) is not None
        )

    def field_gps_transform_ready(self) -> bool:
        """True when ready for FIELD → GLOBAL GPS transform."""
        return bool(
            self.field_heading_confirmed
            and self.field_origin_gps_confirmed
            and self.field_heading_yaw_rad is not None
            and self.field_origin_lat is not None
            and self.field_origin_lon is not None
            and _is_finite_number(self.field_heading_yaw_rad)
            and _is_finite_number(self.field_origin_lat)
            and _is_finite_number(self.field_origin_lon)
            and -90.0 <= float(self.field_origin_lat) <= 90.0
            and -180.0 <= float(self.field_origin_lon) <= 180.0
            and abs(math.cos(math.radians(float(self.field_origin_lat)))) > WGS84_POLE_COS_EPS
        )

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

    def field_transform(self) -> dict[str, object]:
        return {
            "heading_yaw_rad": self.field_heading_yaw_rad,
            "origin_local_x": self.field_origin_local_x,
            "origin_local_y": self.field_origin_local_y,
            "origin_local_z": self.field_origin_local_z,
            "origin_lat": self.field_origin_lat,
            "origin_lon": self.field_origin_lon,
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

        # ── Priority 2: LOCAL_NED → FIELD (legacy field reference) ──
        if not bool(drone.get("local_position_valid", False)):
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
            "source": "local_field_reference",
            "confirmed": True,
        }

    def confirm_field_reference(
        self,
        field_heading_yaw_rad: float,
        origin_local_x: float,
        origin_local_y: float,
        origin_local_z: float | None = None,
        origin_lat: float | None = None,
        origin_lon: float | None = None,
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
        self.field_origin_lat = self._float_or_none(origin_lat)
        self.field_origin_lon = self._float_or_none(origin_lon)
        self.field_origin_time = now
        self.field_origin_confirmed = True
        # GPS-ready from legacy centerline — explicitly clear first
        self.field_origin_gps_confirmed = False
        if self.field_origin_lat is not None and self.field_origin_lon is not None:
            if (
                _is_finite_number(self.field_origin_lat)
                and _is_finite_number(self.field_origin_lon)
                and -90.0 <= float(self.field_origin_lat) <= 90.0
                and -180.0 <= float(self.field_origin_lon) <= 180.0
                and abs(math.cos(math.radians(float(self.field_origin_lat)))) > WGS84_POLE_COS_EPS
            ):
                self.field_origin_gps_confirmed = True
        self.field_reference_mode = ""
        self.field_forward_marker_lat = None
        self.field_forward_marker_lon = None
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
        self.logger.info(
            "field reference synced yaw_rad=%s origin=(%s,%s,%s) gps=(%s,%s) source=%s",
            self.field_heading_yaw_rad,
            ox, oy, self.field_origin_local_z,
            self.field_origin_lat, self.field_origin_lon,
            source,
        )
        return True


    def confirm_runtime_gps_reference(
        self,
        candidate: object,
        *,
        timestamp: float | None = None,
    ) -> bool:
        """Write a runtime GPS binding candidate using the shared validator."""
        errs = validate_runtime_field_binding_candidate(candidate)
        if errs:
            return False
        c = candidate  # type: ignore[assignment]
        ts = timestamp if timestamp is not None else float(c.completed_at_s)
        if not _is_finite_number(ts) or float(ts) < float(c.completed_at_s):
            return False
        ts = float(ts)
        normalized = self._normalize_yaw(float(c.field_heading_yaw_rad))
        self.field_heading_yaw_rad = normalized
        self.field_heading_time = ts
        self.field_heading_confirmed = True
        self.field_heading_source = c.heading_source
        self.field_origin_lat = float(c.origin_lat)
        self.field_origin_lon = float(c.origin_lon)
        self.field_origin_time = ts
        self.field_origin_gps_confirmed = True
        self.field_origin_local_x = None
        self.field_origin_local_y = None
        self.field_origin_local_z = None
        self.field_origin_confirmed = False
        self.field_reference_mode = c.field_reference_mode
        self.field_forward_marker_lat = float(c.forward_marker_lat)
        self.field_forward_marker_lon = float(c.forward_marker_lon)
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
        self.logger.info(
            "runtime gps reference synced origin=(%s,%s) heading=%s baseline=%s",
            self.field_origin_lat, self.field_origin_lon,
            self.field_heading_yaw_rad, self.field_baseline_m)
        return True

    def clear_field_heading(self) -> None:
        """Clear all field-heading and origin fields."""
        self.field_heading_yaw_rad = None
        self.field_heading_time = None
        self.field_heading_confirmed = False
        self.field_heading_source = ""
        self.field_origin_local_x = None
        self.field_origin_local_y = None
        self.field_origin_local_z = None
        self.field_origin_lat = None
        self.field_origin_lon = None
        self.field_origin_time = None
        self.field_origin_confirmed = False
        self.field_origin_gps_confirmed = False
        self.field_reference_mode = ""
        self.field_forward_marker_lat = None
        self.field_forward_marker_lon = None
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

    _FIELD_REFERENCE_KEYS = (
        "field_heading_yaw_rad", "field_heading_time", "field_heading_confirmed", "field_heading_source",
        "field_origin_local_x", "field_origin_local_y", "field_origin_local_z",
        "field_origin_lat", "field_origin_lon", "field_origin_time",
        "field_origin_confirmed", "field_origin_gps_confirmed",
        "field_reference_mode",
        "field_forward_marker_lat", "field_forward_marker_lon", "field_baseline_m",
        "field_gps_sample_count", "field_gps_rejected_sample_count", "field_gps_duplicate_sample_count",
        "field_gps_sample_duration_s", "field_gps_horizontal_spread_m",
        "field_gps_fix_type", "field_gps_satellites", "field_gps_eph", "field_gps_epv",
        "field_runtime_profile_id",
    )

    def snapshot_field_reference_state(self) -> dict[str, object]:
        """Capture all FieldReference-sync-related fields."""
        return {key: getattr(self, key) for key in self._FIELD_REFERENCE_KEYS}

    def restore_field_reference_state(self, snapshot: Mapping[str, object]) -> bool:
        """Restore from a validated snapshot. Returns False if invalid."""
        if not isinstance(snapshot, Mapping):
            return False
        keys = self._FIELD_REFERENCE_KEYS
        if set(keys) != set(snapshot.keys()):
            return False
        for key in ("field_heading_confirmed", "field_origin_confirmed", "field_origin_gps_confirmed"):
            if not isinstance(snapshot.get(key), bool):
                return False
        for key in ("field_heading_source", "field_reference_mode", "field_runtime_profile_id"):
            if not isinstance(snapshot.get(key), str):
                return False
        if snapshot.get("field_heading_confirmed") is True:
            if not _is_finite_number(snapshot.get("field_heading_yaw_rad")):
                return False
            if not snapshot.get("field_heading_source"):
                return False
        if snapshot.get("field_origin_confirmed") is True:
            if not _is_finite_number(snapshot.get("field_origin_local_x")):
                return False
            if not _is_finite_number(snapshot.get("field_origin_local_y")):
                return False
        if snapshot.get("field_origin_gps_confirmed") is True:
            olat = snapshot.get("field_origin_lat"); olon = snapshot.get("field_origin_lon")
            if not _is_finite_number(olat) or not _is_finite_number(olon): return False
            f_lat = float(olat); f_lon = float(olon)
            if f_lat < -90.0 or f_lat > 90.0: return False
            if f_lon < -180.0 or f_lon > 180.0: return False
            if abs(math.cos(math.radians(f_lat))) <= WGS84_POLE_COS_EPS: return False
            if not snapshot.get("field_heading_confirmed"): return False
        for key in ("field_gps_sample_duration_s", "field_gps_horizontal_spread_m", "field_gps_eph", "field_gps_epv"):
            v = snapshot.get(key)
            if v is not None and (not _is_finite_number(v) or float(v) < 0.0): return False
        for key in ("field_gps_sample_count", "field_gps_rejected_sample_count", "field_gps_duplicate_sample_count", "field_gps_fix_type", "field_gps_satellites"):
            v = snapshot.get(key)
            if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and v >= 0): return False
        for key in ("field_heading_yaw_rad", "field_heading_time",
                     "field_origin_local_x", "field_origin_local_y", "field_origin_local_z",
                     "field_origin_lat", "field_origin_lon", "field_origin_time",
                     "field_forward_marker_lat", "field_forward_marker_lon", "field_baseline_m"):
            v = snapshot.get(key)
            if v is not None and not _is_finite_number(v): return False
        bm = snapshot.get("field_baseline_m")
        if bm is not None and float(bm) <= 0.0: return False
        for lat_key in ("field_origin_lat", "field_forward_marker_lat"):
            v = snapshot.get(lat_key)
            if v is not None and (float(v) < -90.0 or float(v) > 90.0): return False
        for lon_key in ("field_origin_lon", "field_forward_marker_lon"):
            v = snapshot.get(lon_key)
            if v is not None and (float(v) < -180.0 or float(v) > 180.0): return False
        mode = snapshot.get("field_reference_mode", "")
        if mode == "runtime_origin_forward_marker":
            if not snapshot.get("field_heading_confirmed"): return False
            if not snapshot.get("field_origin_gps_confirmed"): return False
            if snapshot.get("field_heading_source", "") != "runtime_forward_marker": return False
            if not _is_finite_number(snapshot.get("field_forward_marker_lat")): return False
            if not _is_finite_number(snapshot.get("field_forward_marker_lon")): return False
            if not _is_finite_number(snapshot.get("field_baseline_m")) or float(snapshot["field_baseline_m"]) <= 0.0: return False
            if not snapshot.get("field_runtime_profile_id"): return False
            for key, minimum in (("field_gps_sample_count", 1), ("field_gps_rejected_sample_count", 0),
                                 ("field_gps_duplicate_sample_count", 0), ("field_gps_fix_type", 0),
                                 ("field_gps_satellites", 0)):
                v = snapshot.get(key)
                if not (isinstance(v, int) and not isinstance(v, bool) and v >= minimum): return False
            for key in ("field_gps_sample_duration_s", "field_gps_horizontal_spread_m",
                         "field_gps_eph", "field_gps_epv"):
                v = snapshot.get(key)
                if not _is_finite_number(v) or float(v) < 0.0: return False
        elif mode != "": return False
        else:
            for key in ("field_forward_marker_lat", "field_forward_marker_lon", "field_baseline_m",
                         "field_gps_sample_count", "field_gps_rejected_sample_count", "field_gps_duplicate_sample_count",
                         "field_gps_sample_duration_s", "field_gps_horizontal_spread_m",
                         "field_gps_fix_type", "field_gps_satellites", "field_gps_eph", "field_gps_epv"):
                if snapshot.get(key) is not None: return False
            if snapshot.get("field_runtime_profile_id") != "": return False
        for key in keys:
            setattr(self, key, snapshot[key])
        return True    # ------------------------------------------------------------------
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
