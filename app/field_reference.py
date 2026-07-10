from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_M = 6371000.0
MIN_GPS_BASELINE_M = 5.0
RECOMMENDED_GPS_BASELINE_M = 10.0
WGS84_POLE_COS_EPS = 1e-9


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------

class OriginSource(str, Enum):
    LOCAL_POSITION = "local_position"          # internal compatibility only
    GPS_MARKER = "gps_marker"                  # deprecated — not API-reachable
    MANUAL_GPS_INPUT = "manual_gps_input"      # deprecated — not API-reachable
    PROFILE_GPS_BOUND = "profile_gps_bound"    # deprecated — replaced by PROFILE_CENTERLINE
    PROFILE_CENTERLINE = "profile_centerline"  # current — centerline profile binding
    RUNTIME_CURRENT_GPS = "runtime_current_gps"  # step 4+ — dynamic origin from stationary GPS samples


class HeadingSource(str, Enum):
    COMPASS_YAW = "compass_yaw"                    # deprecated — not API-reachable
    GPS_TWO_POINT = "gps_two_point"                # deprecated — not API-reachable
    MANUAL_ANGLE = "manual_angle"                  # deprecated — not API-reachable
    PROFILE_GPS_TWO_POINT = "profile_gps_two_point"  # deprecated — replaced by PROFILE_GPS_CENTERLINE
    PROFILE_GPS_CENTERLINE = "profile_gps_centerline"  # current — centerline profile heading
    RUNTIME_FORWARD_MARKER = "runtime_forward_marker"  # step 4+ — A→B heading from dynamic origin to forward marker


# ---------------------------------------------------------------------------
# exception
# ---------------------------------------------------------------------------

class FieldReferenceError(Exception):
    """Raised when a FieldReference operation is invalid."""


# ---------------------------------------------------------------------------
# lightweight GPS marker
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class GpsMarker:
    lat: float
    lon: float


