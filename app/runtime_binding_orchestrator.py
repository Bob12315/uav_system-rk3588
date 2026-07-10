"""Controller-level orchestration for runtime GPS field binding.

The orchestrator owns sampling and the Service/RuntimeContext transaction.  It
does not read hardware, use wall-clock time, expose Web APIs, or send commands.
"""

from __future__ import annotations

import math
from dataclasses import fields
from typing import Mapping

from .field_profile import FieldProfile
from .field_reference_service import FieldReferenceService
from .runtime_context import RuntimeContextBuilder
from .runtime_field_binding import (
    RuntimeFieldBindingCandidate,
    RuntimeFieldBindingSampler,
)
from .runtime_field_geometry import RuntimeFieldGeometry, RuntimeFieldPoint


class RuntimeBindingOrchestrator:
    """Own one runtime sampling session and its atomic dual-state apply."""

    def __init__(
        self,
        svc: FieldReferenceService,
        builder: RuntimeContextBuilder,
    ) -> None:
        self._svc = svc
        self._builder = builder
        self._last_observed_at_s: float | None = None
        self._sampler: RuntimeFieldBindingSampler | None = None
        self._profile: FieldProfile | None = None
        self._profile_name: str | None = None
        self._candidate: RuntimeFieldBindingCandidate | None = None
        self._state = "idle"
        self._last_error: str | None = None
        self._last_result: dict[str, object] | None = None

    def start(
        self,
        profile: FieldProfile,
        *,
        started_at_s: float,
    ) -> dict[str, object]:
        if not isinstance(profile, FieldProfile):
            return self._failure("profile must be a FieldProfile", state=self._state)
        if self._state == "sampling":
            return self._failure(
                "runtime sampling is already in progress", state="sampling"
            )
        if not _finite_number(started_at_s):
            return self._failure("started_at_s must be finite", state=self._state)
        if self._svc.reference.is_frozen:
            return self._failure("field reference is frozen", state=self._state)
        if profile.schema_version != 3:
            return self._failure(
                "runtime GPS sampling requires schema v3", state=self._state
            )
        try:
            sampler = RuntimeFieldBindingSampler(profile)
            sampling = sampler.start(started_at_s=float(started_at_s))
        except Exception as exc:
            return self._failure(exc, state=self._state)

        self._sampler = sampler
        self._profile = profile
        self._profile_name = profile.name
        self._candidate = None
        self._state = "sampling"
        self._last_observed_at_s = float(started_at_s)
        self._last_error = None
        self._last_result = None
        return {
            "ok": True,
            "profile_id": profile.profile_id,
            "state": "sampling",
            "sampling": _status_dict(sampling),
        }

    def observe(
        self,
        snapshot: object,
        *,
        observed_at_s: float,
    ) -> dict[str, object]:
        if not _finite_number(observed_at_s):
            return self._failure(
                "observed_at_s must be finite", state=self._state
            )
        self._last_observed_at_s = float(observed_at_s)
        if self._sampler is None or self._state != "sampling":
            return {"ok": True, "observed": False, "state": self._state}
        try:
            sampling = self._sampler.observe_snapshot(
                snapshot, observed_at_s=float(observed_at_s)  # type: ignore[arg-type]
            )
        except Exception as exc:
            sampler_state = self._safe_sampler_state()
            state = "sampling_failed" if sampler_state == "failed" else "sampling"
            return self._failure(exc, state=state, observed=True)
        if sampling.state == "failed":
            return self._failure(
                "runtime sampler entered failed state",
                state="sampling_failed",
                observed=True,
            )
        return {
            "ok": True,
            "observed": True,
            "state": "sampling",
            "sampling": _status_dict(sampling),
        }

    def finalize(self, *, completed_at_s: float) -> dict[str, object]:
        if not _finite_number(completed_at_s):
            return self._failure("completed_at_s must be finite", state=self._state)
        if self._state == "applied" and self._last_result is not None:
            return dict(self._last_result)
        if self._sampler is None:
            return self._failure("no runtime sampling session", state=self._state)
        if self._state == "apply_failed" and self._candidate is not None:
            return self._apply(self._candidate, completed_at_s=float(completed_at_s))
        if self._state != "sampling":
            return self._failure(
                f"cannot finalize runtime binding in state {self._state}",
                state=self._state,
            )

        try:
            sampling = self._sampler.status(now_s=float(completed_at_s))
        except Exception as exc:
            return self._failure(exc, state="sampling")
        if sampling.state == "failed":
            return self._failure(
                "runtime sampler is failed", state="sampling_failed"
            )
        if not sampling.window_complete:
            return self._failure(
                "sampling window not yet complete", state="sampling"
            )

        try:
            candidate = self._sampler.finalize(
                completed_at_s=float(completed_at_s)
            )
        except Exception as exc:
            state = (
                "sampling_failed"
                if self._safe_sampler_state() == "failed"
                else "sampling"
            )
            return self._failure(exc, state=state)

        self._candidate = candidate
        self._state = "candidate_ready"
        self._last_error = None
        return self._apply(candidate, completed_at_s=float(completed_at_s))

    def cancel(self) -> dict[str, object]:
        if self._sampler is not None:
            try:
                self._sampler.reset()
            except Exception:
                # Cancellation still discards the owned sampler; it does not
                # claim that a state restore transaction succeeded.
                pass
        self._sampler = None
        self._profile = None
        self._profile_name = None
        self._candidate = None
        self._state = "idle"
        self._last_observed_at_s = None
        self._last_error = None
        self._last_result = None
        return {"ok": True, "state": "idle"}

    def _apply(
        self,
        candidate: RuntimeFieldBindingCandidate,
        *,
        completed_at_s: float,
    ) -> dict[str, object]:
        service_snapshot: object | None = None
        builder_snapshot: object | None = None
        try:
            service_snapshot = self._svc.snapshot()
        except Exception as exc:
            return self._transaction_failure(
                f"service snapshot failed: {exc}", service_snapshot, builder_snapshot
            )
        try:
            builder_snapshot = self._builder.snapshot_field_reference_state()
        except Exception as exc:
            return self._transaction_failure(
                f"builder snapshot failed: {exc}", service_snapshot, builder_snapshot
            )

        try:
            result = self._svc.apply_runtime_binding(
                candidate,
                profile_name=self._profile_name or "runtime",
                timestamp=completed_at_s,
            )
        except Exception as exc:
            return self._transaction_failure(
                f"service apply failed: {exc}", service_snapshot, builder_snapshot
            )
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            error = result.get("error", "service apply failed") if isinstance(result, Mapping) else "service apply returned invalid result"
            return self._transaction_failure(error, service_snapshot, builder_snapshot)

        try:
            builder_ok = self._builder.confirm_runtime_gps_reference(
                candidate, timestamp=completed_at_s
            )
        except Exception as exc:
            return self._transaction_failure(
                f"builder apply failed: {exc}", service_snapshot, builder_snapshot
            )
        if builder_ok is not True:
            return self._transaction_failure(
                "builder apply failed", service_snapshot, builder_snapshot
            )

        try:
            service_status = self._svc.status()
        except Exception as exc:
            return self._transaction_failure(
                f"service status before freeze failed: {exc}",
                service_snapshot,
                builder_snapshot,
            )
        try:
            synced = _synced(
                candidate, service_status, self._builder, require_frozen=False
            )
        except Exception as exc:
            return self._transaction_failure(
                f"sync before freeze failed: {exc}",
                service_snapshot,
                builder_snapshot,
            )
        if not synced:
            return self._transaction_failure(
                "sync verification before freeze failed",
                service_snapshot,
                builder_snapshot,
            )

        try:
            freeze_result = self._svc.freeze()
        except Exception as exc:
            return self._transaction_failure(
                f"service freeze failed: {exc}", service_snapshot, builder_snapshot
            )
        if not isinstance(freeze_result, Mapping) or freeze_result.get("ok") is not True:
            error = freeze_result.get("error", "service freeze failed") if isinstance(freeze_result, Mapping) else "service freeze returned invalid result"
            return self._transaction_failure(error, service_snapshot, builder_snapshot)

        try:
            frozen_status = self._svc.status()
        except Exception as exc:
            return self._transaction_failure(
                f"service status after freeze failed: {exc}",
                service_snapshot,
                builder_snapshot,
            )
        try:
            synced = _synced(
                candidate, frozen_status, self._builder, require_frozen=True
            )
        except Exception as exc:
            return self._transaction_failure(
                f"sync after freeze failed: {exc}",
                service_snapshot,
                builder_snapshot,
            )
        if not synced:
            return self._transaction_failure(
                "sync verification after freeze failed",
                service_snapshot,
                builder_snapshot,
            )

        self._state = "applied"
        self._last_error = None
        geometry = _geometry_payload(candidate.geometry)
        applied: dict[str, object] = {
            "ok": True,
            "state": "applied",
            "profile_id": candidate.profile_id,
            "synced_to_runtime": True,
            "is_frozen": True,
            "is_ready_for_field_to_gps": True,
            "is_ready_for_field_to_local": False,
            "origin_lat": candidate.origin_lat,
            "origin_lon": candidate.origin_lon,
            "forward_marker_lat": candidate.forward_marker_lat,
            "forward_marker_lon": candidate.forward_marker_lon,
            "field_heading_yaw_rad": candidate.field_heading_yaw_rad,
            "field_heading_deg": candidate.field_heading_deg,
            "baseline_m": candidate.baseline_m,
            "sample_count": candidate.sample_count,
            "horizontal_spread_m": candidate.horizontal_spread_m,
            "warnings": list(candidate.warnings),
            "geometry": geometry,
        }
        self._last_result = applied
        return dict(applied)

    def _transaction_failure(
        self,
        error: object,
        service_snapshot: object | None,
        builder_snapshot: object | None,
    ) -> dict[str, object]:
        rollback_ok = self._rollback(service_snapshot, builder_snapshot)
        return self._failure(
            error, state="apply_failed", rollback_ok=rollback_ok
        )

    def _rollback(
        self,
        service_snapshot: object,
        builder_snapshot: object,
    ) -> bool:
        service_ok = False
        builder_ok = False
        try:
            self._svc.restore(service_snapshot)  # type: ignore[arg-type]
            service_ok = True
        except Exception:
            service_ok = False
        try:
            builder_ok = (
                self._builder.restore_field_reference_state(  # type: ignore[arg-type]
                    builder_snapshot
                )
                is True
            )
        except Exception:
            builder_ok = False
        return service_ok and builder_ok

    @property
    def state(self) -> str:
        return self._state

    def synced_to_runtime(
        self,
        service_status: Mapping[str, object] | None = None,
        *,
        require_frozen: bool = True,
    ) -> bool:
        """Return full Service/Builder parity for the retained candidate."""
        if self._candidate is None:
            return False
        try:
            status = service_status if service_status is not None else self._svc.status()
            return _synced(
                self._candidate,
                status,
                self._builder,
                require_frozen=require_frozen,
            )
        except Exception:
            return False

    def _failure(
        self,
        error: object,
        *,
        state: str,
        rollback_ok: bool | None = None,
        observed: bool | None = None,
    ) -> dict[str, object]:
        self._state = state
        self._last_error = str(error)
        result: dict[str, object] = {
            "ok": False,
            "state": state,
            "error": str(error),
        }
        if rollback_ok is not None:
            result["rollback_ok"] = rollback_ok
        if observed is not None:
            result["observed"] = observed
        profile_id = (
            self._candidate.profile_id
            if self._candidate is not None
            else self._profile.profile_id if self._profile is not None else None
        )
        if profile_id is not None:
            result["profile_id"] = profile_id
        self._last_result = dict(result)
        return result

    def _safe_sampler_state(self) -> str | None:
        if self._sampler is None:
            return None
        try:
            return self._sampler.status(now_s=self._last_observed_at_s).state
        except Exception:
            return None

    def status(self, *, now_s: float | None = None) -> dict[str, object]:
        sampling: dict[str, object] | None = None
        if self._sampler is not None and self._state == "sampling":
            timestamp = now_s if now_s is not None else self._last_observed_at_s
            try:
                sampling = _status_dict(self._sampler.status(now_s=timestamp))
            except Exception as exc:
                sampling = {"state": "sampling", "error": str(exc)}

        candidate_summary: dict[str, object] | None = None
        geometry: dict[str, object] | None = None
        if self._candidate is not None:
            candidate_summary = {
                "origin_lat": self._candidate.origin_lat,
                "origin_lon": self._candidate.origin_lon,
                "forward_marker_lat": self._candidate.forward_marker_lat,
                "forward_marker_lon": self._candidate.forward_marker_lon,
                "field_heading_yaw_rad": self._candidate.field_heading_yaw_rad,
                "baseline_m": self._candidate.baseline_m,
                "sample_count": self._candidate.sample_count,
                "horizontal_spread_m": self._candidate.horizontal_spread_m,
            }
            geometry = _geometry_payload(self._candidate.geometry)

        return {
            "state": self._state,
            "profile_id": (
                self._candidate.profile_id
                if self._candidate is not None
                else self._profile.profile_id if self._profile is not None else None
            ),
            "profile_name": self._profile_name,
            "last_error": self._last_error,
            "candidate_ready": self._candidate is not None,
            "sampling": sampling,
            "candidate_summary": candidate_summary,
            "geometry": geometry,
            "last_result": dict(self._last_result) if self._last_result else None,
        }


