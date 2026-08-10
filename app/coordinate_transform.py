from __future__ import annotations

import math
from dataclasses import dataclass

from .field_reference import (
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
class LocalNedPoint:
    """A point in the LOCAL_NED frame.

    ``north_m`` / ``east_m`` / ``z_down_m`` follow the conventions in
    ``docs/developer/coordinate_frames.md``.
    """

    north_m: float
    east_m: float
    z_down_m: float


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

def field_to_local_ned(
    field_x_m: float,
    field_y_m: float,
    altitude_m: float,
    reference: FieldReference,
) -> LocalNedPoint:
    """Convert FIELD coordinates to LOCAL_NED.

    Implements the formula from ``docs/developer/coordinate_frames.md``::

        forward_N = cos(field_heading_yaw_rad)
        forward_E = sin(field_heading_yaw_rad)

        right_N = -sin(field_heading_yaw_rad)
        right_E =  cos(field_heading_yaw_rad)

        local_N = origin_N + field_y_m * forward_N + field_x_m * right_N
        local_E = origin_E + field_y_m * forward_E + field_x_m * right_E
        z_down  = -altitude_m

    Raises :exc:`FieldReferenceError` if *reference* is not ready.
    """
    if not reference.is_ready_for_field_to_local():
        raise FieldReferenceError(
            "FieldReference is not ready for coordinate transform"
        )

    yaw = reference.field_heading_yaw_rad  # type: float
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    # forward  = (cos_yaw,  sin_yaw)   -- FIELD +Y in LOCAL_NED
    # right    = (-sin_yaw, cos_yaw)   -- FIELD +X in LOCAL_NED
    local_n = (
        reference.origin_local_n_m
        + field_y_m * cos_yaw
        + field_x_m * (-sin_yaw)
    )
    local_e = (
        reference.origin_local_e_m
        + field_y_m * sin_yaw
        + field_x_m * cos_yaw
    )

    return LocalNedPoint(
        north_m=local_n,
        east_m=local_e,
        z_down_m=-altitude_m,
    )


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


def gps_to_local_ned(
    lat: float,
    lon: float,
    altitude_m: float,
    reference: FieldReference,
) -> LocalNedPoint:
    """Convert GPS coordinates to LOCAL_NED using a fixed origin.

    Uses *reference.origin_lat* / *reference.origin_lon* as the fixed GPS
    origin and *reference.origin_local_n_m* / *reference.origin_local_e_m*
    as the LOCAL_NED origin.  The current drone GPS position must NOT be
    used as the origin — this function is for mapping absolute global
    coordinates into a consistent LOCAL_NED frame.

    Height convention: ``z_down_m = -altitude_m`` (positive-up altitude
    becomes negative-down LOCAL_NED).

    Raises :exc:`FieldReferenceError` if the reference is missing its GPS
    origin or LOCAL origin fields.
    """
    if (
        reference.origin_lat is None
        or reference.origin_lon is None
        or reference.origin_local_n_m is None
        or reference.origin_local_e_m is None
    ):
        raise FieldReferenceError(
            "FieldReference is missing GPS or LOCAL origin for GPS -> LOCAL_NED conversion"
        )

    origin_lat = float(reference.origin_lat)
    origin_lon = float(reference.origin_lon)
    origin_n = float(reference.origin_local_n_m)
    origin_e = float(reference.origin_local_e_m)

    if not (
        math.isfinite(origin_lat)
        and math.isfinite(origin_lon)
        and math.isfinite(origin_n)
        and math.isfinite(origin_e)
        and math.isfinite(lat)
        and math.isfinite(lon)
        and math.isfinite(altitude_m)
    ):
        raise FieldReferenceError(
            "Non-finite values in GPS -> LOCAL_NED conversion"
        )

    d_north, d_east = gps_enu_deltas(origin_lat, origin_lon, lat, lon)

    return LocalNedPoint(
        north_m=origin_n + d_north,
        east_m=origin_e + d_east,
        z_down_m=-altitude_m,
    )


def local_ned_to_field(
    north_m: float,
    east_m: float,
    z_down_m: float,
    reference: FieldReference,
) -> FieldPoint:
    """Convert LOCAL_NED coordinates to FIELD (inverse of
    :func:`field_to_local_ned`).

    Raises :exc:`FieldReferenceError` if *reference* is not ready.
    """
    if not reference.is_ready():
        raise FieldReferenceError(
            "FieldReference is not ready for coordinate transform"
        )

    yaw = reference.field_heading_yaw_rad  # type: float
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    dn = north_m - reference.origin_local_n_m
    de = east_m - reference.origin_local_e_m

    # inverse rotation
    field_y = dn * cos_yaw + de * sin_yaw
    field_x = -dn * sin_yaw + de * cos_yaw

    return FieldPoint(
        field_x_m=field_x,
        field_y_m=field_y,
        altitude_m=-z_down_m,
    )