# ---------------------------------------------------------------------------
# FieldReference
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FieldReference:
    """Pure-data field reference with validation and lifecycle methods.

    Coordinates use the conventions from ``docs/reference/coordinate_frames.md``:

    * LOCAL_NED: ``north_m`` / ``east_m`` / ``z_down_m``
    * FIELD:     ``field_x_m`` (+X = right) / ``field_y_m`` (+Y = forward)
    """

    is_confirmed: bool = False
    is_frozen: bool = False

    origin_source: Optional[str] = None
    heading_source: Optional[str] = None

    # LOCAL_NED origin (required for field_to_local_ned)
    origin_local_n_m: Optional[float] = None
    origin_local_e_m: Optional[float] = None
    origin_local_z_m: Optional[float] = None  # stored for status display, not used in XY transform

    # GPS origin (for gps_marker / manual_gps_input sources)
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None

    # GPS forward marker (for gps_two_point heading)
    forward_marker_lat: Optional[float] = None
    forward_marker_lon: Optional[float] = None

    # FIELD +Y heading in LOCAL_NED, normalized to (-pi, pi]
    field_heading_yaw_rad: Optional[float] = None

    # Unix timestamp of last successful confirm()
    confirmed_at_s: Optional[float] = None

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_yaw(yaw_rad: float) -> float:
        """Normalize *yaw_rad* to (-pi, pi].

        Maps ``-pi`` to ``+pi`` so the range is truly half-open at the
        negative end.
        """
        yaw = math.atan2(math.sin(yaw_rad), math.cos(yaw_rad))
        # atan2(sin(-pi), cos(-pi)) may return -pi due to floating-point
        # artifacts; force it to +pi for a clean (-pi, pi] range.
        if yaw <= -math.pi + 1e-15:
            return math.pi
        return yaw

    def _guard_confirmed(self) -> None:
        if not self.is_confirmed:
            raise FieldReferenceError("FieldReference is not confirmed")

    def _guard_not_frozen(self) -> None:
        if self.is_frozen:
            raise FieldReferenceError(
                "FieldReference is frozen; reset before modifying"
            )

    # ------------------------------------------------------------------
    # readiness
    # ------------------------------------------------------------------

    def is_ready_for_field_to_local(self) -> bool:
        """True when ready for FIELD ↔ LOCAL_NED transforms."""
        return (
            self.is_confirmed
            and self.origin_local_n_m is not None
            and self.origin_local_e_m is not None
            and self.field_heading_yaw_rad is not None
            and math.isfinite(self.origin_local_n_m)
            and math.isfinite(self.origin_local_e_m)
            and math.isfinite(self.field_heading_yaw_rad)
        )

    def is_ready_for_field_to_gps(self) -> bool:
        """True when ready for FIELD → GLOBAL GPS transforms.

        Requires confirmed reference, WGS84 origin, and heading.
        Does NOT require LOCAL_NED origin or forward marker.
        Defensively handles non-finite / non-numeric field values.
        """
        if not self.is_confirmed:
            return False

        origin_lat = self.origin_lat
        origin_lon = self.origin_lon
        heading = self.field_heading_yaw_rad

        if any(v is None for v in (origin_lat, origin_lon, heading)):
            return False

        if any(isinstance(v, bool) for v in (origin_lat, origin_lon, heading)):
            return False

        try:
            lat = float(origin_lat)
            lon = float(origin_lon)
            hdg = float(heading)
        except (TypeError, ValueError):
            return False

        if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(hdg)):
            return False

        if not -90.0 <= lat <= 90.0:
            return False

        if not -180.0 <= lon <= 180.0:
            return False

        if abs(math.cos(math.radians(lat))) <= WGS84_POLE_COS_EPS:
            return False

        return True

    def is_ready(self) -> bool:
        """Backward-compatible alias for FIELD ↔ LOCAL_NED readiness."""
        return self.is_ready_for_field_to_local()

    # ------------------------------------------------------------------
    # setters  (each checks the frozen guard)
    # ------------------------------------------------------------------

    def set_origin_local_position(self, north_m: float, east_m: float) -> None:
        self._guard_not_frozen()
        self.origin_source = OriginSource.LOCAL_POSITION.value
        self.origin_local_n_m = float(north_m)
        self.origin_local_e_m = float(east_m)

    def set_origin_gps(self, lat: float, lon: float) -> None:
        """Record the GPS origin point (marker A).

        This sets the geographic reference only.  Without a LOCAL_NED
        snapshot the reference cannot service FIELD <-> LOCAL_NED
        transforms (``is_ready()`` stays ``False``).  Use
        :meth:`set_origin_gps_with_local_snapshot` to bind both in one
        call.
        """
        self._guard_not_frozen()
        self.origin_source = OriginSource.GPS_MARKER.value
        self.origin_lat = float(lat)
        self.origin_lon = float(lon)

    def set_origin_gps_with_local_snapshot(
        self, lat: float, lon: float, local_n_m: float, local_e_m: float,
        local_z_m: float | None = None,
    ) -> None:
        """Record the GPS origin point **and** its LOCAL_NED position
        snapshot at the time of marking.

        The GPS lat/lon define the geographic reference; the LOCAL_NED
        snapshot defines the coordinate origin usable by the flight
        controller for ``field_to_local_ned`` / ``local_ned_to_field``.
        *local_z_m* is stored for status display (not used in XY transform).
        """
        self._guard_not_frozen()
        self.origin_source = OriginSource.GPS_MARKER.value
        self.origin_lat = float(lat)
        self.origin_lon = float(lon)
        self.origin_local_n_m = float(local_n_m)
        self.origin_local_e_m = float(local_e_m)
        if local_z_m is not None:
            self.origin_local_z_m = float(local_z_m)

    def set_origin_manual_gps(self, lat: float, lon: float) -> None:
        self._guard_not_frozen()
        self.origin_source = OriginSource.MANUAL_GPS_INPUT.value
        self.origin_lat = float(lat)
        self.origin_lon = float(lon)

    def set_forward_marker(self, lat: float, lon: float) -> None:
        self._guard_not_frozen()
        self.forward_marker_lat = float(lat)
        self.forward_marker_lon = float(lon)

    def set_compass_heading(self, yaw_rad: float) -> None:
        self._guard_not_frozen()
        self.heading_source = HeadingSource.COMPASS_YAW.value
        self.field_heading_yaw_rad = self._normalize_yaw(float(yaw_rad))

    def set_manual_heading(self, yaw_rad: float) -> None:
        self._guard_not_frozen()
        self.heading_source = HeadingSource.MANUAL_ANGLE.value
        self.field_heading_yaw_rad = self._normalize_yaw(float(yaw_rad))

    def set_gps_two_point_heading(self) -> None:
        """Declare that heading will be derived from GPS A→B bearing at
        ``confirm()`` time.  The actual bearing is computed during confirm."""
        self._guard_not_frozen()
        self.heading_source = HeadingSource.GPS_TWO_POINT.value

    # ------------------------------------------------------------------
    # confirm / freeze / reset
    # ------------------------------------------------------------------

    def confirm(self) -> None:
        """Validate all required fields and mark the reference confirmed.

        Raises :exc:`FieldReferenceError` on any validation failure.
        """
        self._guard_not_frozen()

        # -- origin --
        if self.origin_source is None:
            raise FieldReferenceError("origin_source must be set before confirm")
        if self.origin_source == OriginSource.LOCAL_POSITION.value:
            if self.origin_local_n_m is None or self.origin_local_e_m is None:
                raise FieldReferenceError(
                    "origin_local_n_m and origin_local_e_m required"
                    " for local_position origin"
                )
        elif self.origin_source in (
            OriginSource.GPS_MARKER.value,
            OriginSource.MANUAL_GPS_INPUT.value,
        ):
            if self.origin_lat is None or self.origin_lon is None:
                raise FieldReferenceError(
                    "origin_lat and origin_lon required for GPS origin"
                )

        # -- heading --
        if self.heading_source is None:
            raise FieldReferenceError("heading_source must be set before confirm")
        if self.heading_source in (
            HeadingSource.COMPASS_YAW.value,
            HeadingSource.MANUAL_ANGLE.value,
        ):
            if self.field_heading_yaw_rad is None or not math.isfinite(
                self.field_heading_yaw_rad
            ):
                raise FieldReferenceError(
                    "field_heading_yaw_rad must be a finite number"
                )
        elif self.heading_source == HeadingSource.GPS_TWO_POINT.value:
            if self.origin_lat is None or self.origin_lon is None:
                raise FieldReferenceError(
                    "origin GPS coordinates required for gps_two_point heading"
                )
            if self.forward_marker_lat is None or self.forward_marker_lon is None:
                raise FieldReferenceError(
                    "forward_marker required for gps_two_point heading"
                    " (single GPS point cannot define heading)"
                )
            distance = _gps_distance_m(
                self.origin_lat,
                self.origin_lon,
                self.forward_marker_lat,
                self.forward_marker_lon,
            )
            if distance < MIN_GPS_BASELINE_M:
                raise FieldReferenceError(
                    f"GPS A/B distance {distance:.2f}m"
                    f" < {MIN_GPS_BASELINE_M}m minimum"
                )
            # compute bearing and normalize
            self.field_heading_yaw_rad = self._normalize_yaw(
                _gps_bearing_rad(
                    self.origin_lat,
                    self.origin_lon,
                    self.forward_marker_lat,
                    self.forward_marker_lon,
                )
            )

        # final yaw normalization (belt-and-suspenders)
        if self.field_heading_yaw_rad is not None:
            self.field_heading_yaw_rad = self._normalize_yaw(
                self.field_heading_yaw_rad
            )

        self.is_confirmed = True
        self.confirmed_at_s = time.time()

    def confirm_with_warnings(self) -> Tuple[bool, list]:
        """Like :meth:`confirm` but returns ``(ok, warnings)`` instead of
        raising on hard validation failures.

        Warnings include the recommended-baseline advisory (5-10 m).
        """
        warnings: list = []
        try:
            self.confirm()
        except FieldReferenceError as exc:
            return False, [str(exc)]

        # post-confirm soft checks
        if self.heading_source == HeadingSource.GPS_TWO_POINT.value:
            if self.origin_lat is not None and self.forward_marker_lat is not None:
                distance = _gps_distance_m(
                    self.origin_lat,
                    self.origin_lon,
                    self.forward_marker_lat,
                    self.forward_marker_lon,
                )
                if distance < RECOMMENDED_GPS_BASELINE_M:
                    warnings.append(
                        f"GPS A/B distance {distance:.2f}m"
                        f" < recommended {RECOMMENDED_GPS_BASELINE_M}m"
                    )
        return True, warnings

    def freeze(self) -> None:
        """Freeze the confirmed reference so origin/heading cannot be
        accidentally changed during mission execution."""
        self._guard_confirmed()
        self.is_frozen = True

    def reset(self) -> None:
        """Clear all fields back to the unconfirmed, unfrozen state."""
        self.is_confirmed = False
        self.is_frozen = False
        self.origin_source = None
        self.heading_source = None
        self.origin_local_n_m = None
        self.origin_local_e_m = None
        self.origin_local_z_m = None
        self.origin_lat = None
        self.origin_lon = None
        self.forward_marker_lat = None
        self.forward_marker_lon = None
        self.field_heading_yaw_rad = None
        self.confirmed_at_s = None


