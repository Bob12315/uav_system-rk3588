"""Runtime field geometry — pure math layer.

Schema v3 ``FieldProfile`` + dynamic origin GPS A → FIELD +Y heading,
baseline, scan waypoints, area boundaries, and home point.

Pure functions only: no global state, no telemetry, no flight commands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

from .coordinate_transform import field_to_gps_from_origin
from .field_profile import (
    BindingPolicy,
    DropScanConfig,
    FieldGeometry,
    FieldProfile,
    ForwardMarker,
    validate_field_profile,
)
from .field_reference import gps_enu_deltas


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


class RuntimeFieldGeometryError(ValueError):
    """Invalid input or geometry for runtime field generation."""


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeFieldPoint:
    """A single point in both FIELD-metre and GLOBAL GPS coordinates."""

    name: str
    field_x_m: float
    field_y_m: float
    altitude_m: float
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class RuntimeFieldGeometry:
    """Complete runtime field layout derived from Schema v3 + dynamic origin."""

    profile_id: str

    origin_lat: float
    origin_lon: float

    forward_marker_lat: float
    forward_marker_lon: float

    field_heading_yaw_rad: float
    field_heading_deg: float
    baseline_m: float

    home: RuntimeFieldPoint
    forward_marker: RuntimeFieldPoint

    drop_scan_waypoints: Tuple[RuntimeFieldPoint, ...]
    drop_area_corners: Tuple[RuntimeFieldPoint, ...]
    recce_area_corners: Tuple[RuntimeFieldPoint, ...]

    warnings: Tuple[str, ...]


# ---------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------


def build_runtime_field_geometry(
    profile: FieldProfile,
    *,
    origin_lat: float,
    origin_lon: float,
) -> RuntimeFieldGeometry:
    """Build a complete runtime field layout from a validated Schema v3
    ``FieldProfile`` and a dynamic origin GPS position.

    Pure function — does not mutate *profile*.
    """
    _validate_inputs(profile, origin_lat, origin_lon)

    marker: ForwardMarker = profile.forward_marker  # type: ignore[assignment]
    fg: FieldGeometry = profile.field_geometry
    bp: BindingPolicy = profile.binding_policy

    d_north, d_east = gps_enu_deltas(
        origin_lat, origin_lon, marker.lat, marker.lon
    )
    baseline_m = math.hypot(d_north, d_east)
    heading_rad = _normalize_yaw(math.atan2(d_east, d_north))
    heading_deg = math.degrees(heading_rad)

    warnings: list[str] = []

    # baseline policy
    if baseline_m < bp.min_baseline_m:
        raise RuntimeFieldGeometryError(
            f"A→B baseline {baseline_m:.1f} m is below minimum "
            f"{bp.min_baseline_m} m"
        )
    if baseline_m < bp.warn_baseline_below_m:
        warnings.append(
            f"A→B baseline {baseline_m:.1f} m is below warning threshold "
            f"{bp.warn_baseline_below_m} m (minimum {bp.min_baseline_m} m)"
        )

    # collect validation warnings
    val_diag = validate_field_profile(profile)
    warnings.extend(val_diag.warnings)

    home = RuntimeFieldPoint(
        name="HOME",
        field_x_m=0.0,
        field_y_m=0.0,
        altitude_m=0.0,
        lat=origin_lat,
        lon=origin_lon,
    )

    fwd = RuntimeFieldPoint(
        name=marker.name,
        field_x_m=0.0,
        field_y_m=baseline_m,
        altitude_m=0.0,
        lat=marker.lat,
        lon=marker.lon,
    )

    scan_points = _build_scan_points(
        profile.drop_scan, origin_lat, origin_lon, heading_rad
    )
    drop_corners = _build_area_corners(
        "D", fg.lane_half_width_m,
        fg.drop_area_y_min, fg.drop_area_y_max,
        origin_lat, origin_lon, heading_rad,
    )
    recce_corners = _build_area_corners(
        "R", fg.lane_half_width_m,
        fg.recce_area_y_min, fg.recce_area_y_max,
        origin_lat, origin_lon, heading_rad,
    )

    return RuntimeFieldGeometry(
        profile_id=profile.profile_id,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        forward_marker_lat=marker.lat,
        forward_marker_lon=marker.lon,
        field_heading_yaw_rad=heading_rad,
        field_heading_deg=heading_deg,
        baseline_m=baseline_m,
        home=home,
        forward_marker=fwd,
        drop_scan_waypoints=tuple(scan_points),
        drop_area_corners=tuple(drop_corners),
        recce_area_corners=tuple(recce_corners),
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _validate_inputs(
    profile: FieldProfile,
    origin_lat: float,
    origin_lon: float,
) -> None:
    if not isinstance(profile, FieldProfile):
        raise RuntimeFieldGeometryError("profile must be a FieldProfile instance")
    if profile.schema_version != 3:
        raise RuntimeFieldGeometryError(
            f"only schema v3 supported, got v{profile.schema_version}"
        )

    diag = validate_field_profile(profile)
    if not diag.ok:
        raise RuntimeFieldGeometryError(
            f"profile validation failed: {'; '.join(diag.errors)}"
        )

    if profile.forward_marker is None:
        raise RuntimeFieldGeometryError("profile has no forward_marker")
    if profile.drop_scan is None:
        raise RuntimeFieldGeometryError("profile has no drop_scan")
    if profile.drop_scan.waypoints is None or len(profile.drop_scan.waypoints) != 4:
        raise RuntimeFieldGeometryError("profile.drop_scan must have exactly 4 waypoints")

    if (
        profile.field_geometry.drop_area_y_min is None
        or profile.field_geometry.drop_area_y_max is None
        or profile.field_geometry.recce_area_y_min is None
        or profile.field_geometry.recce_area_y_max is None
    ):
        raise RuntimeFieldGeometryError("profile.field_geometry area boundaries must not be None")

    # validate dynamic origin
    for name, val in (("origin_lat", origin_lat), ("origin_lon", origin_lon)):
        if not (
            isinstance(val, (int, float))
            and not isinstance(val, bool)
            and math.isfinite(float(val))
        ):
            raise RuntimeFieldGeometryError(f"{name} must be a finite number, got {val!r}")
    if origin_lat < -90.0 or origin_lat > 90.0:
        raise RuntimeFieldGeometryError(f"origin_lat {origin_lat} out of range [-90, 90]")
    if origin_lon < -180.0 or origin_lon > 180.0:
        raise RuntimeFieldGeometryError(f"origin_lon {origin_lon} out of range [-180, 180]")
    if abs(math.cos(math.radians(origin_lat))) < 1e-9:
        raise RuntimeFieldGeometryError("origin latitude too close to pole")


def _normalize_yaw(yaw_rad: float) -> float:
    yaw = math.atan2(math.sin(yaw_rad), math.cos(yaw_rad))
    if yaw <= -math.pi + 1e-15:
        yaw = math.pi
    return yaw


def _build_scan_points(
    ds: DropScanConfig,
    origin_lat: float,
    origin_lon: float,
    heading_rad: float,
) -> list[RuntimeFieldPoint]:
    points: list[RuntimeFieldPoint] = []
    for i, wp in enumerate(ds.waypoints):
        gps = field_to_gps_from_origin(
            wp.x_m,
            wp.y_m,
            wp.altitude_m,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            field_heading_yaw_rad=heading_rad,
        )
        points.append(
            RuntimeFieldPoint(
                name=f"DROP_SCAN_{i + 1}",
                field_x_m=wp.x_m,
                field_y_m=wp.y_m,
                altitude_m=wp.altitude_m,
                lat=gps.lat,
                lon=gps.lon,
            )
        )
    return points


def _build_area_corners(
    prefix: str,
    lane_half_width_m: float,
    y_min: float | None,
    y_max: float | None,
    origin_lat: float,
    origin_lon: float,
    heading_rad: float,
) -> list[RuntimeFieldPoint]:
    if y_min is None or y_max is None:
        return []
    lane = lane_half_width_m
    corners = [
        (f"{prefix}1", -lane, y_min),
        (f"{prefix}2",  lane, y_min),
        (f"{prefix}3",  lane, y_max),
        (f"{prefix}4", -lane, y_max),
    ]
    points: list[RuntimeFieldPoint] = []
    for name, fx, fy in corners:
        gps = field_to_gps_from_origin(
            fx, fy, 0.0,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            field_heading_yaw_rad=heading_rad,
        )
        points.append(
            RuntimeFieldPoint(
                name=name,
                field_x_m=fx,
                field_y_m=fy,
                altitude_m=0.0,
                lat=gps.lat,
                lon=gps.lon,
            )
        )
    return points
