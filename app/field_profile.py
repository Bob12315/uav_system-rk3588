"""Field Profile — pure logic for loading, validating, and binding
centerline-based field profiles.

This module does NOT write RuntimeContext, does NOT confirm/freeze, and does
NOT send MAVLink commands.  It is a pure data-and-math layer.

Schema version 2: takeoff-anchor + 4+ centerline GPS points.
Schema version 3: single forward marker + field geometry + drop scan waypoints
(in FIELD metres), with runtime origin sampling.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .field_reference import (
    EARTH_RADIUS_M,
    WGS84_POLE_COS_EPS,
    _gps_bearing_rad,
    _gps_distance_m,
    _gps_enu_deltas,
)


# ---------------------------------------------------------------------------
# dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GpsQualityThresholds:
    """Minimum GPS quality required for a profile bind (from JSON)."""

    min_fix_type: int = 3
    min_satellites: int = 10
    max_eph: float = 2.5
    max_epv: float = 5.0


@dataclass(slots=True)
class GpsQuality:
    """Observed GPS quality snapshot at bind time."""

    fix_type: int
    satellites_visible: int
    eph: Optional[float]
    epv: Optional[float]


@dataclass(slots=True)
class AnchorPoint:
    """Takeoff anchor point — defines where the drone takes off."""

    name: str
    lat: float
    lon: float
    field_x_m: float = 0.0
    field_y_m: float = 0.0


@dataclass(slots=True)
class CenterlinePoint:
    """A single GPS point along the field centerline (≥4 required)."""

    name: str
    lat: float
    lon: float
    expected_field_y_m: Optional[float] = None
    """Optional diagnostic-only expected field_y.  Does NOT participate in fitting."""


@dataclass(slots=True)
class ForwardMarker:
    """Single remote forward marker B (Schema v3).

    Obtained pre-competition via map or other means.  Must be WGS84.
    This is NOT the field origin and NOT the return-to-home point.
    """

    name: str
    lat: float
    lon: float
    coordinate_system: str = "WGS84"


@dataclass(slots=True)
class FieldScanWaypoint:
    """A single scan waypoint in FIELD metre coordinates (Schema v3).

    x_m: positive to the right, perpendicular to the centreline.
    y_m: positive forward along the centreline.
    altitude_m: positive up.
    """

    x_m: float
    y_m: float
    altitude_m: float


@dataclass(slots=True)
class DropScanConfig:
    """Drop scan waypoints (Schema v3).  Exactly 4 waypoints required."""

    waypoints: List[FieldScanWaypoint] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeOriginSampling:
    """Parameters for runtime origin sampling (Schema v3).

    Sampling is performed while the drone is stationary during pre-mission
    field confirmation, NOT after takeoff.  Only valid GPS samples are
    accepted.

    """

    min_samples: int = 20
    sample_window_s: float = 5.0
    max_horizontal_spread_m: float = 1.0
    estimator: str = "median"


@dataclass(slots=True)
class FieldGeometry:
    """Field geometry parameters."""

    lane_half_width_m: float = 4.0
    drop_center_y_m: float = 32.5
    recce_center_y_m: float = 57.5
    drop_area_y_min: Optional[float] = 30.0
    drop_area_y_max: Optional[float] = 35.0
    recce_area_y_min: Optional[float] = 55.0
    recce_area_y_max: Optional[float] = 60.0


@dataclass(slots=True)
class BindingPolicy:
    """Binding error/warning thresholds."""

    # v2 fields — keep defaults unchanged
    max_start_error_m: float = 3.0
    warn_start_error_m: float = 1.5
    max_centerline_residual_m: float = 2.5
    warn_centerline_residual_m: float = 1.5

    # v3 fields
    min_baseline_m: float = 30.0
    warn_baseline_below_m: float = 50.0


@dataclass(slots=True)
class FieldProfile:
    """Deserialised, validated field profile.

    Schema v2: anchor + 4+ centerline_points.
    Schema v3: forward_marker + drop_scan + runtime_origin_sampling.
    """

    schema_version: int
    profile_id: str
    name: str
    coordinate_convention: Dict[str, str]
    anchor: Optional[AnchorPoint] = None
    centerline_points: List[CenterlinePoint] = field(default_factory=list)
    forward_marker: Optional[ForwardMarker] = None
    drop_scan: Optional[DropScanConfig] = None
    recon_scan: Optional[DropScanConfig] = None
    gps_quality: GpsQualityThresholds = field(default_factory=GpsQualityThresholds)
    field_geometry: FieldGeometry = field(default_factory=FieldGeometry)
    binding_policy: BindingPolicy = field(default_factory=BindingPolicy)
    runtime_origin_sampling: Optional[RuntimeOriginSampling] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    """Unknown top-level JSON keys preserved for forward compatibility."""


# ---------------------------------------------------------------------------
# centerline fitting result
# ---------------------------------------------------------------------------


@dataclass
class CenterlineFitResult:
    """Output of centerline fitting on anchor + centerline_points."""

    field_heading_yaw_rad: float
    field_heading_deg: float
    baseline_m: float
    """Distance from anchor to farthest centerline point."""
    point_residuals: List[float]
    """Perpendicular residual (m) for each centerline point."""
    max_residual_m: float
    rms_residual_m: float
    diagnostics: "FieldProfileDiagnostics"


@dataclass
class FieldProfileDiagnostics:
    """Collected errors and warnings from validation or fitting."""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


class FieldProfileValidationError(ValueError):
    """Raised when a field profile fails validation.

    Carries the full diagnostics so callers can inspect both errors and
    warnings.
    """

    def __init__(self, diagnostics: FieldProfileDiagnostics) -> None:
        self.diagnostics = diagnostics
        super().__init__(
            f"FieldProfile validation failed: "
            f"{len(diagnostics.errors)} error(s), "
            f"{len(diagnostics.warnings)} warning(s)"
        )


# ---------------------------------------------------------------------------
# public API — load / parse / validate
# ---------------------------------------------------------------------------


def load_field_profile_json(path: str) -> FieldProfile:
    """Read a ``*.json`` file, parse it, and validate it.

    Returns a fully-populated :class:`FieldProfile` on success.
    Raises :class:`FieldProfileValidationError` on any hard error.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Field profile not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = json.load(fh)

    profile = parse_field_profile(raw)
    diag = validate_field_profile(profile)
    if not diag.ok:
        raise FieldProfileValidationError(diag)
    return profile


def parse_field_profile(data: Dict[str, Any]) -> FieldProfile:
    """Construct a :class:`FieldProfile` from a raw JSON dict.

    Dispatches to the v2 or v3 parser based on ``schema_version``.
    """
    schema_version = _parse_schema_version(data)
    common = _parse_common_fields(data)

    if schema_version == 2:
        return _parse_field_profile_v2(data, common)

    if schema_version == 3:
        return _parse_field_profile_v3(data, common)

    raise FieldProfileValidationError(
        FieldProfileDiagnostics(
            errors=[f"Unsupported schema_version {schema_version} (only 2 and 3 are supported)"]
        )
    )