def _synced(
    candidate: RuntimeFieldBindingCandidate,
    service_status: Mapping[str, object],
    builder: RuntimeContextBuilder,
    *,
    require_frozen: bool,
) -> bool:
    """Verify every runtime GPS binding field in both state owners."""
    if service_status.get("is_confirmed") is not True:
        return False
    if service_status.get("is_ready_for_field_to_gps") is not True:
        return False
    if service_status.get("is_ready_for_field_to_local") is not False:
        return False
    if service_status.get("origin_source") != candidate.origin_source:
        return False
    if service_status.get("heading_source") != candidate.heading_source:
        return False
    if service_status.get("profile_id") != candidate.profile_id:
        return False
    if require_frozen and service_status.get("is_frozen") is not True:
        return False
    for actual, expected in (
        (service_status.get("origin_lat"), candidate.origin_lat),
        (service_status.get("origin_lon"), candidate.origin_lon),
        (service_status.get("forward_marker_lat"), candidate.forward_marker_lat),
        (service_status.get("forward_marker_lon"), candidate.forward_marker_lon),
        (service_status.get("field_heading_yaw_rad"), candidate.field_heading_yaw_rad),
    ):
        if not _same_float(actual, expected):
            return False

    if builder.field_heading_confirmed is not True:
        return False
    if builder.field_origin_gps_confirmed is not True:
        return False
    if builder.field_origin_confirmed is not False:
        return False
    if builder.field_gps_transform_ready() is not True:
        return False
    if builder.field_transform_ready() is not False:
        return False
    for actual, expected in (
        (builder.field_heading_source, candidate.heading_source),
        (builder.field_reference_mode, candidate.field_reference_mode),
        (builder.field_runtime_profile_id, candidate.profile_id),
    ):
        if actual != expected:
            return False
    for actual, expected in (
        (builder.field_origin_lat, candidate.origin_lat),
        (builder.field_origin_lon, candidate.origin_lon),
        (builder.field_forward_marker_lat, candidate.forward_marker_lat),
        (builder.field_forward_marker_lon, candidate.forward_marker_lon),
        (builder.field_heading_yaw_rad, candidate.field_heading_yaw_rad),
        (builder.field_baseline_m, candidate.baseline_m),
        (builder.field_gps_sample_duration_s, candidate.sample_duration_s),
        (builder.field_gps_horizontal_spread_m, candidate.horizontal_spread_m),
        (builder.field_gps_eph, candidate.gps_eph),
        (builder.field_gps_epv, candidate.gps_epv),
    ):
        if not _same_float(actual, expected):
            return False
    for actual, expected in (
        (builder.field_gps_sample_count, candidate.sample_count),
        (builder.field_gps_rejected_sample_count, candidate.rejected_sample_count),
        (builder.field_gps_duplicate_sample_count, candidate.duplicate_sample_count),
        (builder.field_gps_fix_type, candidate.gps_fix_type),
        (builder.field_gps_satellites, candidate.gps_satellites),
    ):
        if not _same_int(actual, expected):
            return False
    return True


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _same_float(actual: object, expected: object) -> bool:
    return (
        _finite_number(actual)
        and _finite_number(expected)
        and math.isclose(
            float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9
        )
    )


