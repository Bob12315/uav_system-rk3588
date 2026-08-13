"""Schema-v3 runtime Field Reference controller."""
from __future__ import annotations

import math
import os
from copy import deepcopy
from dataclasses import replace
from typing import Any, Mapping

from field.profile import FieldProfile, validate_field_profile
from field.profile_service import FieldProfileService
from field.models import validate_wgs84_lat_lon
from field._reference_store import _ReferenceStore
from field.calibration_session import CalibrationSession
from field.context import RuntimeContextBuilder


class FieldService:
    _REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    _PROFILE_DIRS = [
        os.path.join(_REPO_ROOT, "config", "field_profiles"),
        os.path.join(_REPO_ROOT, "runtime", "field_profiles"),
    ]

    def __init__(self, runtime_context_builder: RuntimeContextBuilder, get_drone_snapshot: Any,
                 reference_store: _ReferenceStore | None = None) -> None:
        self._svc = reference_store or _ReferenceStore()
        self._builder = runtime_context_builder
        self._builder.bind_field_reference(self._svc.reference)
        self._get_drone_snapshot = get_drone_snapshot
        self._runtime_binding = CalibrationSession(self._svc, runtime_context_builder)
        self._active_profile_id: str | None = None

    @property
    def reference(self):
        return self._svc.reference

    def status(self) -> dict[str, object]:
        drone = self._drone_snapshot()
        state = self._svc.status()
        yaw = state.get("field_heading_yaw_rad")
        active = state.get("origin_source") == "runtime_current_gps"
        return {
            "ok": True,
            "field_reference": {
                "is_confirmed": state["is_confirmed"], "is_frozen": state["is_frozen"],
                "is_ready": self._svc.reference.is_ready(),
                "is_ready_for_field_to_gps": self._svc.reference.is_ready_for_field_to_gps(),
                "origin_source": state["origin_source"], "heading_source": state["heading_source"],
                "origin_lat": state["origin_lat"], "origin_lon": state["origin_lon"],
                "forward_marker_lat": state.get("forward_marker_lat"), "forward_marker_lon": state.get("forward_marker_lon"),
                "field_heading_yaw_rad": yaw,
                "field_heading_deg": math.degrees(float(yaw)) if yaw is not None else None,
                "active_source": "runtime_origin_forward_marker" if active else "none",
                "synced_to_runtime": self._runtime_binding.synced_to_runtime(state, require_frozen=True) if active else False,
                "profile_id": self._active_profile_id,
                "runtime_binding": self._runtime_binding.status(),
                "warnings": [],
            },
            "telemetry": {
                "global_position_valid": bool(drone.get("global_position_valid", False)),
                "lat": drone.get("lat"), "lon": drone.get("lon"),
                "last_global_position_time": drone.get("last_global_position_time"),
                "gps_fix_type": drone.get("gps_fix_type", 0), "satellites_visible": drone.get("satellites_visible", 0),
                "gps_eph": drone.get("gps_eph", -1.0), "gps_epv": drone.get("gps_epv", -1.0),
            },
        }

    def reset(self) -> dict[str, object]:
        self._runtime_binding.reset()
        self._builder.clear_field_heading()
        self._active_profile_id = None
        return self._svc.reset()

    def freeze(self) -> dict[str, object]:
        return self._svc.freeze()

    def start_runtime_profile_sampling(self, profile_id: str, *, started_at_s: float) -> dict[str, object]:
        profile, errors = self._load_profile(profile_id)
        if profile is None:
            return {"ok": False, "state": self._runtime_binding.state, "profile_id": profile_id, "error": errors[0]}
        if profile.extra.get("template_only") is True:
            return {"ok": False, "state": self._runtime_binding.state, "profile_id": profile_id, "error": "template-only profile requires the competition runtime setup endpoint"}
        return self._runtime_binding.start(profile, started_at_s=started_at_s)

    def start_competition_runtime_sampling(self, forward_marker_lat: float, forward_marker_lon: float, *, started_at_s: float) -> dict[str, object]:
        profile, errors = self._load_profile("competition_runtime_v3")
        if profile is None:
            return {"ok": False, "state": self._runtime_binding.state, "error": errors[0]}
        try:
            validate_wgs84_lat_lon(forward_marker_lat, forward_marker_lon, reject_pole=True)
        except Exception as exc:
            return {"ok": False, "state": self._runtime_binding.state, "error": f"invalid forward marker: {exc}"}
        runtime_profile = deepcopy(profile)
        runtime_profile.forward_marker = replace(profile.forward_marker, lat=float(forward_marker_lat), lon=float(forward_marker_lon))
        diagnostics = validate_field_profile(runtime_profile)
        if not diagnostics.ok:
            return {"ok": False, "state": self._runtime_binding.state, "error": diagnostics.errors[0], "errors": diagnostics.errors}
        return self._runtime_binding.start(runtime_profile, started_at_s=started_at_s, template_profile_id=profile.profile_id, runtime_profile_id="competition_runtime_session", input_source="web_ui_runtime", forward_marker_lat=float(forward_marker_lat), forward_marker_lon=float(forward_marker_lon))

    def observe_runtime_profile_sampling(self, snapshot: Mapping[str, object], *, observed_at_s: float) -> dict[str, object]:
        result = self._runtime_binding.observe(snapshot, observed_at_s=observed_at_s)
        if result.get("ok") is True and result.get("state") == "applied":
            self._active_profile_id = str(result.get("profile_id") or "competition_runtime_v3")
        return result

    def finalize_runtime_profile_binding(self, *, completed_at_s: float) -> dict[str, object]:
        result = self._runtime_binding.finalize(completed_at_s=completed_at_s)
        if result.get("ok") is True:
            self._active_profile_id = str(result.get("profile_id") or "competition_runtime_v3")
        return result

    def cancel_runtime_profile_sampling(self) -> dict[str, object]:
        return self._runtime_binding.cancel()

    def _load_profile(self, profile_id: str) -> tuple[FieldProfile | None, list[str]]:
        errors: list[str] = []
        for directory in self._PROFILE_DIRS:
            try:
                return FieldProfileService.load_profile(profile_id, profile_dir=directory), errors
            except FileNotFoundError:
                continue
            except Exception as exc:
                errors.append(str(exc))
        return None, errors or [f"profile not found: {profile_id}"]

    def _drone_snapshot(self) -> dict[str, object]:
        snapshot = self._get_drone_snapshot()
        return dict(snapshot) if isinstance(snapshot, Mapping) else {}
