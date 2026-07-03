from __future__ import annotations

import time as _time
from typing import Any, Optional

from .field_profile_service import BindResult
from .field_reference import (
    FieldReference,
    FieldReferenceError,
    HeadingSource,
    OriginSource,
)


class FieldReferenceService:
    """Lightweight business wrapper around :class:`FieldReference`.

    Every method returns a plain ``dict`` with at least an ``"ok"`` key so
    callers never need to catch exceptions.  The service operates on
    internal state only — it does **not** read from the flight controller,
    Web UI, LinkManager, or MAVLink.
    """

    def __init__(self, reference: FieldReference | None = None) -> None:
        self._ref = reference or FieldReference()
        self._profile_id: Optional[str] = None
        self._profile_name: Optional[str] = None

    @property
    def reference(self) -> FieldReference:
        return self._ref

    # ------------------------------------------------------------------
    # marker / setter wrappers
    # ------------------------------------------------------------------

    def mark_local_origin(self, north_m: float, east_m: float) -> dict[str, Any]:
        """Record the LOCAL_NED origin from the drone's current position."""
        try:
            self._ref.set_origin_local_position(north_m, east_m)
        except FieldReferenceError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def mark_gps_origin(
        self,
        lat: float,
        lon: float,
        *,
        local_n_m: float | None = None,
        local_e_m: float | None = None,
        local_z_m: float | None = None,
    ) -> dict[str, Any]:
        """Record the GPS origin point (marker A).

        If *local_n_m* and *local_e_m* are provided they are stored as a
        LOCAL_NED snapshot so the reference can service FIELD <-> LOCAL_NED
        transforms.  Without them the GPS point is stored but
        ``is_ready()`` remains ``False``.
        """
        try:
            if local_n_m is not None and local_e_m is not None:
                self._ref.set_origin_gps_with_local_snapshot(
                    lat, lon, local_n_m, local_e_m, local_z_m=local_z_m,
                )
            else:
                self._ref.set_origin_gps(lat, lon)
        except FieldReferenceError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def mark_gps_forward(self, lat: float, lon: float) -> dict[str, Any]:
        """Record the GPS forward marker (marker B) and select
        ``gps_two_point`` heading source."""
        try:
            self._ref.set_forward_marker(lat, lon)
            self._ref.set_gps_two_point_heading()
        except FieldReferenceError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def set_compass_heading(self, yaw_rad: float) -> dict[str, Any]:
        """Set heading from the drone compass yaw."""
        try:
            self._ref.set_compass_heading(yaw_rad)
        except FieldReferenceError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def set_manual_heading(self, yaw_rad: float) -> dict[str, Any]:
        """Set heading from a user-supplied angle."""
        try:
            self._ref.set_manual_heading(yaw_rad)
        except FieldReferenceError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def set_manual_origin(self, lat: float, lon: float) -> dict[str, Any]:
        """Set origin from user-supplied GPS coordinates."""
        try:
            self._ref.set_origin_manual_gps(lat, lon)
        except FieldReferenceError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    # ------------------------------------------------------------------
    # profile binding
    # ------------------------------------------------------------------

    def apply_profile_binding(
        self,
        bind_result: BindResult,
        profile_id: str,
        profile_name: str,
        origin_lat: float,
        origin_lon: float,
        forward_lat: float,
        forward_lon: float,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Atomically apply a profile bind result to this field reference.

        Rejected if the reference is already frozen or the bind result is
        not ``ok``.  On success the reference is marked confirmed.
        """
        if self._ref.is_frozen:
            return {"ok": False, "error": "field reference is frozen"}
        if not bind_result.ok:
            return {"ok": False, "error": "bind result is not ok",
                    "errors": list(bind_result.errors)}

        ts = timestamp if timestamp is not None else _time.time()

        # Write all fields atomically (bypass individual setter guards
        # since we already checked is_frozen above).
        self._ref.origin_source = OriginSource.PROFILE_GPS_BOUND.value
        self._ref.heading_source = HeadingSource.PROFILE_GPS_TWO_POINT.value
        self._ref.origin_lat = origin_lat
        self._ref.origin_lon = origin_lon
        self._ref.forward_marker_lat = forward_lat
        self._ref.forward_marker_lon = forward_lon
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
    # lifecycle
    # ------------------------------------------------------------------

    def confirm(self) -> dict[str, Any]:
        """Validate and confirm the reference.

        Returns ``{"ok": True, "warnings": [...]}`` on success, or
        ``{"ok": False, "error": "..."}`` on hard validation failure.
        """
        ok, warnings = self._ref.confirm_with_warnings()
        if not ok:
            return {"ok": False, "error": warnings[0] if warnings else "confirm failed"}
        return {"ok": True, "warnings": warnings}

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
        if self._ref.origin_source == OriginSource.PROFILE_GPS_BOUND.value:
            result["profile_id"] = self._profile_id
            result["profile_name"] = self._profile_name
        return result