def _same_int(actual: object, expected: object) -> bool:
    return (
        isinstance(actual, int)
        and not isinstance(actual, bool)
        and isinstance(expected, int)
        and not isinstance(expected, bool)
        and actual == expected
    )


def _status_dict(status: object) -> dict[str, object]:
    return {item.name: getattr(status, item.name) for item in fields(status)}


def _point_payload(point: RuntimeFieldPoint) -> dict[str, object]:
    return {
        "name": point.name,
        "field_x_m": point.field_x_m,
        "field_y_m": point.field_y_m,
        "altitude_m": point.altitude_m,
        "lat": point.lat,
        "lon": point.lon,
    }


def _geometry_payload(geometry: RuntimeFieldGeometry) -> dict[str, object]:
    return {
        "home": _point_payload(geometry.home),
        "forward_marker": _point_payload(geometry.forward_marker),
        "drop_scan_waypoints": [
            _point_payload(point) for point in geometry.drop_scan_waypoints
        ],
        "drop_area_corners": [
            _point_payload(point) for point in geometry.drop_area_corners
        ],
        "recce_area_corners": [
            _point_payload(point) for point in geometry.recce_area_corners
        ],
        "heading": {
            "yaw_rad": geometry.field_heading_yaw_rad,
            "degrees": geometry.field_heading_deg,
        },
        "baseline": geometry.baseline_m,
        "warnings": list(geometry.warnings),
    }