def validate_field_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
    """Run all semantic validation checks on *profile*.

    Dispatches to the v2 or v3 validator based on ``schema_version``.
    """
    diag = FieldProfileDiagnostics()

    if profile.schema_version == 2:
        _validate_field_profile_v2(profile, diag)
    elif profile.schema_version == 3:
        _validate_field_profile_v3(profile, diag)
    else:
        diag.errors.append(
            f"Unsupported schema_version {profile.schema_version} (only 2 and 3 are supported)"
        )

    return diag


# ---------------------------------------------------------------------------
# Schema v2 parser (preserved behaviour)
# ---------------------------------------------------------------------------

_V2_TOP_KEYS = {
    "schema_version", "profile_id", "name", "created_at",
    "coordinate_convention", "anchor", "centerline_points",
    "gps_quality", "field_geometry", "binding_policy",
}


def _parse_field_profile_v2(
    data: Dict[str, Any], common: Dict[str, Any]
) -> FieldProfile:
    extra: Dict[str, Any] = {}
    for key, value in data.items():
        if key not in _V2_TOP_KEYS:
            extra[key] = value

    # -- anchor ----------------------------------------------------------
    raw_anchor = data.get("anchor")
    if raw_anchor is None or not isinstance(raw_anchor, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=["'anchor' is required and must be a JSON object"])
        )
    anchor_name = str(raw_anchor.get("name", "takeoff_anchor"))
    anchor_lat = _require_float_in_obj(raw_anchor, "lat", "anchor")
    anchor_lon = _require_float_in_obj(raw_anchor, "lon", "anchor")
    anchor_fx = float(raw_anchor.get("field_x_m", 0.0))
    anchor_fy = float(raw_anchor.get("field_y_m", 0.0))
    anchor = AnchorPoint(name=anchor_name, lat=anchor_lat, lon=anchor_lon,
                         field_x_m=anchor_fx, field_y_m=anchor_fy)

    # -- centerline_points -----------------------------------------------
    raw_cl = data.get("centerline_points")
    if raw_cl is None or not isinstance(raw_cl, list):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'centerline_points' is required and must be a JSON array"]
            )
        )
    centerline_points: List[CenterlinePoint] = []
    for i, raw_pt in enumerate(raw_cl):
        if not isinstance(raw_pt, dict):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"centerline_points[{i}] must be a JSON object, got {type(raw_pt).__name__}"]
                )
            )
        pt_name = str(raw_pt.get("name", f"cl_{i}"))
        pt_lat = _require_float_in_obj(raw_pt, "lat", f"centerline_points[{i}]")
        pt_lon = _require_float_in_obj(raw_pt, "lon", f"centerline_points[{i}]")
        expected_fy = raw_pt.get("expected_field_y_m")
        if expected_fy is not None:
            if isinstance(expected_fy, bool) or not isinstance(expected_fy, (int, float)):
                raise FieldProfileValidationError(
                    FieldProfileDiagnostics(
                        errors=[f"centerline_points[{i}].expected_field_y_m must be a number"]
                    )
                )
            expected_fy = float(expected_fy)
            if not math.isfinite(expected_fy):
                raise FieldProfileValidationError(
                    FieldProfileDiagnostics(
                        errors=[f"centerline_points[{i}].expected_field_y_m is not finite"]
                    )
                )
        centerline_points.append(CenterlinePoint(
            name=pt_name, lat=pt_lat, lon=pt_lon,
            expected_field_y_m=expected_fy,
        ))

    gps_quality = _parse_gps_quality_thresholds(data)
    field_geometry = _parse_field_geometry(data)
    binding_policy = _parse_binding_policy(data)

    return FieldProfile(
        schema_version=common["schema_version"],
        profile_id=common["profile_id"],
        name=common["name"],
        coordinate_convention=common["coordinate_convention"],
        anchor=anchor,
        centerline_points=centerline_points,
        gps_quality=gps_quality,
        field_geometry=field_geometry,
        binding_policy=binding_policy,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Schema v3 parser
# ---------------------------------------------------------------------------

_V3_TOP_KEYS = {
    "schema_version", "profile_id", "name", "created_at",
    "coordinate_convention", "forward_marker", "field_geometry",
    "drop_scan", "recon_scan", "gps_quality", "runtime_origin_sampling",
    "binding_policy",
}

_V3_FORBIDDEN_KEYS = {"anchor", "centerline_points", "origin", "origin_lat", "origin_lon"}


def _parse_field_profile_v3(
    data: Dict[str, Any], common: Dict[str, Any]
) -> FieldProfile:
    extra: Dict[str, Any] = {}
    for key, value in data.items():
        if key not in _V3_TOP_KEYS:
            if key in _V3_FORBIDDEN_KEYS:
                raise FieldProfileValidationError(
                    FieldProfileDiagnostics(
                        errors=[f"schema v3 must not contain pre-surveyed '{key}'"]
                    )
                )
            extra[key] = value

    # -- forward_marker --------------------------------------------------
    forward_marker = _parse_forward_marker(data)

    # -- field_geometry (v3 JSON key names mapped to FieldGeometry) ------
    field_geometry = _parse_field_geometry_v3(data)

    # -- drop_scan -------------------------------------------------------
    drop_scan = _parse_drop_scan_v3(data, field_geometry)

    # -- recon_scan (optional, same format as drop_scan) --------------
    recon_scan = _parse_recon_scan_v3(data, field_geometry)

    # -- gps_quality (v3 requires the object) ----------------------------
    gps_quality = _parse_gps_quality_v3(data)

    # -- runtime_origin_sampling -----------------------------------------
    runtime_origin_sampling = _parse_runtime_origin_sampling_v3(data)

    # -- binding_policy (v3 requires the object) -------------------------
    binding_policy = _parse_binding_policy_v3(data)

    return FieldProfile(
        schema_version=common["schema_version"],
        profile_id=common["profile_id"],
        name=common["name"],
        coordinate_convention=common["coordinate_convention"],
        anchor=None,
        centerline_points=[],
        forward_marker=forward_marker,
        drop_scan=drop_scan,
        recon_scan=recon_scan,
        gps_quality=gps_quality,
        field_geometry=field_geometry,
        binding_policy=binding_policy,
        runtime_origin_sampling=runtime_origin_sampling,
        extra=extra,
    )


def _parse_forward_marker(data: Dict[str, Any]) -> ForwardMarker:
    raw = data.get("forward_marker")
    if raw is None or not isinstance(raw, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'forward_marker' is required and must be a JSON object"]
            )
        )
    name = str(raw.get("name", "")).strip()
    if not isinstance(raw.get("name"), str) or not name:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=["forward_marker.name must be a non-empty string"])
        )
    lat = _require_float_in_obj(raw, "lat", "forward_marker")
    lon = _require_float_in_obj(raw, "lon", "forward_marker")
    if lat < -90.0 or lat > 90.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"forward_marker.lat {lat} out of range [-90, 90]"])
        )
    if lon < -180.0 or lon > 180.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"forward_marker.lon {lon} out of range [-180, 180]"])
        )
    coord_sys = raw.get("coordinate_system")
    if coord_sys is None:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["forward_marker.coordinate_system is required"]
            )
        )
    if coord_sys != "WGS84":
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"forward_marker.coordinate_system must be 'WGS84', got {coord_sys!r}"]
            )
        )
    return ForwardMarker(name=name, lat=lat, lon=lon, coordinate_system="WGS84")


