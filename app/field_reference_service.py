from __future__ import annotations

import time as _time
from dataclasses import dataclass, fields
from typing import Any, Optional

from .field_profile_service import BindResult
from .runtime_field_binding import RuntimeFieldBindingCandidate
from .field_reference import (
    FieldReference,
    FieldReferenceError,
    HeadingSource,
    OriginSource,
)


@dataclass(frozen=True, slots=True)
class FieldReferenceServiceSnapshot:
    """Complete rollback snapshot for a FieldReferenceService transaction."""

    reference_values: dict[str, Any]
    profile_id: Optional[str]
    profile_name: Optional[str]


class FieldReferenceService:
    """Lightweight business wrapper around :class:`FieldReference`.

    Every method returns a plain ``dict`` with at least an ``"ok"`` key so
    callers never need to catch exceptions.  The service operates on
    internal state only — it does **not** read from the flight controller,
    Web UI, LinkManager, or MAVLink.

    Centerline-only: the only way to populate the reference is via
    ``apply_profile_binding`` with a centerline ``BindResult``.
    """

    def __init__(self, reference: FieldReference | None = None) -> None:
        self._ref = reference or FieldReference()
        self._profile_id: Optional[str] = None
        self._profile_name: Optional[str] = None

    @property
    def reference(self) -> FieldReference:
        return self._ref

    def snapshot(self) -> FieldReferenceServiceSnapshot:
        """Capture reference fields and service-owned profile metadata."""
        return FieldReferenceServiceSnapshot(
            reference_values={
                item.name: getattr(self._ref, item.name)
                for item in fields(FieldReference)
            },
            profile_id=self._profile_id,
            profile_name=self._profile_name,
        )

    def restore(self, snapshot: FieldReferenceServiceSnapshot) -> None:
        """Restore a snapshot after a failed apply/sync transaction."""
        if not isinstance(snapshot, FieldReferenceServiceSnapshot):
            raise TypeError("snapshot must be FieldReferenceServiceSnapshot")
        for name, value in snapshot.reference_values.items():
            setattr(self._ref, name, value)
        self._profile_id = snapshot.profile_id
        self._profile_name = snapshot.profile_name

    # ------------------------------------------------------------------
    # profile binding (centerline only)
    # ------------------------------------------------------------------

    def apply_profile_binding(
        self,
        bind_result: BindResult,
        profile_id: str,
        profile_name: str,
        anchor_lat: float,
        anchor_lon: float,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Atomically apply a centerline profile bind result to this field reference.

        Rejected if the reference is already frozen or the bind result is
        not ``ok``.  On success the reference is marked confirmed with
        PROFILE_CENTERLINE / PROFILE_GPS_CENTERLINE sources.
        """
        if self._ref.is_frozen:
            return {"ok": False, "error": "field reference is frozen"}
        if not bind_result.ok:
            return {"ok": False, "error": "bind result is not ok",
                    "errors": list(bind_result.errors)}

        ts = timestamp if timestamp is not None else _time.time()

        # Write all fields atomically.
        self._ref.origin_source = OriginSource.PROFILE_CENTERLINE.value
        self._ref.heading_source = HeadingSource.PROFILE_GPS_CENTERLINE.value
        self._ref.origin_lat = anchor_lat
        self._ref.origin_lon = anchor_lon
        self._ref.forward_marker_lat = None
        self._ref.forward_marker_lon = None
        self._ref.origin_local_n_m = bind_result.origin_local_n_m
        self._ref.origin_local_e_m = bind_result.origin_local_e_m
        self._ref.origin_local_z_m = bind_result.origin_local_z_m
        self._ref.field_heading_yaw_rad = bind_result.field_heading_yaw_rad
        self._ref.is_confirmed = True
        self._ref.confirmed_at_s = ts

        self._profile_id = profile_id
        self._profile_name = profile_name

        return {"ok": True}

    # ------------------------------------------------------------------
    # runtime binding (5B.1)
    # ------------------------------------------------------------------

    def apply_runtime_binding(
        self,
        candidate: RuntimeFieldBindingCandidate,
        *,
        profile_name: str,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Apply a validated runtime GPS sampling candidate.

        Sets a confirmed GPS-only FieldReference.  Clears LOCAL_NED origin
        fields.  Does NOT freeze.
        """
        if self._ref.is_frozen:
            return {"ok": False, "error": "field reference is frozen"}

        # ── validate candidate ──────────────────────────────────────
        errs = self._validate_runtime_candidate(candidate)
        if errs:
            return {"ok": False, "error": "invalid candidate", "errors": errs}

        if not isinstance(profile_name, str) or not profile_name.strip():
            return {"ok": False, "error": "profile_name must be a non-empty string"}

        ts = timestamp if timestamp is not None else candidate.completed_at_s
        if not (isinstance(ts, (int, float)) and not isinstance(ts, bool) and __import__('math').isfinite(float(ts))):
            return {"ok": False, "error": f"timestamp must be finite, got {ts!r}"}

        # ── write ──────────────────────────────────────────────────
        self._ref.origin_source = candidate.origin_source
        self._ref.heading_source = candidate.heading_source
        self._ref.origin_lat = candidate.origin_lat
        self._ref.origin_lon = candidate.origin_lon
        self._ref.forward_marker_lat = candidate.forward_marker_lat
        self._ref.forward_marker_lon = candidate.forward_marker_lon
        self._ref.field_heading_yaw_rad = FieldReference._normalize_yaw(candidate.field_heading_yaw_rad)
        self._ref.origin_local_n_m = None
        self._ref.origin_local_e_m = None
        self._ref.origin_local_z_m = None
        self._ref.is_confirmed = True
        self._ref.confirmed_at_s = ts

        self._profile_id = candidate.profile_id
        self._profile_name = profile_name.strip()

        return {
            "ok": True,
            "profile_id": candidate.profile_id,
            "is_ready": self._ref.is_ready(),
            "is_ready_for_field_to_local": self._ref.is_ready_for_field_to_local(),
            "is_ready_for_field_to_gps": self._ref.is_ready_for_field_to_gps(),
            "is_frozen": self._ref.is_frozen,
        }

    @staticmethod
    def _validate_runtime_candidate(candidate: object) -> list[str]:
        m = __import__('math')
        i = __import__('itertools')
        errs: list[str] = []

        from .runtime_field_binding import RuntimeFieldBindingCandidate as RC
        from .runtime_field_geometry import RuntimeFieldGeometry
        from .field_reference import (
            HeadingSource, OriginSource, FieldReference,
        )

        if not isinstance(candidate, RC):
            return [f"candidate must be RuntimeFieldBindingCandidate, got {type(candidate).__name__}"]

        # fixed source values
        if candidate.origin_source != OriginSource.RUNTIME_CURRENT_GPS.value:
            errs.append(f"origin_source must be runtime_current_gps, got {candidate.origin_source!r}")
        if candidate.heading_source != HeadingSource.RUNTIME_FORWARD_MARKER.value:
            errs.append(f"heading_source must be runtime_forward_marker, got {candidate.heading_source!r}")
        if candidate.field_reference_mode != "runtime_origin_forward_marker":
            errs.append(f"field_reference_mode must be runtime_origin_forward_marker, got {candidate.field_reference_mode!r}")

        for label in ("profile_id", "origin_source", "heading_source", "field_reference_mode"):
            val = getattr(candidate, label, "")
            if not isinstance(val, str) or not val.strip():
                errs.append(f"{label} must be a non-empty string, got {val!r}")

        # lat/lon
        for name in ("origin_lat", "origin_lon", "forward_marker_lat", "forward_marker_lon"):
            v = getattr(candidate, name)
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and m.isfinite(float(v))):
                errs.append(f"{name} must be a finite number, got {v!r}")
                continue
            fv = float(v)
            if name.endswith("_lat") and (fv < -90.0 or fv > 90.0):
                errs.append(f"{name} {fv} out of range [-90, 90]")
            if name.endswith("_lon") and (fv < -180.0 or fv > 180.0):
                errs.append(f"{name} {fv} out of range [-180, 180]")
        if not errs:
            if abs(m.cos(m.radians(float(candidate.origin_lat)))) < 1e-9:
                errs.append("origin latitude too close to pole")

        # heading
        hdg = candidate.field_heading_yaw_rad
        if not (isinstance(hdg, (int, float)) and not isinstance(hdg, bool) and m.isfinite(float(hdg))):
            errs.append(f"field_heading_yaw_rad must be finite, got {hdg!r}")
        else:
            normalized = FieldReference._normalize_yaw(float(hdg))
            if abs(float(hdg) - normalized) > 1e-10 and abs(float(hdg) - normalized) < 6.28:
                pass  # close enough
        hdg_deg = candidate.field_heading_deg
        if not (isinstance(hdg_deg, (int, float)) and not isinstance(hdg_deg, bool) and m.isfinite(float(hdg_deg))):
            errs.append(f"field_heading_deg must be finite, got {hdg_deg!r}")
        else:
            expected_deg = m.degrees(float(hdg)) if not errs else None
            if expected_deg is not None and not m.isclose(float(hdg_deg), expected_deg, rel_tol=1e-9, abs_tol=1e-9):
                errs.append(f"field_heading_deg {hdg_deg} inconsistent with yaw_rad {hdg}")

        # baseline
        bl = candidate.baseline_m
        if not (isinstance(bl, (int, float)) and not isinstance(bl, bool) and m.isfinite(float(bl))) or float(bl) <= 0.0:
            errs.append(f"baseline_m must be finite > 0, got {bl!r}")

        # sample diagnostics
        for int_fld in ("sample_count", "rejected_sample_count", "duplicate_sample_count"):
            v = getattr(candidate, int_fld)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                errs.append(f"{int_fld} must be integer >= 0, got {v!r}")
        if candidate.sample_count < 1:
            errs.append(f"sample_count must be >= 1, got {candidate.sample_count}")

        # timing
        for fname in ("started_at_s", "completed_at_s", "sample_duration_s", "horizontal_spread_m"):
            v = getattr(candidate, fname)
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and m.isfinite(float(v))):
                errs.append(f"{fname} must be finite, got {v!r}")
        if not errs:
            if float(candidate.completed_at_s) < float(candidate.started_at_s):
                errs.append("completed_at_s < started_at_s")
            if not m.isclose(float(candidate.sample_duration_s), float(candidate.completed_at_s) - float(candidate.started_at_s), rel_tol=1e-9, abs_tol=1e-9):
                errs.append("sample_duration_s inconsistent with started/completed")

        # GPS quality
        for int_fld in ("gps_fix_type", "gps_satellites"):
            v = getattr(candidate, int_fld)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                errs.append(f"{int_fld} must be integer >= 0, got {v!r}")
        for f_fld in ("gps_eph", "gps_epv"):
            v = getattr(candidate, f_fld)
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and m.isfinite(float(v))) or float(v) < 0:
                errs.append(f"{f_fld} must be finite >= 0, got {v!r}")

        # geometry
        g = candidate.geometry
        if not isinstance(g, RuntimeFieldGeometry):
            errs.append(f"geometry must be RuntimeFieldGeometry, got {type(g).__name__}")
        else:
            if g.profile_id != candidate.profile_id:
                errs.append(f"geometry.profile_id {g.profile_id!r} != candidate.profile_id {candidate.profile_id!r}")
            if not m.isclose(g.origin_lat, float(candidate.origin_lat), rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry.origin_lat {g.origin_lat} != candidate.origin_lat {candidate.origin_lat}")
            if not m.isclose(g.origin_lon, float(candidate.origin_lon), rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry.origin_lon {g.origin_lon} != candidate.origin_lon {candidate.origin_lon}")
            if not m.isclose(g.forward_marker_lat, float(candidate.forward_marker_lat), rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry forward marker lat mismatch")
            if not m.isclose(g.forward_marker_lon, float(candidate.forward_marker_lon), rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry forward marker lon mismatch")
            if not m.isclose(g.field_heading_yaw_rad, float(hdg), rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry heading mismatch")
            if not m.isclose(g.baseline_m, float(bl), rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry baseline mismatch")

        # warnings
        if not isinstance(candidate.warnings, tuple):
            errs.append("warnings must be a tuple")
        elif candidate.warnings != g.warnings:
            errs.append("candidate.warnings != geometry.warnings")

        return errs

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def freeze(self) -> dict[str, Any]:
        """Freeze the confirmed reference."""
        try:
            self._ref.freeze()
        except FieldReferenceError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def reset(self) -> dict[str, Any]:
        """Reset the reference to its initial unconfirmed, unfrozen state."""
        self._ref.reset()
        self._profile_id = None
        self._profile_name = None
        return {"ok": True}

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the current reference state."""
        result: dict[str, Any] = {
            "is_confirmed": self._ref.is_confirmed,
            "is_frozen": self._ref.is_frozen,
            "is_ready": self._ref.is_ready(),
            "is_ready_for_field_to_local": self._ref.is_ready_for_field_to_local(),
            "is_ready_for_field_to_gps": self._ref.is_ready_for_field_to_gps(),
            "origin_source": self._ref.origin_source,
            "heading_source": self._ref.heading_source,
            "origin_local_n_m": self._ref.origin_local_n_m,
            "origin_local_e_m": self._ref.origin_local_e_m,
            "origin_local_z_m": self._ref.origin_local_z_m,
            "origin_lat": self._ref.origin_lat,
            "origin_lon": self._ref.origin_lon,
            "forward_marker_lat": self._ref.forward_marker_lat,
            "forward_marker_lon": self._ref.forward_marker_lon,
            "field_heading_yaw_rad": self._ref.field_heading_yaw_rad,
            "confirmed_at_s": self._ref.confirmed_at_s,
        }
        if self._ref.origin_source in (
            OriginSource.PROFILE_GPS_BOUND.value,
            OriginSource.PROFILE_CENTERLINE.value,
            OriginSource.RUNTIME_CURRENT_GPS.value,
        ):
            result["profile_id"] = self._profile_id
            result["profile_name"] = self._profile_name
        return result
