from __future__ import annotations

import math
from typing import Any

from app.field_reference import _gps_distance_m
from app.field_reference_service import FieldReferenceService
from app.runtime_context import RuntimeContextBuilder


class FieldReferenceController:
    """Thin controller for the /api/field-reference/* endpoints.

    Extracted from SystemRunner (SR-1).  Reads drone state through
    the *get_drone_snapshot* callback.  Does not depend on Web UI,
    LinkManager, or MAVLink.
    """

    def __init__(
        self,
        field_reference_service: FieldReferenceService,
        runtime_context_builder: RuntimeContextBuilder,
        get_drone_snapshot: Any,
    ) -> None:
        self._svc = field_reference_service
        self._builder = runtime_context_builder
        self._get_drone_snapshot = get_drone_snapshot

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, object]:
        drone = self._drone_snapshot()
        status = self._svc.status()

        distance_m = None
        if status["origin_lat"] is not None and status["forward_marker_lat"] is not None:
            distance_m = _gps_distance_m(
                status["origin_lat"], status["origin_lon"],
                status["forward_marker_lat"], status["forward_marker_lon"],
            )

        telemetry: dict[str, object] = {
            "global_position_valid": bool(drone.get("global_position_valid", False)),
            "gps_fix_type": drone.get("gps_fix_type", 0),
            "satellites_visible": drone.get("satellites_visible", 0),
            "gps_eph": drone.get("gps_eph", -1.0),
            "gps_epv": drone.get("gps_epv", -1.0),
            "has_local_position": bool(drone.get("local_position_valid", False)),
            "has_yaw": bool(drone.get("attitude_valid", False)),
        }

        field_heading_deg = None
        if status["field_heading_yaw_rad"] is not None:
            field_heading_deg = math.degrees(float(status["field_heading_yaw_rad"]))

        fr: dict[str, object] = {
            "is_confirmed": status["is_confirmed"],
            "is_frozen": status["is_frozen"],
            "origin_source": status["origin_source"],
            "heading_source": status["heading_source"],
            "field_heading_yaw_rad": status["field_heading_yaw_rad"],
            "field_heading_deg": field_heading_deg,
            "origin_local_n_m": status["origin_local_n_m"],
            "origin_local_e_m": status["origin_local_e_m"],
            "origin_local_z_m": status["origin_local_z_m"],
            "origin_lat": status["origin_lat"],
            "origin_lon": status["origin_lon"],
            "forward_marker_lat": status["forward_marker_lat"],
            "forward_marker_lon": status["forward_marker_lon"],
            "distance_m": distance_m,
            "warnings": [],
        }

        # synced-to-legacy-runtime check
        builder = self._builder
        fr["active_source"] = (
            "legacy_field_heading"
            if builder.field_heading_confirmed and not status["is_confirmed"]
            else "field_reference"
            if status["is_confirmed"]
            else "none"
        )
        fr["synced_to_runtime"] = (
            builder.field_heading_confirmed
            and builder.field_origin_confirmed
            and status["is_confirmed"]
            and builder.field_heading_yaw_rad == status.get("field_heading_yaw_rad")
        )

        return {"ok": True, "field_reference": fr, "telemetry": telemetry}

    # ------------------------------------------------------------------
    # mark / set
    # ------------------------------------------------------------------

    def mark_origin(self) -> dict[str, object]:
        drone = self._drone_snapshot()
        if not isinstance(drone, dict):
            return {"ok": False, "error": "drone state unavailable"}
        if not bool(drone.get("global_position_valid", False)):
            return {"ok": False, "error": "no valid GPS position"}
        gps_fix = drone.get("gps_fix_type", 0)
        if not isinstance(gps_fix, (int, float)) or int(gps_fix) < 3:
            return {"ok": False, "error": f"GPS fix type {gps_fix} < 3"}
        lat = RuntimeContextBuilder._float_or_none(drone.get("lat"))
        lon = RuntimeContextBuilder._float_or_none(drone.get("lon"))
        if lat is None or lon is None:
            return {"ok": False, "error": "GPS lat/lon not available"}
        local_x = RuntimeContextBuilder._float_or_none(drone.get("local_x"))
        local_y = RuntimeContextBuilder._float_or_none(drone.get("local_y"))
        local_z = RuntimeContextBuilder._float_or_none(drone.get("local_z"))
        if not bool(drone.get("local_position_valid", False)) or local_x is None or local_y is None:
            return {"ok": False, "error": "no valid LOCAL_NED position"}
        return self._svc.mark_gps_origin(
            lat, lon, local_n_m=local_x, local_e_m=local_y, local_z_m=local_z,
        )

    def mark_forward(self) -> dict[str, object]:
        drone = self._drone_snapshot()
        if not isinstance(drone, dict):
            return {"ok": False, "error": "drone state unavailable"}
        if not bool(drone.get("global_position_valid", False)):
            return {"ok": False, "error": "no valid GPS position"}
        gps_fix = drone.get("gps_fix_type", 0)
        if not isinstance(gps_fix, (int, float)) or int(gps_fix) < 3:
            return {"ok": False, "error": f"GPS fix type {gps_fix} < 3"}
        lat = RuntimeContextBuilder._float_or_none(drone.get("lat"))
        lon = RuntimeContextBuilder._float_or_none(drone.get("lon"))
        if lat is None or lon is None:
            return {"ok": False, "error": "GPS lat/lon not available"}
        return self._svc.mark_gps_forward(lat, lon)

    def use_current_yaw(self) -> dict[str, object]:
        drone = self._drone_snapshot()
        if not isinstance(drone, dict):
            return {"ok": False, "error": "drone state unavailable"}
        if not bool(drone.get("attitude_valid", False)):
            return {"ok": False, "error": "attitude yaw not valid"}
        yaw = RuntimeContextBuilder._float_or_none(drone.get("yaw"))
        if yaw is None:
            return {"ok": False, "error": "attitude yaw not valid"}
        return self._svc.set_compass_heading(yaw)

    def set_manual_heading(self, yaw_deg: float) -> dict[str, object]:
        try:
            yaw_rad = math.radians(float(yaw_deg))
        except (TypeError, ValueError):
            return {"ok": False, "error": "yaw_deg must be a number"}
        return self._svc.set_manual_heading(yaw_rad)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def confirm(self) -> dict[str, object]:
        result = self._svc.confirm()
        if not result.get("ok"):
            return result

        ref = self._svc.reference
        yaw = ref.field_heading_yaw_rad
        ox = ref.origin_local_n_m
        oy = ref.origin_local_e_m
        oz = ref.origin_local_z_m
        if yaw is None or ox is None or oy is None:
            return {"ok": False, "error": "confirm succeeded but missing heading or LOCAL_NED origin"}

        hs = ref.heading_source or ""
        source = f"field_reference:{hs}" if hs else "field_reference"

        ok = self._builder.confirm_field_reference(
            field_heading_yaw_rad=yaw,
            origin_local_x=ox,
            origin_local_y=oy,
            origin_local_z=oz,
            source=source,
            timestamp=ref.confirmed_at_s,
        )
        if not ok:
            return {"ok": False, "error": "confirm succeeded but failed to sync to runtime context"}
        result["synced_to_runtime"] = True
        return result

    def reset(self) -> dict[str, object]:
        result = self._svc.reset()
        self._builder.clear_field_heading()
        return result

    def freeze(self) -> dict[str, object]:
        return self._svc.freeze()

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _drone_snapshot(self) -> dict[str, object]:
        return self._get_drone_snapshot()