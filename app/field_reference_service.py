from __future__ import annotations

import math
import time as _time
from dataclasses import dataclass, fields
from typing import Any, Optional

from .field_profile_service import BindResult
from .runtime_field_binding import (
    RuntimeFieldBindingCandidate,
    validate_runtime_field_binding_candidate,
)
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

    References can be populated by legacy centerline binding or by a validated
    runtime GPS binding candidate.
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
        if not (isinstance(ts, (int, float)) and not isinstance(ts, bool) and math.isfinite(float(ts))):
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
        return list(validate_runtime_field_binding_candidate(candidate))

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