# ---------------------------------------------------------------------------
# module-level GPS utilities (small-range ENU approximation)
# ---------------------------------------------------------------------------


def normalize_longitude_deg(longitude_deg: float) -> float:
    """Normalize a finite longitude to the canonical range [-180, 180)."""
    if not (
        isinstance(longitude_deg, (int, float))
        and not isinstance(longitude_deg, bool)
        and math.isfinite(float(longitude_deg))
    ):
        raise FieldReferenceError(
            f"longitude must be a finite number, got {longitude_deg!r}"
        )
    normalized = (float(longitude_deg) + 180.0) % 360.0 - 180.0
    return -180.0 if normalized == 180.0 else normalized


def shortest_longitude_delta_deg(
    from_lon_deg: float,
    to_lon_deg: float,
) -> float:
    """Return the shortest signed longitude delta from *from* to *to*."""
    if not (
        isinstance(from_lon_deg, (int, float))
        and not isinstance(from_lon_deg, bool)
        and math.isfinite(float(from_lon_deg))
    ):
        raise FieldReferenceError(
            f"from longitude must be a finite number, got {from_lon_deg!r}"
        )
    if not (
        isinstance(to_lon_deg, (int, float))
        and not isinstance(to_lon_deg, bool)
        and math.isfinite(float(to_lon_deg))
    ):
        raise FieldReferenceError(
            f"to longitude must be a finite number, got {to_lon_deg!r}"
        )
    return normalize_longitude_deg(float(to_lon_deg) - float(from_lon_deg))