def _parse_field_geometry_v3(data: Dict[str, Any]) -> FieldGeometry:
    raw = data.get("field_geometry")
    if raw is None or not isinstance(raw, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'field_geometry' is required and must be a JSON object"]
            )
        )

    lane_half = _require_float_nonneg(
        _require_in_obj(raw, "lane_half_width_m"),
        "field_geometry.lane_half_width_m",
    )
    if lane_half <= 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"field_geometry.lane_half_width_m must be > 0, got {lane_half}"]
            )
        )

    drop_min = _require_float_nonneg(
        _require_in_obj(raw, "drop_area_y_min_m"),
        "field_geometry.drop_area_y_min_m",
    )
    drop_max = _require_float_nonneg(
        _require_in_obj(raw, "drop_area_y_max_m"),
        "field_geometry.drop_area_y_max_m",
    )
    drop_center = _require_float_nonneg(
        _require_in_obj(raw, "drop_center_y_m"),
        "field_geometry.drop_center_y_m",
    )
    recce_min = _require_float_nonneg(
        _require_in_obj(raw, "recce_area_y_min_m"),
        "field_geometry.recce_area_y_min_m",
    )
    recce_max = _require_float_nonneg(
        _require_in_obj(raw, "recce_area_y_max_m"),
        "field_geometry.recce_area_y_max_m",
    )
    recce_center = _require_float_nonneg(
        _require_in_obj(raw, "recce_center_y_m"),
        "field_geometry.recce_center_y_m",
    )

    return FieldGeometry(
        lane_half_width_m=lane_half,
        drop_center_y_m=drop_center,
        recce_center_y_m=recce_center,
        drop_area_y_min=drop_min,
        drop_area_y_max=drop_max,
        recce_area_y_min=recce_min,
        recce_area_y_max=recce_max,
    )


def _parse_drop_scan_v3(data: Dict[str, Any], fg: FieldGeometry) -> DropScanConfig:
    raw = data.get("drop_scan")
    if raw is None or not isinstance(raw, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'drop_scan' is required and must be a JSON object"]
            )
        )
    waypoints_raw = raw.get("waypoints")
    if waypoints_raw is None or not isinstance(waypoints_raw, list):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["drop_scan.waypoints is required and must be a JSON array"]
            )
        )
    if len(waypoints_raw) != 4:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"drop_scan.waypoints must have exactly 4 waypoints, got {len(waypoints_raw)}"]
            )
        )

    waypoints: List[FieldScanWaypoint] = []
    for i, wp in enumerate(waypoints_raw):
        if not isinstance(wp, dict):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"drop_scan.waypoints[{i}] must be a JSON object, got {type(wp).__name__}"]
                )
            )
        # reject GPS/local fields in waypoints
        for forbidden in ("lat", "lon", "local_x", "local_y"):
            if forbidden in wp:
                raise FieldProfileValidationError(
                    FieldProfileDiagnostics(
                        errors=[
                            f"drop_scan.waypoints[{i}] must not contain '{forbidden}'; "
                            f"use FIELD metre coordinates (x_m, y_m)"
                        ]
                    )
                )
        x_m = _require_float_in_obj(wp, "x_m", f"drop_scan.waypoints[{i}]")
        y_m = _require_float_in_obj(wp, "y_m", f"drop_scan.waypoints[{i}]")
        alt = _require_float_in_obj(wp, "altitude_m", f"drop_scan.waypoints[{i}]")
        if alt <= 0.0:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"drop_scan.waypoints[{i}].altitude_m must be > 0, got {alt}"]
                )
            )
        lane = fg.lane_half_width_m
        if x_m < -lane or x_m > lane:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[
                        f"drop_scan.waypoints[{i}].x_m={x_m} outside "
                        f"lane [-{lane}, {lane}]"
                    ]
                )
            )
        dmin = fg.drop_area_y_min
        dmax = fg.drop_area_y_max
        if dmin is not None and dmax is not None:
            if y_m < dmin or y_m > dmax:
                raise FieldProfileValidationError(
                    FieldProfileDiagnostics(
                        errors=[
                            f"drop_scan.waypoints[{i}].y_m={y_m} outside "
                            f"drop area [{dmin}, {dmax}]"
                        ]
                    )
                )
        waypoints.append(FieldScanWaypoint(x_m=x_m, y_m=y_m, altitude_m=alt))

    # check not all identical
    coords = {(w.x_m, w.y_m, w.altitude_m) for w in waypoints}
    if len(coords) < 2:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["drop_scan.waypoints must not be all identical"]
            )
        )

    return DropScanConfig(waypoints=waypoints)


def _parse_recon_scan_v3(data: Dict[str, Any], fg: FieldGeometry) -> Optional[DropScanConfig]:
    """Parse optional recon_scan; returns None if key is missing."""
    raw = data.get("recon_scan")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'recon_scan' must be a JSON object when present"]
            )
        )
    waypoints_raw = raw.get("waypoints")
    if waypoints_raw is None or not isinstance(waypoints_raw, list):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["recon_scan.waypoints is required and must be a JSON array"]
            )
        )
    if len(waypoints_raw) != 4:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"recon_scan.waypoints must have exactly 4 waypoints, got {len(waypoints_raw)}"]
            )
        )

    waypoints: List[FieldScanWaypoint] = []
    for i, wp in enumerate(waypoints_raw):
        if not isinstance(wp, dict):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"recon_scan.waypoints[{i}] must be a JSON object"]
                )
            )
        for forbidden in ("lat", "lon", "local_x", "local_y"):
            if forbidden in wp:
                raise FieldProfileValidationError(
                    FieldProfileDiagnostics(
                        errors=[f"recon_scan.waypoints[{i}] must not contain '{forbidden}'"]
                    )
                )
        x_m = _require_float_in_obj(wp, "x_m", f"recon_scan.waypoints[{i}]")
        y_m = _require_float_in_obj(wp, "y_m", f"recon_scan.waypoints[{i}]")
        alt = _require_float_in_obj(wp, "altitude_m", f"recon_scan.waypoints[{i}]")
        if alt <= 0.0:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"recon_scan.waypoints[{i}].altitude_m must be > 0, got {alt}"]
                )
            )
        lane = fg.lane_half_width_m
        if x_m < -lane or x_m > lane:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"recon_scan.waypoints[{i}].x_m={x_m} outside lane [-{lane}, {lane}]"]
                )
            )
        rmin = fg.recce_area_y_min
        rmax = fg.recce_area_y_max
        if rmin is not None and rmax is not None:
            if y_m < rmin or y_m > rmax:
                raise FieldProfileValidationError(
                    FieldProfileDiagnostics(
                        errors=[f"recon_scan.waypoints[{i}].y_m={y_m} outside recce area [{rmin}, {rmax}]"]
                    )
                )
        waypoints.append(FieldScanWaypoint(x_m=x_m, y_m=y_m, altitude_m=alt))

    coords = {(w.x_m, w.y_m, w.altitude_m) for w in waypoints}
    if len(coords) < 2:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=["recon_scan.waypoints must not be all identical"])
        )

    return DropScanConfig(waypoints=waypoints)


