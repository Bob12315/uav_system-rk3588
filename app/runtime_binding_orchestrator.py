"""Runtime binding orchestration — Controller-level lifecycle (step 5B.2).

Integrates RuntimeFieldBindingSampler, FieldReferenceService, and
RuntimeContextBuilder into atomic transactions with sync verification,
freeze, and rollback.
"""

from __future__ import annotations

import json
import math
from typing import Any, Optional

from .field_profile import (
    FieldProfile,
    load_field_profile_json,
)
from .field_reference_service import FieldReferenceService
from .runtime_context import RuntimeContextBuilder
from .runtime_field_binding import (
    RuntimeFieldBindingCandidate,
    RuntimeFieldBindingError,
    RuntimeFieldBindingSampler,
)


class RuntimeBindingOrchestrator:
    """Manages the full runtime GPS binding lifecycle.

    Owns the sampler, orchestrates atomic dual-apply with sync
    verification, freeze, and rollback.  Does not access Web UI,
    flight commands, or system time directly — all timestamps are caller-supplied.
    """

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
        self._state: str = "idle"  # idle|sampling|applied|apply_failed|sampling_failed
        self._last_error: str | None = None
        self._last_result: dict[str, object] | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(
        self, profile: FieldProfile, *, started_at_s: float
    ) -> dict[str, object]:
        """Begin a new runtime GPS sampling session."""
        if not (
            isinstance(started_at_s, (int, float))
            and not isinstance(started_at_s, bool)
            and math.isfinite(float(started_at_s))
        ):
            return _fail("started_at_s must be a finite number", self._state)
        if self._svc.reference.is_frozen:
            return _fail("field reference is frozen", self._state)
        if profile.schema_version != 3:
            return _fail("runtime GPS sampling requires schema v3", self._state)

        try:
            sampler = RuntimeFieldBindingSampler(profile)
        except RuntimeFieldBindingError as exc:
            return _fail(str(exc), self._state)

        status = sampler.start(started_at_s=started_at_s)
        self._sampler = sampler
        self._profile = profile
        self._profile_name = profile.name
        self._candidate = None
        self._state = "sampling"
        self._last_error = None
        self._last_result = None
        return {
            "ok": True, "profile_id": profile.profile_id,
            "state": "sampling",
            "sampling": _status_dict(status),
        }

    def observe(
        self, snapshot: object, *, observed_at_s: float
    ) -> dict[str, object]:
        """Feed one drone-state snapshot into the active sampling session."""
        if self._sampler is None or self._state != "sampling":
            return {"ok": True, "observed": False, "state": self._state}
        try:
            status = self._sampler.observe_snapshot(
                snapshot, observed_at_s=observed_at_s
            )
        except RuntimeFieldBindingError as exc:
            self._state = "sampling_failed"
            self._last_error = str(exc)
            return {"ok": False, "observed": True, "state": "sampling_failed", "error": str(exc)}
        return {
            "ok": True, "observed": True, "state": "sampling",
            "sampling": _status_dict(status),
        }

    def cancel(self) -> dict[str, object]:
        """Cancel the current sampling session."""
        if self._sampler is not None:
            self._sampler.reset()
        self._sampler = None
        self._profile = None
        self._profile_name = None
        self._candidate = None
        self._state = "idle"
        self._last_error = None
        self._last_result = None
        return {"ok": True, "state": "idle"}

    def finalize(
        self, *, completed_at_s: float
    ) -> dict[str, object]:
        """Finalize sampling and apply as an atomic transaction."""
        if not (
            isinstance(completed_at_s, (int, float))
            and not isinstance(completed_at_s, bool)
            and math.isfinite(float(completed_at_s))
        ):
            return _fail("completed_at_s must be finite", self._state)

        # Idempotent — already applied
        if self._state == "applied" and self._last_result is not None:
            return dict(self._last_result)

        if self._sampler is None:
            return _fail("no runtime sampling session", self._state)

        # Retry with stored candidate
        if self._state == "apply_failed" and self._candidate is not None:
            return self._apply(self._candidate, completed_at_s=float(completed_at_s))

        # Finalize sampler
        try:
            candidate = self._sampler.finalize(completed_at_s=float(completed_at_s))
        except RuntimeFieldBindingError as exc:
            err = str(exc)
            if "samples" in err.lower() or "spread" in err.lower() or "baseline" in err.lower():
                self._state = "sampling_failed"
                self._last_error = err
            return _fail(err, self._state)

        return self._apply(candidate, completed_at_s=float(completed_at_s))

    # ------------------------------------------------------------------
    # transaction
    # ------------------------------------------------------------------

    def _apply(
        self, candidate: RuntimeFieldBindingCandidate, *, completed_at_s: float
    ) -> dict[str, object]:
        svc_snap = self._svc.snapshot()
        bld_snap = self._builder.snapshot_field_reference_state()

        # 1 — Service
        r = self._svc.apply_runtime_binding(
            candidate, profile_name=self._profile_name or "runtime",
            timestamp=completed_at_s,
        )
        if not r.get("ok"):
            self._rollback(svc_snap, bld_snap, candidate)
            return _fail(r.get("error", "service apply failed"), "apply_failed")

        # 2 — Builder
        if not self._builder.confirm_runtime_gps_reference(candidate, timestamp=completed_at_s):
            self._rollback(svc_snap, bld_snap, candidate)
            return _fail("builder apply failed", "apply_failed")

        # 3 — Sync before freeze
        if not _synced(candidate, self._svc.status(), self._builder, require_frozen=False):
            self._rollback(svc_snap, bld_snap, candidate)
            return _fail("sync verification failed", "apply_failed")

        # 4 — Freeze
        fr = self._svc.freeze()
        if not fr.get("ok"):
            self._rollback(svc_snap, bld_snap, candidate)
            return _fail("freeze failed", "apply_failed")

        # 5 — Sync after freeze
        if not _synced(candidate, self._svc.status(), self._builder, require_frozen=True):
            self._rollback(svc_snap, bld_snap, candidate)
            return _fail("post-freeze sync verification failed", "apply_failed")

        # Success
        self._candidate = candidate
        self._state = "applied"
        self._last_error = None
        result = {
            "ok": True, "state": "applied", "profile_id": candidate.profile_id,
            "synced_to_runtime": True, "is_frozen": True,
            "is_ready_for_field_to_gps": True, "is_ready_for_field_to_local": False,
            "origin_lat": candidate.origin_lat, "origin_lon": candidate.origin_lon,
            "forward_marker_lat": candidate.forward_marker_lat,
            "forward_marker_lon": candidate.forward_marker_lon,
            "field_heading_yaw_rad": candidate.field_heading_yaw_rad,
            "field_heading_deg": candidate.field_heading_deg,
            "baseline_m": candidate.baseline_m,
            "sample_count": candidate.sample_count,
            "horizontal_spread_m": candidate.horizontal_spread_m,
            "warnings": list(candidate.warnings),
        }
        self._last_result = result
        return result

    def _rollback(
        self,
        svc_snap: object,
        bld_snap: object,
        candidate: RuntimeFieldBindingCandidate,
    ) -> None:
        try:
            self._svc.restore(svc_snap)
        except Exception:
            pass
        try:
            self._builder.restore_field_reference_state(bld_snap)
        except Exception:
            pass
        self._state = "apply_failed"
        self._candidate = candidate

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def _failure(self, error: object, *, state: str, rollback_ok: bool | None = None) -> dict[str, object]:
        self._state = state
        self._last_error = str(error)
        result: dict[str, object] = {"ok": False, "state": state, "error": str(error)}
        if rollback_ok is not None:
            result["rollback_ok"] = rollback_ok
        if self._candidate is not None:
            result["profile_id"] = self._candidate.profile_id
        self._last_result = result
        return result

    def status(self, *, now_s: float | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "state": self._state,
            "profile_id": self._candidate.profile_id if self._candidate else self._profile.profile_id if self._profile else None,
            "profile_name": self._profile_name,
            "last_error": self._last_error,
            "candidate_ready": self._candidate is not None,
        }
        if self._sampler is not None and self._state in ("sampling", "candidate_ready"):
            try:
                ts = now_s if now_s is not None else self._last_observed_at_s
                if ts is not None:
                    result["sampling"] = _status_dict(self._sampler.status(now_s=ts))
                else:
                    result["sampling"] = _status_dict(self._sampler.status())
            except Exception:
                pass
        if self._candidate is not None:
            result["candidate_summary"] = {
                "origin_lat": self._candidate.origin_lat, "origin_lon": self._candidate.origin_lon,
                "sample_count": self._candidate.sample_count, "baseline_m": self._candidate.baseline_m,
            }
        return result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _synced(
    candidate: RuntimeFieldBindingCandidate,
    svc_status: dict[str, object],
    builder: RuntimeContextBuilder,
    *,
    require_frozen: bool,
) -> bool:
    try:
        m = __import__('math')
        if not svc_status.get("is_confirmed"): return False
        if not svc_status.get("is_ready_for_field_to_gps"): return False
        if svc_status.get("origin_source") != "runtime_current_gps": return False
        if require_frozen and not svc_status.get("is_frozen"): return False
        if not builder.field_heading_confirmed: return False
        if not builder.field_origin_gps_confirmed: return False
        if builder.field_origin_confirmed: return False
        for cv, bv in ((candidate.origin_lat, builder.field_origin_lat), (candidate.origin_lon, builder.field_origin_lon)):
            if bv is None: return False
            if not m.isfinite(float(bv)): return False
            if not m.isclose(float(cv), float(bv), rel_tol=1e-9, abs_tol=1e-9): return False
        return True
    except Exception:
        return False

def _status_dict(status: object) -> dict[str, object]:
    """Convert a slotted dataclass to a dict (handles slots=True)."""
    from dataclasses import fields as _flds
    result: dict[str, object] = {}
    for fld in _flds(status.__class__):
        result[fld.name] = getattr(status, fld.name)
    return result


def _fail(error: str, state: str) -> dict[str, object]:
    return {"ok": False, "error": error, "state": state}
