"""Field Profile — pure logic for loading, validating, and binding
centerline-based field profiles.

This module does NOT write RuntimeContext, does NOT confirm/freeze, and does
NOT send MAVLink commands.  It is a pure data-and-math layer.

Schema version 2: takeoff-anchor + 4+ centerline GPS points.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .field_reference import (
    EARTH_RADIUS_M,
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
class FieldGeometry:
    """Field geometry parameters."""

    lane_half_width_m: float = 4.0
    drop_center_y_m: float = 30.0
    recce_center_y_m: float = 55.0
    drop_area_y_min: Optional[float] = None
    drop_area_y_max: Optional[float] = None
    recce_area_y_min: Optional[float] = None
    recce_area_y_max: Optional[float] = None


@dataclass(slots=True)
class BindingPolicy:
    """Binding error/warning thresholds."""

    max_start_error_m: float = 3.0
    warn_start_error_m: float = 1.5
    max_centerline_residual_m: float = 2.5
    warn_centerline_residual_m: float = 1.5


@dataclass(slots=True)
class FieldProfile:
    """Deserialised, validated field profile (schema v2 — centerline).

    Key differences from v1:
    - ``anchor`` replaces ``origin``: lat/lon + field (0,0) anchor.
    - ``centerline_points`` replaces ``forward`` + ``left_check`` / ``right_check``:
      at least 4 GPS points along the centerline.
    - ``field_geometry`` contains lane/drop/recce dimensions.
    - ``binding_policy`` contains error/warning thresholds.
    """

    schema_version: int
    profile_id: str
    name: str
    coordinate_convention: Dict[str, str]
    anchor: AnchorPoint
    centerline_points: List[CenterlinePoint]
    gps_quality: GpsQualityThresholds = field(default_factory=GpsQualityThresholds)
    field_geometry: FieldGeometry = field(default_factory=FieldGeometry)
    binding_policy: BindingPolicy = field(default_factory=BindingPolicy)
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
    """Construct a :class:`FieldProfile` from a raw JSON dict (schema v2)."""
    _TOP_KEYS = {
        "schema_version", "profile_id", "name", "created_at",
        "coordinate_convention", "anchor", "centerline_points",
        "gps_quality", "field_geometry", "binding_policy",
    }
    extra: Dict[str, Any] = {}
    for key, value in data.items():
        if key not in _TOP_KEYS:
            extra[key] = value

    # -- schema_version --------------------------------------------------
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
        schema_version = int(fv)
    except FieldProfileValidationError:
        raise
    except (ValueError, TypeError) as exc:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"schema_version invalid: {exc}"])
        )

    _require_str(data, "profile_id")
    _require_str(data, "name")

    profile_id = str(data["profile_id"])
    name = str(data["name"])
    coordinate_convention = _parse_coordinate_convention(data)

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

    # -- gps_quality -----------------------------------------------------
    gps_quality = _parse_gps_quality_thresholds(data)

    # -- field_geometry --------------------------------------------------
    field_geometry = _parse_field_geometry(data)

    # -- binding_policy --------------------------------------------------
    binding_policy = _parse_binding_policy(data)

    return FieldProfile(
        schema_version=schema_version,
        profile_id=profile_id,
        name=name,
        coordinate_convention=coordinate_convention,
        anchor=anchor,
        centerline_points=centerline_points,
        gps_quality=gps_quality,
        field_geometry=field_geometry,
        binding_policy=binding_policy,
        extra=extra,
    )


def validate_field_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
    """Run all semantic validation checks on *profile*."""
    diag = FieldProfileDiagnostics()

    # -- schema version --------------------------------------------------
    if profile.schema_version != 2:
        diag.errors.append(
            f"Unsupported schema_version {profile.schema_version} (only 2 is supported)"
        )

    # -- profile_id -------------------------------------------------------
    if not profile.profile_id.strip():
        diag.errors.append("profile_id must be non-empty")

    # -- coordinate convention --------------------------------------------
    _validate_coordinate_convention(profile.coordinate_convention, diag)

    # -- anchor -----------------------------------------------------------
    anchor = profile.anchor
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
        return diag

    # -- centerline fitting sanity ---------------------------------------
    # Compute ENU coordinates relative to anchor
    enu_points: List[Tuple[float, float]] = []
    for pt in profile.centerline_points:
        dn, de = _gps_enu_deltas(anchor.lat, anchor.lon, pt.lat, pt.lon)
        enu_points.append((dn, de))

    # All points must be at a meaningful distance from anchor
    min_dist = min(
        math.hypot(dn, de) for dn, de in enu_points
    )
    if min_dist < 0.5:
        diag.errors.append(
            f"Minimum centerline point distance from anchor is {min_dist:.2f} m (< 0.5 m)"
        )

    # Check that centerline points are roughly collinear (quick cosine check
    # on farthest point direction)
    farthest_idx = max(range(len(enu_points)), key=lambda i: math.hypot(*enu_points[i]))
    farthest_n, farthest_e = enu_points[farthest_idx]
    farthest_dist = math.hypot(farthest_n, farthest_e)
    if farthest_dist > 0.0:
        ref_n = farthest_n / farthest_dist
        ref_e = farthest_e / farthest_dist
        for i, (dn, de) in enumerate(enu_points):
            d = math.hypot(dn, de)
            if d < 0.01:
                continue
            dot = (dn * ref_n + de * ref_e) / d
            if dot < 0.7:
                diag.warnings.append(
                    f"centerline_points[{i}] direction deviates from main axis (cos={dot:.2f})"
                )

    # -- field_geometry ---------------------------------------------------
    fg = profile.field_geometry
    if fg.lane_half_width_m <= 0.0:
        diag.errors.append(f"field_geometry.lane_half_width_m must be > 0, got {fg.lane_half_width_m}")
    if fg.drop_center_y_m <= 0.0:
        diag.errors.append(f"field_geometry.drop_center_y_m must be > 0, got {fg.drop_center_y_m}")
    if fg.recce_center_y_m <= 0.0:
        diag.errors.append(f"field_geometry.recce_center_y_m must be > 0, got {fg.recce_center_y_m}")

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

    return diag


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
# internal helpers — parsing
# ===================================================================


def _require_str(data: Dict[str, Any], key: str) -> None:
    if key not in data or data[key] is None or not isinstance(data[key], str) or not data[key].strip():
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"'{key}' is required and must be a non-empty string"])
        )


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
    drop_y = float(raw.get("drop_center_y_m", 30.0))
    recce_y = float(raw.get("recce_center_y_m", 55.0))
    return FieldGeometry(
        lane_half_width_m=lane,
        drop_center_y_m=drop_y,
        recce_center_y_m=recce_y,
        drop_area_y_min=raw.get("drop_area_y_min"),
        drop_area_y_max=raw.get("drop_area_y_max"),
        recce_area_y_min=raw.get("recce_area_y_min"),
        recce_area_y_max=raw.get("recce_area_y_max"),
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
    )


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