def _parse_gps_quality_v3(data: Dict[str, Any]) -> GpsQualityThresholds:
    raw = data.get("gps_quality")
    if raw is None or not isinstance(raw, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'gps_quality' is required and must be a JSON object"]
            )
        )
    # reject hdop fields
    for hkey in ("hdop", "max_hdop"):
        if hkey in raw:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[
                        f"gps_quality must not contain '{hkey}'; "
                        f"Schema v3 uses EPH/EPV"
                    ]
                )
            )

    min_fix_type = _require_int_nonneg(
        _require_in_obj(raw, "min_fix_type"), "gps_quality.min_fix_type"
    )
    if min_fix_type < 3:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"gps_quality.min_fix_type must be >= 3, got {min_fix_type}"]
            )
        )
    min_satellites = _require_int_nonneg(
        _require_in_obj(raw, "min_satellites"), "gps_quality.min_satellites"
    )
    if min_satellites <= 0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"gps_quality.min_satellites must be > 0, got {min_satellites}"]
            )
        )
    max_eph = _require_float_nonneg(
        _require_in_obj(raw, "max_eph"), "gps_quality.max_eph"
    )
    if max_eph <= 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"gps_quality.max_eph must be > 0, got {max_eph}"]
            )
        )
    max_epv = _require_float_nonneg(
        _require_in_obj(raw, "max_epv"), "gps_quality.max_epv"
    )
    if max_epv <= 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"gps_quality.max_epv must be > 0, got {max_epv}"]
            )
        )

    return GpsQualityThresholds(
        min_fix_type=min_fix_type,
        min_satellites=min_satellites,
        max_eph=max_eph,
        max_epv=max_epv,
    )


def _parse_runtime_origin_sampling_v3(data: Dict[str, Any]) -> RuntimeOriginSampling:
    raw = data.get("runtime_origin_sampling")
    if raw is None or not isinstance(raw, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'runtime_origin_sampling' is required and must be a JSON object"]
            )
        )
    min_samp = _require_int_nonneg(
        _require_in_obj(raw, "min_samples"),
        "runtime_origin_sampling.min_samples",
    )
    if min_samp < 3:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[
                    f"runtime_origin_sampling.min_samples must be >= 3, got {min_samp}"
                ]
            )
        )
    window = _require_float_nonneg(
        _require_in_obj(raw, "sample_window_s"),
        "runtime_origin_sampling.sample_window_s",
    )
    if window <= 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[
                    f"runtime_origin_sampling.sample_window_s must be > 0, got {window}"
                ]
            )
        )
    spread = _require_float_nonneg(
        _require_in_obj(raw, "max_horizontal_spread_m"),
        "runtime_origin_sampling.max_horizontal_spread_m",
    )
    if spread <= 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[
                    f"runtime_origin_sampling.max_horizontal_spread_m must be > 0, got {spread}"
                ]
            )
        )
    estimator_raw = raw.get("estimator")
    if estimator_raw is None or estimator_raw != "median":
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[
                    f"runtime_origin_sampling.estimator must be 'median', "
                    f"got {estimator_raw!r}"
                ]
            )
        )

    return RuntimeOriginSampling(
        min_samples=min_samp,
        sample_window_s=window,
        max_horizontal_spread_m=spread,
        estimator="median",
    )


def _parse_binding_policy_v3(data: Dict[str, Any]) -> BindingPolicy:
    raw = data.get("binding_policy")
    if raw is None or not isinstance(raw, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'binding_policy' is required and must be a JSON object for schema v3"]
            )
        )
    min_bl = _require_float_nonneg(
        _require_in_obj(raw, "min_baseline_m"),
        "binding_policy.min_baseline_m",
    )
    if min_bl <= 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"binding_policy.min_baseline_m must be > 0, got {min_bl}"]
            )
        )
    warn_bl = _require_float_nonneg(
        _require_in_obj(raw, "warn_baseline_below_m"),
        "binding_policy.warn_baseline_below_m",
    )
    if warn_bl <= min_bl:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[
                    f"binding_policy.warn_baseline_below_m ({warn_bl}) "
                    f"must be > min_baseline_m ({min_bl})"
                ]
            )
        )

    return BindingPolicy(
        min_baseline_m=min_bl,
        warn_baseline_below_m=warn_bl,
    )


# ---------------------------------------------------------------------------
# Schema v2 validator (preserved behaviour)
# ---------------------------------------------------------------------------


