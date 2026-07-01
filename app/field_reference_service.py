from __future__ import annotations

from typing import Any

from .field_reference import FieldReference, FieldReferenceError


class FieldReferenceService:
    """Lightweight business wrapper around :class:`FieldReference`.

    Every method returns a plain ``dict`` with at least an ``"ok"`` key so
    callers never need to catch exceptions.  The service operates on
    internal state only — it does **not** read from the flight controller,
    Web UI, LinkManager, or MAVLink.
    """

    def __init__(self, reference: FieldReference | None = None) -> None:
        self._ref = reference or FieldReference()

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
        return {"ok": True}

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the current reference state."""
        return {
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