def validate_wgs84_lat_lon(
    lat: object,
    lon: object,
    *,
    reject_pole: bool,
) -> tuple[float, float]:
    """Validate and return numeric WGS84 latitude/longitude values."""
    for name, value in (("latitude", lat), ("longitude", lon)):
        if not (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            raise FieldReferenceError(
                f"{name} must be a finite number, got {value!r}"
            )
    lat_f = float(lat)
    lon_f = float(lon)
    if not -90.0 <= lat_f <= 90.0:
        raise FieldReferenceError(f"latitude {lat_f} out of range [-90, 90]")
    if not -180.0 <= lon_f <= 180.0:
        raise FieldReferenceError(f"longitude {lon_f} out of range [-180, 180]")
    if reject_pole and abs(math.cos(math.radians(lat_f))) <= WGS84_POLE_COS_EPS:
        raise FieldReferenceError("latitude is too close to a WGS84 pole")
    return lat_f, lon_f

def gps_enu_deltas(
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
) -> Tuple[float, float]:
    """Return (d_north_m, d_east_m) from *a* to *b* using a small-range
    ENU approximation.  Inputs are decimal degrees."""
    lat_a_f, lon_a_f = validate_wgs84_lat_lon(
        lat_a, lon_a, reject_pole=True
    )
    lat_b_f, lon_b_f = validate_wgs84_lat_lon(
        lat_b, lon_b, reject_pole=True
    )
    lat_a_rad = math.radians(lat_a_f)
    lat_b_rad = math.radians(lat_b_f)
    d_north = (lat_b_rad - lat_a_rad) * EARTH_RADIUS_M
    d_east = (
        math.radians(shortest_longitude_delta_deg(lon_a_f, lon_b_f))
        * EARTH_RADIUS_M
        * math.cos(lat_a_rad)
    )
    return d_north, d_east


# backward-compatible alias for internal callers
_gps_enu_deltas = gps_enu_deltas


def _gps_distance_m(
    lat_a: float, lon_a: float, lat_b: float, lon_b: float
) -> float:
    """Great-circle distance approximation (ENU flat-earth for small ranges)."""
    d_north, d_east = _gps_enu_deltas(lat_a, lon_a, lat_b, lon_b)
    return math.hypot(d_north, d_east)


def _gps_bearing_rad(
    lat_a: float, lon_a: float, lat_b: float, lon_b: float
) -> float:
    """Bearing from *a* to *b* in radians (north = 0, east = +pi/2)."""
    d_north, d_east = _gps_enu_deltas(lat_a, lon_a, lat_b, lon_b)
    return math.atan2(d_east, d_north)