def _validate_field_profile_v2(
    profile: FieldProfile, diag: FieldProfileDiagnostics
) -> None:
    # -- profile_id -------------------------------------------------------
    if not profile.profile_id.strip():
        diag.errors.append("profile_id must be non-empty")

    # -- coordinate convention --------------------------------------------
    _validate_coordinate_convention(profile.coordinate_convention, diag)

    # -- anchor -----------------------------------------------------------
    anchor = profile.anchor
    if anchor is None:
        diag.errors.append("anchor is required for schema v2")
    else:
        if anchor.lat < -90.0 or anchor.lat > 90.0:
            diag.errors.append(f"anchor.lat {anchor.lat} out of range [-90, 90]")
        if anchor.lon < -180.0 or anchor.lon > 180.0:
            diag.errors.append(f"anchor.lon {anchor.lon} out of range [-180, 180]")
        if not math.isfinite(anchor.field_x_m):
            diag.errors.append(f"anchor.field_x_m is not finite: {anchor.field_x_m}")
        if not math.isfinite(anchor.field_y_m):
            diag.errors.append(f"anchor.field_y_m is not finite: {anchor.field_y_m}")
        if not math.isclose(anchor.field_x_m, 0.0, abs_tol=1e-9):
            diag.errors.append(
                f"anchor.field_x_m must be 0.0 (takeoff anchor is FIELD origin), got {anchor.field_x_m}"
            )
        if not math.isclose(anchor.field_y_m, 0.0, abs_tol=1e-9):
            diag.errors.append(
                f"anchor.field_y_m must be 0.0 (takeoff anchor is FIELD origin), got {anchor.field_y_m}"
            )

    # -- centerline_points ------------------------------------------------
    if len(profile.centerline_points) < 4:
        diag.errors.append(
            f"centerline_points must have at least 4 points, got {len(profile.centerline_points)}"
        )
    for i, pt in enumerate(profile.centerline_points):
        if pt.lat < -90.0 or pt.lat > 90.0:
            diag.errors.append(f"centerline_points[{i}].lat {pt.lat} out of range [-90, 90]")
        if pt.lon < -180.0 or pt.lon > 180.0:
            diag.errors.append(f"centerline_points[{i}].lon {pt.lon} out of range [-180, 180]")

    if not diag.ok:
        return

    # -- centerline fitting sanity ---------------------------------------
    if anchor is not None:
        enu_points: List[Tuple[float, float]] = []
        for pt in profile.centerline_points:
            dn, de = _gps_enu_deltas(anchor.lat, anchor.lon, pt.lat, pt.lon)
            enu_points.append((dn, de))

        min_dist = min(
            math.hypot(dn, de) for dn, de in enu_points
        )
        if min_dist < 0.5:
            diag.errors.append(
                f"Minimum centerline point distance from anchor is {min_dist:.2f} m (< 0.5 m)"
            )

        # check direction consistency (original semantics: reference =
        # direction to farthest point, cosine < 0.7 → warning)
        if len(enu_points) >= 2:
            farthest_idx = max(
                range(len(enu_points)),
                key=lambda i: math.hypot(*enu_points[i]),
            )
            farthest_n, farthest_e = enu_points[farthest_idx]
            farthest_dist = math.hypot(farthest_n, farthest_e)

            if farthest_dist > 0.0:
                ref_n = farthest_n / farthest_dist
                ref_e = farthest_e / farthest_dist

                for i, (dn, de) in enumerate(enu_points):
                    distance = math.hypot(dn, de)
                    if distance < 0.01:
                        continue

                    dot = (dn * ref_n + de * ref_e) / distance
                    if dot < 0.7:
                        diag.warnings.append(
                            f"centerline_points[{i}] direction deviates "
                            f"from main axis (cos={dot:.2f})"
                        )

    # -- field_geometry ---------------------------------------------------
    fg = profile.field_geometry
    if fg.lane_half_width_m <= 0.0:
        diag.errors.append(f"field_geometry.lane_half_width_m must be > 0, got {fg.lane_half_width_m}")
    if fg.drop_center_y_m <= 0.0:
        diag.errors.append(f"field_geometry.drop_center_y_m must be > 0, got {fg.drop_center_y_m}")
    if fg.recce_center_y_m <= 0.0:
        diag.errors.append(
            f"field_geometry.recce_center_y_m must be > 0, got {fg.recce_center_y_m}"
        )

    # -- binding_policy ---------------------------------------------------
    bp = profile.binding_policy
    if bp.max_start_error_m <= 0.0:
        diag.errors.append(f"binding_policy.max_start_error_m must be > 0, got {bp.max_start_error_m}")
    if bp.warn_start_error_m <= 0.0:
        diag.errors.append(f"binding_policy.warn_start_error_m must be > 0, got {bp.warn_start_error_m}")
    if bp.warn_start_error_m >= bp.max_start_error_m:
        diag.errors.append(
            f"binding_policy.warn_start_error_m ({bp.warn_start_error_m}) "
            f"must be < max_start_error_m ({bp.max_start_error_m})"
        )
    if bp.max_centerline_residual_m <= 0.0:
        diag.errors.append(f"binding_policy.max_centerline_residual_m must be > 0, got {bp.max_centerline_residual_m}")
    if bp.warn_centerline_residual_m <= 0.0:
        diag.errors.append(f"binding_policy.warn_centerline_residual_m must be > 0, got {bp.warn_centerline_residual_m}")
    if bp.warn_centerline_residual_m >= bp.max_centerline_residual_m:
        diag.errors.append(
            f"binding_policy.warn_centerline_residual_m ({bp.warn_centerline_residual_m}) "
            f"must be < max_centerline_residual_m ({bp.max_centerline_residual_m})"
        )

    # -- unknown top-level keys → warning ----------------------------------
    if profile.extra:
        for key in sorted(profile.extra.keys()):
            diag.warnings.append(
                f"Unknown top-level key '{key}' (retained for forward compatibility)"
            )


# ---------------------------------------------------------------------------
# Schema v3 validator
# ---------------------------------------------------------------------------


