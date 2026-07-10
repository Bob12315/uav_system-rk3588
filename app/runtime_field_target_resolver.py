"""Runtime field target resolver.

Resolves Schema v3 runtime field geometry into GLOBAL GPS waypoint targets
(HOME, DROP_SCAN_1..4) suitable for ``GotoWaypointAction`` with
``target_frame=global``.

Reads the *frozen* ``FieldReference`` from ``FieldReferenceService`` and
rejects if readiness conditions are not met.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .field_profile import FieldProfile
from .field_reference import FieldReference
from .runtime_field_geometry import (
    RuntimeFieldGeometry,
    RuntimeFieldGeometryError,
    RuntimeFieldPoint,
    build_runtime_field_geometry,
)


# ---------------------------------------------------------------------------
# target DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GpsScanTarget:
    """A GLOBAL GPS waypoint target ready for flight dispatch."""

    name: str
    lat: float
    lon: float
    altitude_m: float
    yaw_mode: str = "hold"


# ---------------------------------------------------------------------------
# resolver
# ---------------------------------------------------------------------------


class RuntimeFieldTargetResolver:
    """Resolve HOME + DROP_SCAN_1..4 from a frozen runtime field reference.

    Usage::

        resolver = RuntimeFieldTargetResolver(profile, reference)
        home = resolver.home()
        scan_waypoints = resolver.scan_waypoints()   # tuple of 4

    All methods raise :exc:`RuntimeFieldTargetError` when the runtime
    state is not ready.
    """

    def __init__(
        self,
        profile: FieldProfile,
        reference: FieldReference,
    ) -> None:
        self._profile = profile
        self._reference = reference
        self._geometry: RuntimeFieldGeometry | None = None
        self._error: str | None = None

        if profile.schema_version != 3:
            self._error = "only schema v3 profiles are supported"
            return

        if not reference.is_confirmed:
            self._error = "field reference is not confirmed"
            return

        if not reference.is_frozen:
            self._error = "field reference is not frozen"
            return

        if not reference.is_ready_for_field_to_gps():
            self._error = "field reference is not ready for field→GPS conversion"
            return

        if reference.origin_source not in ("gps_marker", "manual_gps_input"):
            self._error = (
                f"origin_source must be gps_marker or manual_gps_input, "
                f"got {reference.origin_source!r}"
            )
            return

        if reference.origin_lat is None or reference.origin_lon is None:
            self._error = "origin GPS not set"
            return

        try:
            self._geometry = build_runtime_field_geometry(
                profile,
                origin_lat=reference.origin_lat,
                origin_lon=reference.origin_lon,
            )
        except RuntimeFieldGeometryError as exc:
            self._error = f"failed to build runtime geometry: {exc}"
            return

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._geometry is not None

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def geometry(self) -> RuntimeFieldGeometry:
        self._require_ready()
        return self._geometry  # type: ignore[return-value]

    def home(self) -> GpsScanTarget:
        """Return HOME as a GLOBAL GPS target (runtime origin A)."""
        self._require_ready()
        h = self._geometry.home  # type: ignore[union-attr]
        return GpsScanTarget(
            name="HOME",
            lat=h.lat,
            lon=h.lon,
            altitude_m=h.altitude_m,
            yaw_mode="hold",
        )

    def scan_waypoints(self) -> Tuple[GpsScanTarget, ...]:
        """Return DROP_SCAN_1..4 as GLOBAL GPS targets."""
        self._require_ready()
        return tuple(
            GpsScanTarget(
                name=p.name,
                lat=p.lat,
                lon=p.lon,
                altitude_m=p.altitude_m,
                yaw_mode="hold",
            )
            for p in self._geometry.drop_scan_waypoints  # type: ignore[union-attr]
        )

    def target_by_name(self, name: str) -> GpsScanTarget:
        """Resolve a named target (HOME, DROP_SCAN_1..4)."""
        self._require_ready()
        g = self._geometry  # type: ignore[union-attr]
        if name == "HOME":
            return self.home()
        for p in g.drop_scan_waypoints:
            if p.name == name:
                return GpsScanTarget(
                    name=p.name,
                    lat=p.lat,
                    lon=p.lon,
                    altitude_m=p.altitude_m,
                    yaw_mode="hold",
                )
        raise RuntimeFieldTargetError(f"unknown target: {name!r}")

    def as_action_dict(self, name: str) -> Dict[str, Any]:
        """Return a dict suitable for ``GotoWaypointAction.start()``.

        Produces::

            {
                "x": <lat>, "y": <lon>, "altitude_m": <alt>,
                "waypoint_mode": "absolute",
                "target_frame": "global",
                "yaw_mode": "hold",
            }
        """
        t = self.target_by_name(name)
        return {
            "x": t.lat,
            "y": t.lon,
            "altitude_m": t.altitude_m,
            "waypoint_mode": "absolute",
            "target_frame": "global",
            "yaw_mode": t.yaw_mode,
            "key": f"global_scan_{name}",
        }

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _require_ready(self) -> None:
        if not self.is_ready:
            raise RuntimeFieldTargetError(
                self._error or "runtime field target resolver not ready"
            )


class RuntimeFieldTargetError(RuntimeError):
    """Runtime field target resolution failed."""
