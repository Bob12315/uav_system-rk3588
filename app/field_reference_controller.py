from __future__ import annotations

import math
import os
import time as _time
from typing import Any, Optional

from app.field_profile import FieldProfile, load_field_profile_json
from app.field_profile_service import BindResult, FieldProfileService
from app.field_reference import _gps_distance_m
from app.field_reference_service import FieldReferenceService
from app.runtime_context import RuntimeContextBuilder


class FieldReferenceController:
    """Thin controller for the /api/field-reference/* endpoints.

    Extracted from SystemRunner (SR-1).  Reads drone state through
    the *get_drone_snapshot* callback.  Does not depend on Web UI,
    LinkManager, or MAVLink.
    """

    _PROFILE_DIRS = [
        os.path.join("config", "field_profiles"),
        os.path.join("runtime", "field_profiles"),
    ]

    def __init__(
        self,
        field_reference_service: FieldReferenceService,
        runtime_context_builder: RuntimeContextBuilder,
        get_drone_snapshot: Any,
    ) -> None:
        self._svc = field_reference_service
        self._builder = runtime_context_builder
        self._get_drone_snapshot = get_drone_snapshot
        self._last_bind_result: Optional[BindResult] = None
        self._last_bound_profile_id: Optional[str] = None

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

        # profile binding info
        if self._last_bound_profile_id:
            fr["profile_id"] = self._last_bound_profile_id
            fr["profile_binding_ok"] = (
                self._last_bind_result.ok if self._last_bind_result else None
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
        self._last_bind_result = None
        self._last_bound_profile_id = None
        return result

    def freeze(self) -> dict[str, object]:
        return self._svc.freeze()

    # ------------------------------------------------------------------
    # profile binding
    # ------------------------------------------------------------------

    def bind_profile_current(self, profile_id: str) -> dict[str, object]:
        """Load a profile, bind to current drone GPS+LOCAL_NED, and apply.

        Returns ``{"ok": True, "synced_to_runtime": True, ...}`` on full
        success.  Fails safely if telemetry is missing, GPS quality is low,
        the reference is frozen, or the bind result is not ok.
        """
        # -- resolve profile ------------------------------------------------
        profile = None
        errors = []
        for d in self._PROFILE_DIRS:
            try:
                profile = FieldProfileService.load_profile(profile_id, profile_dir=d)
                break
            except FileNotFoundError:
                continue
            except Exception as exc:
                errors.append(str(exc))
                continue

        if profile is None:
            return {"ok": False, "error": f"profile not found: {profile_id}",
                    "errors": errors}

        # -- drone telemetry ------------------------------------------------
        drone = self._drone_snapshot()
        if not isinstance(drone, dict):
            return {"ok": False, "error": "drone state unavailable"}

        if not bool(drone.get("global_position_valid", False)):
            return {"ok": False, "error": "no valid GPS position"}

        current_lat = RuntimeContextBuilder._float_or_none(drone.get("lat"))
        current_lon = RuntimeContextBuilder._float_or_none(drone.get("lon"))
        if current_lat is None or current_lon is None:
            return {"ok": False, "error": "GPS lat/lon not available"}

        if not bool(drone.get("local_position_valid", False)):
            return {"ok": False, "error": "no valid LOCAL_NED position"}

        local_x = RuntimeContextBuilder._float_or_none(drone.get("local_x"))
        local_y = RuntimeContextBuilder._float_or_none(drone.get("local_y"))
        local_z = RuntimeContextBuilder._float_or_none(drone.get("local_z"))
        if local_x is None or local_y is None:
            return {"ok": False, "error": "LOCAL_NED x/y not available"}
        if local_z is None:
            local_z = 0.0

        gps_fix_type = drone.get("gps_fix_type", 0)
        satellites_visible = drone.get("satellites_visible", 0)
        gps_eph = drone.get("gps_eph")
        gps_epv = drone.get("gps_epv")

        # -- bind ----------------------------------------------------------
        ts = _time.time()
        bind_result = FieldProfileService.bind_profile_to_current_vehicle(
            profile=profile,
            current_lat=current_lat,
            current_lon=current_lon,
            current_local_n_m=local_x,
            current_local_e_m=local_y,
            current_local_z_m=local_z,
            gps_fix_type=gps_fix_type,
            satellites_visible=satellites_visible,
            gps_eph=gps_eph,
            gps_epv=gps_epv,
            timestamp=ts,
        )

        self._last_bind_result = bind_result

        if not bind_result.ok:
            return {
                "ok": False,
                "error": "bind failed",
                "profile_id": profile.profile_id,
                "errors": bind_result.errors,
                "warnings": bind_result.warnings,
                "diagnostics": {
                    "errors": list(bind_result.diagnostics.errors),
                    "warnings": list(bind_result.diagnostics.warnings),
                },
            }

        # -- apply to field reference --------------------------------------
        applied = self._svc.apply_profile_binding(
            bind_result=bind_result,
            profile_id=profile.profile_id,
            profile_name=profile.name,
            origin_lat=profile.origin.lat,
            origin_lon=profile.origin.lon,
            forward_lat=profile.forward.lat,
            forward_lon=profile.forward.lon,
            timestamp=ts,
        )

        if not applied.get("ok"):
            return {
                "ok": False,
                "error": applied.get("error", "apply failed"),
                "profile_id": profile.profile_id,
            }

        self._last_bound_profile_id = profile.profile_id

        # -- sync to RuntimeContext ----------------------------------------
        ref = self._svc.reference
        source = f"field_profile:{profile.profile_id}"
        ok_sync = self._builder.confirm_field_reference(
            field_heading_yaw_rad=ref.field_heading_yaw_rad,
            origin_local_x=ref.origin_local_n_m,
            origin_local_y=ref.origin_local_e_m,
            origin_local_z=ref.origin_local_z_m,
            source=source,
            timestamp=ts,
        )

        return {
            "ok": True,
            "profile_id": profile.profile_id,
            "synced_to_runtime": ok_sync,
            "field_heading_yaw_rad": bind_result.field_heading_yaw_rad,
            "field_heading_deg": bind_result.field_heading_deg,
            "origin_local_n_m": bind_result.origin_local_n_m,
            "origin_local_e_m": bind_result.origin_local_e_m,
            "origin_local_z_m": bind_result.origin_local_z_m,
            "current_field_x_m": bind_result.current_field_x_m,
            "current_field_y_m": bind_result.current_field_y_m,
            "baseline_m": bind_result.baseline_m,
            "warnings": bind_result.warnings,
            "check_points": [
                {"name": cp.name, "role": cp.role,
                 "expected_field_x_m": cp.expected_field_x_m,
                 "expected_field_y_m": cp.expected_field_y_m}
                for cp in bind_result.check_points
            ],
        }

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _drone_snapshot(self) -> dict[str, object]:
        return self._get_drone_snapshot()