def _validate_field_profile_v3(
    profile: FieldProfile, diag: FieldProfileDiagnostics
) -> None:
    # -- reject pre-surveyed static origin data ---------------------------
    if profile.anchor is not None:
        diag.errors.append("schema v3 must not contain pre-surveyed 'anchor'")
    if profile.centerline_points:
        diag.errors.append(
            "schema v3 must not contain pre-surveyed 'centerline_points'"
        )

    # -- profile_id -------------------------------------------------------
    if not profile.profile_id.strip():
        diag.errors.append("profile_id must be non-empty")

    # -- coordinate convention --------------------------------------------
    _validate_coordinate_convention(profile.coordinate_convention, diag)

    # -- forward_marker ---------------------------------------------------
    fm = profile.forward_marker
    if fm is None:
        diag.errors.append("forward_marker is required for schema v3")
    else:
        if not isinstance(fm.name, str) or not fm.name.strip():
            diag.errors.append("forward_marker.name must be a non-empty string")
        if not _is_finite_number(fm.lat):
            diag.errors.append(
                f"forward_marker.lat must be a finite number, got {fm.lat!r}"
            )
        elif not -90.0 <= float(fm.lat) <= 90.0:
            diag.errors.append(
                f"forward_marker.lat {fm.lat} out of range [-90, 90]"
            )
        elif abs(math.cos(math.radians(float(fm.lat)))) <= WGS84_POLE_COS_EPS:
            diag.errors.append("forward_marker latitude is too close to a pole")
        if not _is_finite_number(fm.lon):
            diag.errors.append(
                f"forward_marker.lon must be a finite number, got {fm.lon!r}"
            )
        elif not -180.0 <= float(fm.lon) <= 180.0:
            diag.errors.append(
                f"forward_marker.lon {fm.lon} out of range [-180, 180]"
            )
        if not isinstance(fm.coordinate_system, str) or fm.coordinate_system != "WGS84":
            diag.errors.append(
                f"forward_marker.coordinate_system must be 'WGS84', "
                f"got {fm.coordinate_system!r}"
            )

    # -- field_geometry ---------------------------------------------------
    fg = profile.field_geometry

    if not _is_finite_number(fg.lane_half_width_m):
        diag.errors.append(
            f"field_geometry.lane_half_width_m must be a finite number, "
            f"got {fg.lane_half_width_m!r}"
        )
    elif fg.lane_half_width_m <= 0.0:
        diag.errors.append(
            f"field_geometry.lane_half_width_m must be > 0, got {fg.lane_half_width_m}"
        )

    if not _is_finite_number(fg.drop_center_y_m):
        diag.errors.append(
            f"field_geometry.drop_center_y_m must be a finite number, "
            f"got {fg.drop_center_y_m!r}"
        )
    if not _is_finite_number(fg.recce_center_y_m):
        diag.errors.append(
            f"field_geometry.recce_center_y_m must be a finite number, "
            f"got {fg.recce_center_y_m!r}"
        )

    area_fields = [
        ("drop_area_y_min", fg.drop_area_y_min),
        ("drop_area_y_max", fg.drop_area_y_max),
        ("recce_area_y_min", fg.recce_area_y_min),
        ("recce_area_y_max", fg.recce_area_y_max),
    ]
    area_ok = True
    area_vals: dict[str, float] = {}
    for name, val in area_fields:
        if val is None:
            diag.errors.append(
                f"field_geometry.{name} is required for schema v3"
            )
            area_ok = False
        elif not _is_finite_number(val):
            diag.errors.append(
                f"field_geometry.{name} must be a finite number, got {val!r}"
            )
            area_ok = False
        else:
            area_vals[name] = float(val)

    if area_ok:
        dmin = area_vals["drop_area_y_min"]
        dmax = area_vals["drop_area_y_max"]
        rmin = area_vals["recce_area_y_min"]
        rmax = area_vals["recce_area_y_max"]
        dc = float(fg.drop_center_y_m)
        rc = float(fg.recce_center_y_m)

        if dmin >= dmax:
            diag.errors.append(
                f"field_geometry.drop_area_y_min_m ({dmin}) must be"
                f" < drop_area_y_max_m ({dmax})"
            )
        if dc < dmin or dc > dmax:
            diag.errors.append(
                f"field_geometry.drop_center_y_m ({dc}) must be in"
                f" [drop_area_y_min_m ({dmin}), drop_area_y_max_m ({dmax})]"
            )
        if dmin < 0:
            diag.errors.append(
                f"field_geometry.drop_area_y_min_m must be >= 0, got {dmin}"
            )
        if rmin >= rmax:
            diag.errors.append(
                f"field_geometry.recce_area_y_min_m ({rmin}) must be"
                f" < recce_area_y_max_m ({rmax})"
            )
        if rc < rmin or rc > rmax:
            diag.errors.append(
                f"field_geometry.recce_center_y_m ({rc}) must be in"
                f" [recce_area_y_min_m ({rmin}), recce_area_y_max_m ({rmax})]"
            )
        if rmin < 0:
            diag.errors.append(
                f"field_geometry.recce_area_y_min_m must be >= 0, got {rmin}"
            )
        if dmax >= rmin:
            diag.errors.append(
                f"field_geometry.drop_area_y_max_m ({dmax}) must be"
                f" < recce_area_y_min_m ({rmin})"
            )

    # -- drop_scan --------------------------------------------------------
    ds = profile.drop_scan
    if ds is None:
        diag.errors.append("drop_scan is required for schema v3")
    else:
        if len(ds.waypoints) != 4:
            diag.errors.append(
                f"drop_scan must have exactly 4 waypoints, got {len(ds.waypoints)}"
            )
        lane = float(fg.lane_half_width_m) if _is_finite_number(fg.lane_half_width_m) else 100.0
        coords = set()
        for i, wp in enumerate(ds.waypoints):
            if not _is_finite_number(wp.x_m):
                diag.errors.append(
                    f"drop_scan.waypoints[{i}].x_m must be a finite number, "
                    f"got {wp.x_m!r}"
                )
            elif wp.x_m < -lane or wp.x_m > lane:
                diag.errors.append(
                    f"drop_scan.waypoints[{i}].x_m ({wp.x_m}) out of"
                    f" lane [-{lane}, {lane}]"
                )
            if not _is_finite_number(wp.y_m):
                diag.errors.append(
                    f"drop_scan.waypoints[{i}].y_m must be a finite number, "
                    f"got {wp.y_m!r}"
                )
            elif area_ok and (wp.y_m < dmin or wp.y_m > dmax):
                diag.errors.append(
                    f"drop_scan.waypoints[{i}].y_m ({wp.y_m}) out of"
                    f" drop area [{dmin}, {dmax}]"
                )
            if not _is_finite_number(wp.altitude_m):
                diag.errors.append(
                    f"drop_scan.waypoints[{i}].altitude_m must be a finite"
                    f" number, got {wp.altitude_m!r}"
                )
            elif wp.altitude_m <= 0.0:
                diag.errors.append(
                    f"drop_scan.waypoints[{i}].altitude_m must be > 0,"
                    f" got {wp.altitude_m}"
                )
            if (
                _is_finite_number(wp.x_m)
                and _is_finite_number(wp.y_m)
                and _is_finite_number(wp.altitude_m)
            ):
                coords.add((
                    float(wp.x_m), float(wp.y_m), float(wp.altitude_m)
                ))
        if len(coords) < 2:
            diag.errors.append("drop_scan.waypoints must not be all identical")

    # -- gps_quality ------------------------------------------------------
    gq = profile.gps_quality
    if not _is_strict_int(gq.min_fix_type):
        diag.errors.append(
            f"gps_quality.min_fix_type must be a strict integer, "
            f"got {gq.min_fix_type!r}"
        )
    elif gq.min_fix_type < 3:
        diag.errors.append(
            f"gps_quality.min_fix_type must be >= 3, got {gq.min_fix_type}"
        )
    if not _is_strict_int(gq.min_satellites):
        diag.errors.append(
            f"gps_quality.min_satellites must be a strict integer, "
            f"got {gq.min_satellites!r}"
        )
    elif gq.min_satellites <= 0:
        diag.errors.append(
            f"gps_quality.min_satellites must be > 0, got {gq.min_satellites}"
        )
    if not _is_finite_number(gq.max_eph):
        diag.errors.append(
            f"gps_quality.max_eph must be a finite number, got {gq.max_eph!r}"
        )
    elif gq.max_eph <= 0.0:
        diag.errors.append(
            f"gps_quality.max_eph must be > 0, got {gq.max_eph}"
        )
    if not _is_finite_number(gq.max_epv):
        diag.errors.append(
            f"gps_quality.max_epv must be a finite number, got {gq.max_epv!r}"
        )
    elif gq.max_epv <= 0.0:
        diag.errors.append(
            f"gps_quality.max_epv must be > 0, got {gq.max_epv}"
        )

    # -- runtime_origin_sampling ------------------------------------------
    ros = profile.runtime_origin_sampling
    if ros is None:
        diag.errors.append("runtime_origin_sampling is required for schema v3")
    else:
        if not _is_strict_int(ros.min_samples):
            diag.errors.append(
                f"runtime_origin_sampling.min_samples must be a strict"
                f" integer, got {ros.min_samples!r}"
            )
        elif ros.min_samples < 3:
            diag.errors.append(
                f"runtime_origin_sampling.min_samples must be >= 3,"
                f" got {ros.min_samples}"
            )
        if not _is_finite_number(ros.sample_window_s):
            diag.errors.append(
                f"runtime_origin_sampling.sample_window_s must be a finite"
                f" number, got {ros.sample_window_s!r}"
            )
        elif ros.sample_window_s <= 0.0:
            diag.errors.append(
                f"runtime_origin_sampling.sample_window_s must be > 0,"
                f" got {ros.sample_window_s}"
            )
        if not _is_finite_number(ros.max_horizontal_spread_m):
            diag.errors.append(
                f"runtime_origin_sampling.max_horizontal_spread_m must be"
                f" a finite number, got {ros.max_horizontal_spread_m!r}"
            )
        elif ros.max_horizontal_spread_m <= 0.0:
            diag.errors.append(
                f"runtime_origin_sampling.max_horizontal_spread_m must be"
                f" > 0, got {ros.max_horizontal_spread_m}"
            )
        if not isinstance(ros.estimator, str) or ros.estimator != "median":
            diag.errors.append(
                f"runtime_origin_sampling.estimator must be 'median',"
                f" got {ros.estimator!r}"
            )

    # -- binding_policy ---------------------------------------------------
    bp = profile.binding_policy
    bp_ok = True
    if not _is_finite_number(bp.min_baseline_m):
        diag.errors.append(
            f"binding_policy.min_baseline_m must be a finite number,"
            f" got {bp.min_baseline_m!r}"
        )
        bp_ok = False
    elif bp.min_baseline_m <= 0.0:
        diag.errors.append(
            f"binding_policy.min_baseline_m must be > 0, got {bp.min_baseline_m}"
        )
        bp_ok = False
    if not _is_finite_number(bp.warn_baseline_below_m):
        diag.errors.append(
            f"binding_policy.warn_baseline_below_m must be a finite number,"
            f" got {bp.warn_baseline_below_m!r}"
        )
        bp_ok = False
    if bp_ok and bp.warn_baseline_below_m <= bp.min_baseline_m:
        diag.errors.append(
            f"binding_policy.warn_baseline_below_m"
            f" ({bp.warn_baseline_below_m}) must be"
            f" > min_baseline_m ({bp.min_baseline_m})"
        )

    # -- unknown top-level keys → warning ----------------------------------
    if profile.extra:
        for key in sorted(profile.extra.keys()):
            diag.warnings.append(
                f"Unknown top-level key '{key}' (retained for forward compatibility)"
            )


