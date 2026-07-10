from __future__ import annotations

import math
import os
import time as _time
from copy import deepcopy
from dataclasses import replace
from typing import Any, Mapping, Optional

from app.field_profile import FieldProfile, FieldProfileDiagnostics, ForwardMarker
from app.field_profile_service import BindResult, FieldProfileService
from app.field_reference import (
    _gps_distance_m,
    normalize_longitude_deg,
    validate_wgs84_lat_lon,
)
from app.field_reference_service import FieldReferenceService
from app.runtime_binding_orchestrator import RuntimeBindingOrchestrator
from app.runtime_context import RuntimeContextBuilder


class FieldReferenceController:
    """Thin controller for the /api/field-reference/* and /api/field-profiles/*
    endpoints.

    Supports legacy centerline binding and the explicit runtime GPS sampling
    lifecycle. Legacy marker/set/confirm/manual-heading methods are removed.
    """

    # Absolute profile directories resolved from repo root.
    _REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    _PROFILE_DIRS = [
        os.path.join(_REPO_ROOT, "config", "field_profiles"),
        os.path.join(_REPO_ROOT, "runtime", "field_profiles"),
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
        self._runtime_binding = RuntimeBindingOrchestrator(field_reference_service, runtime_context_builder)
        self._last_bind_result: Optional[BindResult] = None
        self._active_profile_id: Optional[str] = None
        self._last_bind_profile_id: Optional[str] = None

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, object]:
        drone = self._drone_snapshot()
        status = self._svc.status()

        telemetry: dict[str, object] = {
            "global_position_valid": bool(drone.get("global_position_valid", False)),
            "lat": drone.get("lat"),
            "lon": drone.get("lon"),
            "last_global_position_time": drone.get("last_global_position_time"),
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
            "warnings": [],
        }

        fr["is_ready"] = self._svc.reference.is_ready()
        fr["is_ready_for_field_to_local"] = self._svc.reference.is_ready_for_field_to_local()
        fr["is_ready_for_field_to_gps"] = self._svc.reference.is_ready_for_field_to_gps()
        fr["is_frozen"] = self._svc.reference.is_frozen
        fr["runtime_binding"] = self._runtime_binding.status()
        fr["forward_marker_lat"] = status.get("forward_marker_lat")
        fr["forward_marker_lon"] = status.get("forward_marker_lon")
        if status.get("origin_source") == "runtime_current_gps":
            fr["active_source"] = "runtime_origin_forward_marker"
            fr["synced_to_runtime"] = self._runtime_binding.synced_to_runtime(
                status, require_frozen=True
            )
        elif status.get("is_confirmed"):
            fr["active_source"] = "field_profile_centerline"
            fr["synced_to_runtime"] = self._is_field_reference_synced(
                status, self._builder
            )
        else:
            fr["active_source"] = "none"
            fr["synced_to_runtime"] = False

        # profile binding info
        if self._active_profile_id:
            fr["profile_id"] = self._active_profile_id
        if self._last_bind_result:
            fr["profile_binding_ok"] = self._last_bind_result.ok
            if self._last_bind_result.errors:
                fr["profile_binding_errors"] = list(self._last_bind_result.errors)
            if self._last_bind_result.warnings:
                fr["profile_binding_warnings"] = list(self._last_bind_result.warnings)
            fr["profile_binding_diagnostics"] = {
                "errors": list(self._last_bind_result.diagnostics.errors),
                "warnings": list(self._last_bind_result.diagnostics.warnings),
            }
            fr["current_start_error_m"] = self._last_bind_result.current_start_error_m
            fr["yaw_error_deg"] = self._last_bind_result.yaw_error_deg
            fr["max_residual_m"] = self._last_bind_result.max_residual_m
            fr["rms_residual_m"] = self._last_bind_result.rms_residual_m
            # centerline residual rows
            if self._last_bind_result.centerline_residuals:
                fr["centerline_residuals"] = [
                    {
                        "name": r.name,
                        "lat": r.lat,
                        "lon": r.lon,
                        "residual_m": r.residual_m,
                        "expected_field_y_m": r.expected_field_y_m,
                        "fitted_field_y_m": r.fitted_field_y_m,
                    }
                    for r in self._last_bind_result.centerline_residuals
                ]
            fr["warnings"] = list(self._last_bind_result.warnings)
        if self._last_bind_profile_id:
            fr["last_bind_profile_id"] = self._last_bind_profile_id

        return {"ok": True, "field_reference": fr, "telemetry": telemetry}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> dict[str, object]:
        self._runtime_binding.reset()
        result = self._svc.reset()
        self._builder.clear_field_heading()
        self._last_bind_result = None
        self._active_profile_id = None
        self._last_bind_profile_id = None
        return result

    def freeze(self) -> dict[str, object]:
        return self._svc.freeze()

    def start_runtime_profile_sampling(
        self,
        profile_id: str,
        *,
        started_at_s: float,
    ) -> dict[str, object]:
        profile, errors = self._load_profile(profile_id)
        if profile is None:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "profile_id": profile_id,
                "error": errors[0] if errors else f"profile not found: {profile_id}",
                "errors": errors,
            }
        # Reject template-only profiles on the old start endpoint
        if profile.extra.get("template_only") is True:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "profile_id": profile_id,
                "error": (
                    "template-only profile requires "
                    "/api/field-reference/runtime-sampling/start"
                ),
            }
        if profile.schema_version == 2:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "profile_id": profile_id,
                "error": "runtime GPS sampling explicitly rejects schema v2 profiles",
            }
        if profile.schema_version != 3:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "profile_id": profile_id,
                "error": f"runtime GPS sampling requires schema v3, got v{profile.schema_version}",
            }
        return self._runtime_binding.start(profile, started_at_s=started_at_s)

    def start_competition_runtime_sampling(
        self,
        forward_marker_lat: float,
        forward_marker_lon: float,
        *,
        started_at_s: float,
    ) -> dict[str, object]:
        """Competition field setup: start runtime GPS sampling with user-supplied B.

        1. Check orchestrator / Field Reference state.
        2. Load competition_runtime_v3 template.
        3. Deep-copy template, replace forward_marker with user input.
        4. Validate and start sampling.
        """
        # Check state
        if self._runtime_binding.state == "applied":
            return {
                "ok": False,
                "state": "applied",
                "error": (
                    "runtime binding is already applied; "
                    "use field reference reset first"
                ),
            }
        if self._runtime_binding.state == "sampling":
            return {
                "ok": False,
                "state": "sampling",
                "error": "runtime sampling is already in progress",
            }
        if self._svc.reference.is_frozen:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "error": "field reference is frozen; reset first",
            }

        # Load template
        template_profile, errors = self._load_profile("competition_runtime_v3")
        if template_profile is None:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "error": (
                    errors[0]
                    if errors
                    else "competition_runtime_v3 template not found"
                ),
            }
        if template_profile.schema_version != 3:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "error": (
                    f"competition_runtime_v3 must be schema v3, "
                    f"got v{template_profile.schema_version}"
                ),
            }
        if template_profile.extra.get("template_only") is not True:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "error": "competition_runtime_v3 must have template_only=true",
            }

        # Validate B coordinates
        try:
            lat_pair = validate_wgs84_lat_lon(
                forward_marker_lat, forward_marker_lon, reject_pole=True
            )
        except Exception as exc:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "error": f"invalid forward_marker coordinates: {exc}",
            }
        normalized_lat = lat_pair[0]
        normalized_lon = normalize_longitude_deg(lat_pair[1])

        # Deep-copy template
        try:
            candidate_base = deepcopy(template_profile)
        except Exception as exc:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "error": f"failed to copy template: {exc}",
            }

        # Create session profile with user's B
        runtime_profile = replace(
            candidate_base,
            profile_id="competition_runtime_session",
            name="Competition Runtime Field Session",
            forward_marker=ForwardMarker(
                name="runtime_forward_marker",
                lat=normalized_lat,
                lon=normalized_lon,
                coordinate_system="WGS84",
            ),
            extra={
                **candidate_base.extra,
                "template_profile_id": "competition_runtime_v3",
                "runtime_input_source": "web_ui_runtime",
                "template_only": False,
            },
        )

        # Run existing validation on the session profile
        from .field_profile import validate_field_profile

        diag = validate_field_profile(runtime_profile)
        if not diag.ok:
            return {
                "ok": False,
                "state": self._runtime_binding.state,
                "error": (
                    f"session profile validation failed: {'; '.join(diag.errors)}"
                ),
            }

        # Start sampling with session metadata
        result = self._runtime_binding.start(
            runtime_profile,
            started_at_s=started_at_s,
            template_profile_id="competition_runtime_v3",
            runtime_profile_id="competition_runtime_session",
            input_source="web_ui_runtime",
            forward_marker_lat=normalized_lat,
            forward_marker_lon=normalized_lon,
        )
        return result

    def observe_runtime_profile_sampling(
        self,
        snapshot: Mapping[str, object],
        *,
        observed_at_s: float,
    ) -> dict[str, object]:
        return self._runtime_binding.observe(
            snapshot, observed_at_s=observed_at_s
        )

    def finalize_runtime_profile_binding(
        self,
        *,
        completed_at_s: float,
    ) -> dict[str, object]:
        result = self._runtime_binding.finalize(completed_at_s=completed_at_s)
        if result.get("ok") is True:
            profile_id = result.get("profile_id")
            if isinstance(profile_id, str):
                self._active_profile_id = profile_id
                self._last_bind_profile_id = profile_id
            self._last_bind_result = None
        return result

    def cancel_runtime_profile_sampling(self) -> dict[str, object]:
        return self._runtime_binding.cancel()

    # ------------------------------------------------------------------
    # profile binding (centerline only)
    # ------------------------------------------------------------------

    def bind_profile_current(self, profile_id: str) -> dict[str, object]:
        """Load a profile, bind to current drone GPS+LOCAL_NED, and apply.

        Uses centerline fitting for heading.  origin_local = current
        LOCAL_NED directly.  GPS is only used for start_error check.

        Returns ``{"ok": True, "synced_to_runtime": True, ...}`` on full
        success.
        """
        # -- resolve profile ------------------------------------------------
        profile, errors = self._load_profile(profile_id)
        if profile is not None and profile.schema_version != 2:
            return {"ok": False, "error": "bind-current is only supported for schema v2; schema v3 must use runtime GPS sampling"}

        if profile is None:
            message = f"profile not found: {profile_id}"
            return self._bind_failure_response(
                profile_id,
                message,
                errors=[message, *errors],
            )

        # -- drone telemetry ------------------------------------------------
        try:
            drone = self._drone_snapshot()
        except Exception as exc:
            return self._bind_failure_response(
                profile_id, f"drone state unavailable: {exc}"
            )
        if not isinstance(drone, dict):
            return self._bind_failure_response(
                profile_id, "drone state unavailable"
            )

        if not bool(drone.get("global_position_valid", False)):
            return self._bind_failure_response(
                profile_id, "no valid GPS position"
            )

        current_lat = RuntimeContextBuilder._float_or_none(drone.get("lat"))
        current_lon = RuntimeContextBuilder._float_or_none(drone.get("lon"))
        if current_lat is None or current_lon is None:
            return self._bind_failure_response(
                profile_id, "GPS lat/lon not available"
            )

        if not bool(drone.get("local_position_valid", False)):
            return self._bind_failure_response(
                profile_id, "no valid LOCAL_NED position"
            )

        local_x = RuntimeContextBuilder._float_or_none(drone.get("local_x"))
        local_y = RuntimeContextBuilder._float_or_none(drone.get("local_y"))
        local_z = RuntimeContextBuilder._float_or_none(drone.get("local_z"))
        if local_x is None or local_y is None or local_z is None:
            missing = []
            if local_x is None:
                missing.append("local_x")
            if local_y is None:
                missing.append("local_y")
            if local_z is None:
                missing.append("local_z")
            err_msg = f"LOCAL_NED missing: {', '.join(missing)}"
            return self._bind_failure_response(profile_id, err_msg)

        # current yaw (optional, for yaw_error display only)
        current_yaw_rad = RuntimeContextBuilder._float_or_none(drone.get("yaw"))

        gps_fix_type = drone.get("gps_fix_type", 0)
        satellites_visible = drone.get("satellites_visible", 0)
        gps_eph = drone.get("gps_eph")
        gps_epv = drone.get("gps_epv")

        # -- bind ----------------------------------------------------------
        ts = _time.time()
        bind_result = FieldProfileService.takeoff_anchor_centerline(
            profile=profile,
            current_lat=current_lat,
            current_lon=current_lon,
            current_local_n_m=local_x,
            current_local_e_m=local_y,
            current_local_z_m=local_z,
            current_yaw_rad=current_yaw_rad,
            gps_fix_type=gps_fix_type,
            satellites_visible=satellites_visible,
            gps_eph=gps_eph,
            gps_epv=gps_epv,
            timestamp=ts,
        )

        if not bind_result.ok:
            return self._bind_failure_response(
                profile_id,
                "bind failed",
                errors=list(bind_result.errors),
                warnings=list(bind_result.warnings),
                diagnostic_errors=list(bind_result.diagnostics.errors),
                diagnostic_warnings=list(bind_result.diagnostics.warnings),
            )

        # -- save old state for rollback -----------------------------------
        service_snapshot = self._svc.snapshot()
        builder_snapshot = self._builder.snapshot_field_reference_state()
        saved_active_id = self._active_profile_id

        # -- apply to field reference --------------------------------------
        try:
            applied = self._svc.apply_profile_binding(
                bind_result=bind_result,
                profile_id=profile.profile_id,
                profile_name=profile.name,
                anchor_lat=profile.anchor.lat,
                anchor_lon=profile.anchor.lon,
                timestamp=ts,
            )
        except Exception as exc:
            self._svc.restore(service_snapshot)
            self._builder.restore_field_reference_state(builder_snapshot)
            self._active_profile_id = saved_active_id
            return self._bind_failure_response(
                profile_id, f"apply profile binding failed: {exc}"
            )

        if not applied.get("ok"):
            self._svc.restore(service_snapshot)
            self._builder.restore_field_reference_state(builder_snapshot)
            self._active_profile_id = saved_active_id
            error = str(applied.get("error") or "apply failed")
            return self._bind_failure_response(profile_id, error)

        self._active_profile_id = profile.profile_id
        self._last_bind_profile_id = profile_id

        # -- sync to RuntimeContext ----------------------------------------
        ref = self._svc.reference
        source = f"field_profile:{profile.profile_id}"
        try:
            ok_sync = self._builder.confirm_field_reference(
                field_heading_yaw_rad=ref.field_heading_yaw_rad,
                origin_local_x=ref.origin_local_n_m,
                origin_local_y=ref.origin_local_e_m,
                origin_local_z=ref.origin_local_z_m,
                origin_lat=ref.origin_lat,
                origin_lon=ref.origin_lon,
                source=source,
                timestamp=ts,
            )
        except Exception:
            ok_sync = False

        if not ok_sync:
            # -- rollback --------------------------------------------------
            self._svc.restore(service_snapshot)
            self._active_profile_id = saved_active_id
            self._builder.restore_field_reference_state(builder_snapshot)
            return self._bind_failure_response(
                profile_id,
                "apply succeeded but failed to sync to runtime context",
                errors=["sync to runtime context failed"],
            )

        self._last_bind_result = bind_result
        return {
            "ok": True,
            "profile_id": profile.profile_id,
            "synced_to_runtime": True,
            "field_heading_yaw_rad": bind_result.field_heading_yaw_rad,
            "field_heading_deg": bind_result.field_heading_deg,
            "origin_local_n_m": bind_result.origin_local_n_m,
            "origin_local_e_m": bind_result.origin_local_e_m,
            "origin_local_z_m": bind_result.origin_local_z_m,
            "baseline_m": bind_result.baseline_m,
            "current_start_error_m": bind_result.current_start_error_m,
            "yaw_error_deg": bind_result.yaw_error_deg,
            "max_residual_m": bind_result.max_residual_m,
            "rms_residual_m": bind_result.rms_residual_m,
            "warnings": bind_result.warnings,
            "centerline_residuals": [
                {
                    "name": r.name,
                    "lat": r.lat,
                    "lon": r.lon,
                    "residual_m": r.residual_m,
                    "expected_field_y_m": r.expected_field_y_m,
                    "fitted_field_y_m": r.fitted_field_y_m,
                }
                for r in bind_result.centerline_residuals
            ],
        }

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _load_profile(
        self, profile_id: str
    ) -> tuple[FieldProfile | None, list[str]]:
        errors: list[str] = []
        for directory in self._PROFILE_DIRS:
            try:
                return (
                    FieldProfileService.load_profile(
                        profile_id, profile_dir=directory
                    ),
                    errors,
                )
            except FileNotFoundError:
                continue
            except Exception as exc:
                errors.append(str(exc))
        if not errors:
            errors.append(f"profile not found: {profile_id}")
        return None, errors

    def _bind_failure_response(
        self,
        profile_id: str,
        error: str,
        *,
        errors: Optional[list[str]] = None,
        warnings: Optional[list[str]] = None,
        diagnostic_errors: Optional[list[str]] = None,
        diagnostic_warnings: Optional[list[str]] = None,
    ) -> dict[str, object]:
        """Record and return one stable bind-current failure shape."""
        error_list = list(errors) if errors else [error]
        if not error_list:
            error_list = [error]
        warning_list = list(warnings or [])
        diag_errors = list(diagnostic_errors) if diagnostic_errors is not None else list(error_list)
        diag_warnings = list(diagnostic_warnings) if diagnostic_warnings is not None else list(warning_list)
        self._last_bind_result = BindResult(
            ok=False,
            profile_id=profile_id,
            errors=error_list,
            warnings=warning_list,
            diagnostics=FieldProfileDiagnostics(
                errors=diag_errors,
                warnings=diag_warnings,
            ),
        )
        self._last_bind_profile_id = profile_id
        return {
            "ok": False,
            "error": error,
            "profile_id": profile_id,
            "synced_to_runtime": False,
            "errors": error_list,
            "warnings": warning_list,
            "diagnostics": {
                "errors": diag_errors,
                "warnings": diag_warnings,
            },
        }

    @staticmethod
    def _is_field_reference_synced(
        status: dict[str, object],
        builder: RuntimeContextBuilder,
    ) -> bool:
        """Unified sync check used by both status() and C-0 preflight."""
        if not status.get("is_confirmed"):
            return False
        if not builder.field_heading_confirmed:
            return False
        if not builder.field_origin_confirmed:
            return False

        # heading
        ref_yaw = status.get("field_heading_yaw_rad")
        if ref_yaw is None or builder.field_heading_yaw_rad is None:
            return False
        if not math.isclose(
            float(ref_yaw),
            float(builder.field_heading_yaw_rad),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return False

        # origin N/X
        ref_n = status.get("origin_local_n_m")
        builder_x = RuntimeContextBuilder._float_or_none(
            builder.field_origin_local_x
        )
        if ref_n is None or builder_x is None:
            return False
        if not math.isclose(
            float(ref_n), float(builder_x), rel_tol=1e-9, abs_tol=1e-9,
        ):
            return False

        # origin E/Y
        ref_e = status.get("origin_local_e_m")
        builder_y = RuntimeContextBuilder._float_or_none(
            builder.field_origin_local_y
        )
        if ref_e is None or builder_y is None:
            return False
        if not math.isclose(
            float(ref_e), float(builder_y), rel_tol=1e-9, abs_tol=1e-9,
        ):
            return False

        # origin Z (when available on reference)
        ref_z = status.get("origin_local_z_m")
        if ref_z is not None:
            builder_z = RuntimeContextBuilder._float_or_none(
                builder.field_origin_local_z
            )
            if builder_z is None:
                return False
            if not math.isclose(
                float(ref_z), float(builder_z), rel_tol=1e-9, abs_tol=1e-9,
            ):
                return False

        return True

    def _drone_snapshot(self) -> dict[str, object]:
        return self._get_drone_snapshot()
