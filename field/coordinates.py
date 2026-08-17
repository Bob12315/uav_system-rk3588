from __future__ import annotations

import math
from dataclasses import dataclass

from .models import (
    EARTH_RADIUS_M,
    FieldReference,
    FieldReferenceError,
    gps_enu_deltas,
    normalize_longitude_deg,
    validate_wgs84_lat_lon,
)


# ---------------------------------------------------------------------------
# coordinate point types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FieldPoint:
    """A point in the FIELD frame.

    ``field_x_m`` is +right, ``field_y_m`` is +forward,
    ``altitude_m`` is positive-up.
    """

    field_x_m: float
    field_y_m: float
    altitude_m: float


@dataclass(slots=True)
class GpsPoint:
    """A point in global GPS coordinates.

    ``alt_m`` follows the MAVLink global frame selected by the caller
    (relative altitude for ``GLOBAL_RELATIVE_ALT_INT``).
    """

    lat: float
    lon: float
    alt_m: float


# ---------------------------------------------------------------------------
# transform functions
# ---------------------------------------------------------------------------

def field_to_gps(
    field_x_m: float,
    field_y_m: float,
    altitude_m: float,
    reference: FieldReference,
) -> GpsPoint:
    """Convert FIELD coordinates to GPS lat/lon.

    Uses the confirmed FIELD +Y heading and the profile GPS origin.  This
    is intended for fixed competition maps where FIELD targets should become
    global guided targets instead of LOCAL_NED offsets.
    """
    if (
        not reference.is_confirmed
        or reference.field_heading_yaw_rad is None
        or reference.origin_lat is None
        or reference.origin_lon is None
    ):
        raise FieldReferenceError(
            "FieldReference is not ready for field -> GPS conversion"
        )

    heading = float(reference.field_heading_yaw_rad)
    origin_lat = float(reference.origin_lat)
    origin_lon = float(reference.origin_lon)
    if not (
        math.isfinite(heading)
        and math.isfinite(origin_lat)
        and math.isfinite(origin_lon)
    ):
        raise FieldReferenceError(
            "FieldReference contains non-finite field -> GPS values"
        )

    if not reference.is_ready_for_field_to_gps():
        raise FieldReferenceError(
            "FieldReference is not ready for field -> GPS conversion"
        )

    return field_to_gps_from_origin(
        field_x_m,
        field_y_m,
        altitude_m,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        field_heading_yaw_rad=heading,
    )


def field_to_gps_from_origin(
    field_x_m: float,
    field_y_m: float,
    altitude_m: float,
    *,
    origin_lat: float,
    origin_lon: float,
    field_heading_yaw_rad: float,
) -> GpsPoint:
    """Convert FIELD coordinates to GPS lat/lon given explicit origin and heading.

    Pure function — does not read ``FieldReference`` or any global state.

    Parameters must be finite numbers (not None, bool, str, NaN, Inf).
    *origin_lat* ∈ [-90, 90], *origin_lon* ∈ [-180, 180].
    Raises :exc:`FieldReferenceError` on invalid input.
    """
    for name, val in (
        ("field_x_m", field_x_m),
        ("field_y_m", field_y_m),
        ("altitude_m", altitude_m),
        ("origin_lat", origin_lat),
        ("origin_lon", origin_lon),
        ("field_heading_yaw_rad", field_heading_yaw_rad),
    ):
        if not (isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))):
            raise FieldReferenceError(f"{name} must be a finite number, got {val!r}")

    if origin_lat < -90.0 or origin_lat > 90.0:
        raise FieldReferenceError(
            f"origin_lat {origin_lat} out of range [-90, 90]"
        )
    if origin_lon < -180.0 or origin_lon > 180.0:
        raise FieldReferenceError(
            f"origin_lon {origin_lon} out of range [-180, 180]"
        )
    try:
        origin_lat, origin_lon = validate_wgs84_lat_lon(
            origin_lat, origin_lon, reject_pole=True
        )
    except FieldReferenceError as exc:
        raise FieldReferenceError(f"invalid origin_lat/origin_lon: {exc}") from exc
    origin_lat_rad = math.radians(origin_lat)
    cos_lat = math.cos(origin_lat_rad)

    cos_h = math.cos(field_heading_yaw_rad)
    sin_h = math.sin(field_heading_yaw_rad)
    d_north = field_y_m * cos_h - field_x_m * sin_h
    d_east = field_y_m * sin_h + field_x_m * cos_h

    lat = origin_lat + math.degrees(d_north / EARTH_RADIUS_M)
    raw_lon = origin_lon + math.degrees(
        d_east / (EARTH_RADIUS_M * cos_lat)
    )
    lon = normalize_longitude_deg(raw_lon)
    lat, lon = validate_wgs84_lat_lon(lat, lon, reject_pole=True)
    return GpsPoint(lat=lat, lon=lon, alt_m=altitude_m)


def gps_to_field_from_origin(
    lat: float,
    lon: float,
    altitude_m: float,
    *,
    origin_lat: float,
    origin_lon: float,
    field_heading_yaw_rad: float,
) -> FieldPoint:
    """Convert GPS lat/lon to FIELD coordinates given explicit origin and heading.

    Pure function — does not read ``FieldReference`` or any global state.

    Parameters must be finite numbers (not None, bool, str, NaN, Inf).
    *origin_lat* ∈ [-90, 90], *origin_lon* ∈ [-180, 180].
    *lat* ∈ [-90, 90], *lon* ∈ [-180, 180].
    Raises :exc:`FieldReferenceError` on invalid input.
    """
    for name, val in (
        ("lat", lat),
        ("lon", lon),
        ("altitude_m", altitude_m),
        ("origin_lat", origin_lat),
        ("origin_lon", origin_lon),
        ("field_heading_yaw_rad", field_heading_yaw_rad),
    ):
        if not (isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))):
            raise FieldReferenceError(f"{name} must be a finite number, got {val!r}")

    if origin_lat < -90.0 or origin_lat > 90.0:
        raise FieldReferenceError(f"origin_lat {origin_lat} out of range [-90, 90]")
    if origin_lon < -180.0 or origin_lon > 180.0:
        raise FieldReferenceError(f"origin_lon {origin_lon} out of range [-180, 180]")
    if lat < -90.0 or lat > 90.0:
        raise FieldReferenceError(f"lat {lat} out of range [-90, 90]")
    if lon < -180.0 or lon > 180.0:
        raise FieldReferenceError(f"lon {lon} out of range [-180, 180]")

    try:
        origin_lat, origin_lon = validate_wgs84_lat_lon(origin_lat, origin_lon, reject_pole=True)
        lat, lon = validate_wgs84_lat_lon(lat, lon, reject_pole=True)
    except FieldReferenceError as exc:
        raise FieldReferenceError(f"invalid lat/lon: {exc}") from exc

    d_north, d_east = gps_enu_deltas(origin_lat, origin_lon, lat, lon)

    cos_h = math.cos(field_heading_yaw_rad)
    sin_h = math.sin(field_heading_yaw_rad)

    # Inverse of the FIELD → ENU rotation in field_to_gps_from_origin():
    #   d_north = field_y * cos_h - field_x * sin_h
    #   d_east  = field_y * sin_h + field_x * cos_h
    #   => field_y =  d_north * cos_h + d_east * sin_h
    #      field_x = -d_north * sin_h + d_east * cos_h
    field_y = d_north * cos_h + d_east * sin_h
    field_x = -d_north * sin_h + d_east * cos_h

    return FieldPoint(field_x_m=field_x, field_y_m=field_y, altitude_m=altitude_m)