# ---------------------------------------------------------------------------
# centerline fitting
# ---------------------------------------------------------------------------


def fit_centerline(
    anchor: AnchorPoint,
    centerline_points: List[CenterlinePoint],
    binding_policy: BindingPolicy,
) -> CenterlineFitResult:
    """Fit a straight centerline through anchor + centerline_points.

    Uses ENU coordinates relative to anchor.  Direction is determined by
    principal component analysis (PCA) of the centerline points, with the
    sign chosen so that the positive direction points from anchor toward
    the farthest centerline point.

    Returns a :class:`CenterlineFitResult` with heading, residuals, and
    diagnostics.
    """
    diag = FieldProfileDiagnostics()

    if len(centerline_points) < 4:
        diag.errors.append("At least 4 centerline_points required for fitting")
        return CenterlineFitResult(
            field_heading_yaw_rad=0.0,
            field_heading_deg=0.0,
            baseline_m=0.0,
            point_residuals=[],
            max_residual_m=0.0,
            rms_residual_m=0.0,
            diagnostics=diag,
        )

    # Convert all centerline points to ENU relative to anchor
    enu_pts: List[Tuple[float, float]] = []
    for pt in centerline_points:
        dn, de = _gps_enu_deltas(anchor.lat, anchor.lon, pt.lat, pt.lon)
        enu_pts.append((dn, de))

    n = len(enu_pts)

    # Compute centroid
    mean_n = sum(dn for dn, de in enu_pts) / n
    mean_e = sum(de for dn, de in enu_pts) / n

    # Compute covariance (centered at anchor, not centroid, to ensure
    # the line passes through the anchor).
    # We fit a line through the origin (anchor) with direction (u_n, u_e).
    # The direction is the dominant eigenvector of the scatter matrix.
    cov_nn = sum(dn * dn for dn, de in enu_pts)
    cov_ee = sum(de * de for dn, de in enu_pts)
    cov_ne = sum(dn * de for dn, de in enu_pts)

    # Eigenvalues of [[cov_nn, cov_ne], [cov_ne, cov_ee]]
    trace = cov_nn + cov_ee
    det = cov_nn * cov_ee - cov_ne * cov_ne
    discriminant = max(0.0, trace * trace - 4.0 * det)
    lambda1 = (trace + math.sqrt(discriminant)) / 2.0

    # Eigenvector for lambda1 (dominant): (cov_nn - lambda1, cov_ne) is not
    # the right approach.  Instead, solve (cov - lambda*I) * v = 0.
    # For 2x2: direction is (cov_ne, lambda1 - cov_nn) or (lambda1 - cov_ee, cov_ne).
    if abs(cov_ne) > 1e-15:
        u_n = cov_ne
        u_e = lambda1 - cov_nn
    elif cov_nn >= cov_ee:
        u_n = 1.0
        u_e = 0.0
    else:
        u_n = 0.0
        u_e = 1.0

    # Normalize
    norm = math.hypot(u_n, u_e)
    if norm < 1e-15:
        diag.errors.append("Centerline points are degenerate (zero scatter)")
        return CenterlineFitResult(
            field_heading_yaw_rad=0.0,
            field_heading_deg=0.0,
            baseline_m=0.0,
            point_residuals=[],
            max_residual_m=0.0,
            rms_residual_m=0.0,
            diagnostics=diag,
        )
    u_n /= norm
    u_e /= norm

    # Ensure direction points from anchor toward the farthest centerline point
    farthest_idx = max(range(n), key=lambda i: math.hypot(*enu_pts[i]))
    fn, fe = enu_pts[farthest_idx]
    if u_n * fn + u_e * fe < 0.0:
        u_n = -u_n
        u_e = -u_e

    # Heading: bearing from anchor in direction (u_n, u_e)
    field_heading_yaw_rad = math.atan2(u_e, u_n)
    field_heading_deg = math.degrees(field_heading_yaw_rad)

    # Baseline: distance to farthest point
    baseline_m = math.hypot(fn, fe)

    # Compute perpendicular residuals for each point
    point_residuals: List[float] = []
    for dn, de in enu_pts:
        # Project onto direction
        along = dn * u_n + de * u_e
        # Perpendicular residual = distance from point to line
        perp = math.hypot(dn - along * u_n, de - along * u_e)
        point_residuals.append(perp)

    max_residual_m = max(point_residuals) if point_residuals else 0.0
    rms_residual_m = math.sqrt(sum(r * r for r in point_residuals) / n) if n > 0 else 0.0

    # Check against binding policy
    if max_residual_m > binding_policy.max_centerline_residual_m:
        diag.errors.append(
            f"Max centerline residual {max_residual_m:.3f} m exceeds "
            f"max_centerline_residual_m {binding_policy.max_centerline_residual_m:.3f} m"
        )
    elif max_residual_m > binding_policy.warn_centerline_residual_m:
        diag.warnings.append(
            f"Max centerline residual {max_residual_m:.3f} m exceeds "
            f"warn_centerline_residual_m {binding_policy.warn_centerline_residual_m:.3f} m"
        )

    # Diagnostic-only: compare expected_field_y_m with projection
    for i, pt in enumerate(centerline_points):
        if pt.expected_field_y_m is not None:
            dn, de = enu_pts[i]
            along = dn * u_n + de * u_e
            diff = abs(along - pt.expected_field_y_m)
            if diff > 1.0:
                diag.warnings.append(
                    f"centerline_points[{i}] ({pt.name}) expected_field_y_m={pt.expected_field_y_m:.2f} "
                    f"but fitted distance along line is {along:.2f} m (diff {diff:.2f} m)"
                )

    return CenterlineFitResult(
        field_heading_yaw_rad=field_heading_yaw_rad,
        field_heading_deg=field_heading_deg,
        baseline_m=baseline_m,
        point_residuals=point_residuals,
        max_residual_m=max_residual_m,
        rms_residual_m=rms_residual_m,
        diagnostics=diag,
    )


# ===================================================================
# internal helpers — shared
# ===================================================================


def _parse_common_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse fields shared by both schema versions."""
    _require_str(data, "profile_id")
    _require_str(data, "name")
    return {
        "schema_version": _parse_schema_version(data),
        "profile_id": str(data["profile_id"]),
        "name": str(data["name"]),
        "coordinate_convention": _parse_coordinate_convention(data),
    }


def _parse_schema_version(data: Dict[str, Any]) -> int:
    try:
        raw_sv = data.get("schema_version", 2)
        if raw_sv is None:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(errors=["schema_version is None"])
            )
        if isinstance(raw_sv, bool):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(errors=["schema_version must be a number, got bool"])
            )
        if not isinstance(raw_sv, (int, float)):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"schema_version must be a number, got {type(raw_sv).__name__}"]
                )
            )
        fv = float(raw_sv)
        if not math.isfinite(fv):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(errors=[f"schema_version is not finite: {fv}"])
            )
        if fv != math.floor(fv):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(errors=[f"schema_version must be an integer, got {fv}"])
            )
        return int(fv)
    except FieldProfileValidationError:
        raise
    except (ValueError, TypeError) as exc:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"schema_version invalid: {exc}"])
        )


def _require_str(data: Dict[str, Any], key: str) -> None:
    if key not in data or data[key] is None or not isinstance(data[key], str) or not data[key].strip():
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"'{key}' is required and must be a non-empty string"])
        )


def _require_in_obj(obj: Dict[str, Any], key: str) -> Any:
    """Require a key to be present in *obj* (return raw value)."""
    if key not in obj:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"'{key}' is required but missing"])
        )
    return obj[key]


def _require_float_in_obj(obj: Dict[str, Any], key: str, path: str) -> float:
    if key not in obj:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path}.{key} is required but missing"])
        )
    val = obj[key]
    if val is None:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path}.{key} is None"])
        )
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"{path}.{key} must be a number, got {type(val).__name__}"]
            )
        )
    fval = float(val)
    if not math.isfinite(fval):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path}.{key} is not finite: {fval}"])
        )
    return fval


def _require_int_nonneg(val: Any, path: str) -> int:
    if val is None:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path} is None"])
        )
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"{path} must be a number, got {type(val).__name__}"]
            )
        )
    fval = float(val)
    if not math.isfinite(fval):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path} is not finite: {fval}"])
        )
    if fval < 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path} must be >= 0, got {fval}"])
        )
    if fval != math.floor(fval):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"{path} must be an integer, got {fval}"]
            )
        )
    return int(fval)


def _require_float_nonneg(val: Any, path: str) -> float:
    if val is None:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path} is None"])
        )
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=[f"{path} must be a number, got {type(val).__name__}"]
            )
        )
    fval = float(val)
    if not math.isfinite(fval):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path} is not finite: {fval}"])
        )
    if fval < 0.0:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path} must be >= 0, got {fval}"])
        )
    return fval


def _parse_coordinate_convention(data: Dict[str, Any]) -> Dict[str, str]:
    if "coordinate_convention" in data and data["coordinate_convention"] is None:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=["coordinate_convention is null"])
        )
    raw = data.get("coordinate_convention", None)
    if raw is None or not isinstance(raw, dict):
        if raw is not None:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"coordinate_convention must be a JSON object, got {type(raw).__name__}"]
                )
            )
        return {
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        }
    return {
        "field_x_positive": str(raw.get("field_x_positive", "right")),
        "field_y_positive": str(raw.get("field_y_positive", "forward")),
        "altitude_positive": str(raw.get("altitude_positive", "up")),
    }


def _parse_gps_quality_thresholds(data: Dict[str, Any]) -> GpsQualityThresholds:
    if "gps_quality" in data and data["gps_quality"] is None:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=["gps_quality is null"])
        )
    raw = data.get("gps_quality", None)
    if raw is None or not isinstance(raw, dict):
        if raw is not None:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"gps_quality must be a JSON object, got {type(raw).__name__}"]
                )
            )
        return GpsQualityThresholds()

    min_fix_type = _require_int_nonneg(
        raw.get("min_fix_type", 3), "gps_quality.min_fix_type"
    )
    min_satellites = _require_int_nonneg(
        raw.get("min_satellites", 10), "gps_quality.min_satellites"
    )
    max_eph = _require_float_nonneg(raw.get("max_eph", 2.5), "gps_quality.max_eph")
    max_epv = _require_float_nonneg(raw.get("max_epv", 5.0), "gps_quality.max_epv")

    return GpsQualityThresholds(
        min_fix_type=min_fix_type,
        min_satellites=min_satellites,
        max_eph=max_eph,
        max_epv=max_epv,
    )


def _parse_field_geometry(data: Dict[str, Any]) -> FieldGeometry:
    raw = data.get("field_geometry", None)
    if raw is None or not isinstance(raw, dict):
        if raw is not None:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"field_geometry must be a JSON object, got {type(raw).__name__}"]
                )
            )
        return FieldGeometry()

    lane = float(raw.get("lane_half_width_m", 4.0))
    drop_y = float(raw.get("drop_center_y_m", 32.5))
    recce_y = float(raw.get("recce_center_y_m", 57.5))
    return FieldGeometry(
        lane_half_width_m=lane,
        drop_center_y_m=drop_y,
        recce_center_y_m=recce_y,
        drop_area_y_min=raw.get("drop_area_y_min", 30.0),
        drop_area_y_max=raw.get("drop_area_y_max", 35.0),
        recce_area_y_min=raw.get("recce_area_y_min", 55.0),
        recce_area_y_max=raw.get("recce_area_y_max", 60.0),
    )


def _parse_binding_policy(data: Dict[str, Any]) -> BindingPolicy:
    raw = data.get("binding_policy", None)
    if raw is None or not isinstance(raw, dict):
        if raw is not None:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"binding_policy must be a JSON object, got {type(raw).__name__}"]
                )
            )
        return BindingPolicy()

    return BindingPolicy(
        max_start_error_m=float(raw.get("max_start_error_m", 3.0)),
        warn_start_error_m=float(raw.get("warn_start_error_m", 1.5)),
        max_centerline_residual_m=float(raw.get("max_centerline_residual_m", 2.5)),
        warn_centerline_residual_m=float(raw.get("warn_centerline_residual_m", 1.5)),
        min_baseline_m=float(raw.get("min_baseline_m", 30.0)),
        warn_baseline_below_m=float(raw.get("warn_baseline_below_m", 50.0)),
    )


# ===================================================================
# internal helpers — safe type checks for direct-object validation
# ===================================================================


def _is_finite_number(value: Any) -> bool:
    """True if *value* is int or float (not bool) and finite."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_strict_int(value: Any) -> bool:
    """True if *value* is int and not bool."""
    return isinstance(value, int) and not isinstance(value, bool)


# ===================================================================
# internal helpers — validation
# ===================================================================


def _validate_coordinate_convention(
    convention: Dict[str, str], diag: FieldProfileDiagnostics
) -> None:
    expected = {
        "field_x_positive": "right",
        "field_y_positive": "forward",
        "altitude_positive": "up",
    }
    for key, expected_value in expected.items():
        actual = convention.get(key, "")
        if actual != expected_value:
            diag.errors.append(
                f"coordinate_convention.{key} must be '{expected_value}', got '{actual}'"
            )
