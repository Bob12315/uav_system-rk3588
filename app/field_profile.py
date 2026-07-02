"""Field Profile — pure logic for loading, validating, and binding O/F/L/R
field profiles.

This module does NOT write RuntimeContext, does NOT confirm/freeze, and does
NOT send MAVLink commands.  It is a pure data-and-math layer.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

# Phase B: temporary private imports from field_reference.
# A future phase may make these public or extract them to a shared utility.
from .field_reference import (  # noqa: E501  (Phase B private import)
    EARTH_RADIUS_M,
    MIN_GPS_BASELINE_M,
    RECOMMENDED_GPS_BASELINE_M,
    _gps_bearing_rad,
    _gps_distance_m,
    _gps_enu_deltas,
)


# ---------------------------------------------------------------------------
# constants local to this module
# ---------------------------------------------------------------------------

ORIGIN_EPSILON_M = 1e-9
"""Maximum |field_x_m| / |field_y_m| for an origin point before we warn and
normalise to exactly 0.0.  Values above this but below MAX_ORIGIN_DEVIATION_M
are normalised with a warning."""

MAX_ORIGIN_DEVIATION_M = 0.1
"""Maximum |field_x_m| / |field_y_m| for an origin point.  Values exceeding
this are a hard error — the origin is fundamentally wrong."""

LR_COINCIDENT_M = 1e-6
"""Distance below which left_check and right_check are considered coincident
(degenerate geometry → hard error)."""

MIN_LR_GPS_BASELINE_M = 1.0
"""Minimum GPS-derived distance between left_check and right_check.
Below this → hard error (unsafe geometry)."""

DECLARED_POSITION_TOLERANCE_M = 1.0
"""Maximum allowed difference (metres) between GPS-derived FIELD coordinates
and the declared field_x_m / field_y_m in the profile JSON."""

FORWARD_X_TOLERANCE_M = 0.5
"""Maximum allowed |field_x_m| for the forward point — it must lie very
close to the O→F heading line."""


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
class FieldProfilePoint:
    """A single named point (O / F / L / R) within a field profile."""

    name: str
    role: str  # "origin", "forward", "left_check", "right_check"
    lat: float
    lon: float
    field_x_m: float
    field_y_m: float


@dataclass(slots=True)
class FieldProfile:
    """Deserialised, validated field profile.

    The ``points`` dict is keyed by role::

        {"origin": ..., "forward": ..., "left_check": ..., "right_check": ...}
    """

    schema_version: int
    profile_id: str
    name: str
    created_at: str
    coordinate_convention: Dict[str, str]
    points: Dict[str, FieldProfilePoint]
    gps_quality: GpsQualityThresholds = field(default_factory=GpsQualityThresholds)
    extra: Dict[str, Any] = field(default_factory=dict)
    """Unknown top-level JSON keys preserved for forward compatibility."""
    nested_unknowns: List[str] = field(default_factory=list)
    """Unknown keys discovered inside points / gps_quality / coordinate_convention
    objects.  Populated during parse; warned about during validate."""

    # ---- derived helpers (cached after first call) ----

    @property
    def origin(self) -> FieldProfilePoint:
        return self.points["origin"]

    @property
    def forward(self) -> FieldProfilePoint:
        return self.points["forward"]

    @property
    def left_check(self) -> Optional[FieldProfilePoint]:
        return self.points.get("left_check")

    @property
    def right_check(self) -> Optional[FieldProfilePoint]:
        return self.points.get("right_check")


# ---------------------------------------------------------------------------
# validation result helpers
# ---------------------------------------------------------------------------


@dataclass
class FieldProfileDiagnostics:
    """Collected errors and warnings from validation."""

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

    Every point MUST explicitly contain *role*, *lat*, *lon*,
    *field_x_m*, and *field_y_m*.  Missing / None / wrong-type /
    non-finite values raise :class:`FieldProfileValidationError` immediately.

    Call :func:`validate_field_profile` afterwards for semantic checks.
    """
    # -- top-level required strings ----------------------------------------
    _require_str(data, "profile_id")
    _require_str(data, "name")

    # Track unknown keys for forward compatibility.
    _TOP_KEYS = {
        "schema_version", "profile_id", "name", "created_at",
        "coordinate_convention", "points", "gps_quality",
    }
    extra: Dict[str, Any] = {}
    nested_unknowns: List[str] = []
    for key, value in data.items():
        if key not in _TOP_KEYS:
            extra[key] = value

    # -- schema_version: must be int-like, reject bool/None/NaN/Inf/string
    try:
        raw_sv = data.get("schema_version", 1)
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
    profile_id = str(data["profile_id"])
    name = str(data["name"])
    created_at = str(data.get("created_at", ""))
    coordinate_convention = _parse_coordinate_convention(data, nested_unknowns)
    gps_quality = _parse_gps_quality_thresholds(data, nested_unknowns)

    # -- points ------------------------------------------------------------
    raw_points: Any = data.get("points")
    if raw_points is None or not isinstance(raw_points, dict):
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(
                errors=["'points' is required and must be a JSON object"]
            )
        )

    _POINT_KEYS = {"name", "role", "lat", "lon", "field_x_m", "field_y_m"}
    points: Dict[str, FieldProfilePoint] = {}
    for dict_key, raw_pt in raw_points.items():
        if not isinstance(raw_pt, dict):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"points.{dict_key} must be a JSON object, got {type(raw_pt).__name__}"]
                )
            )

        # Detect unknown sub-keys inside the point object.
        for sub_key in raw_pt:
            if sub_key not in _POINT_KEYS:
                nested_unknowns.append(f"points.{dict_key}.{sub_key}")

        # Every point field is strictly required.
        role = _require_str_in_obj(raw_pt, "role", f"points.{dict_key}")
        lat = _require_float_in_obj(raw_pt, "lat", f"points.{dict_key}")
        lon = _require_float_in_obj(raw_pt, "lon", f"points.{dict_key}")
        fx = _require_float_in_obj(raw_pt, "field_x_m", f"points.{dict_key}")
        fy = _require_float_in_obj(raw_pt, "field_y_m", f"points.{dict_key}")
        pt_name = str(raw_pt.get("name", dict_key))

        # Dict key must match role.
        if role != dict_key:
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[
                        f"points.{dict_key} has role '{role}' but key must be '{dict_key}'"
                    ]
                )
            )

        points[dict_key] = FieldProfilePoint(
            name=pt_name,
            role=role,
            lat=lat,
            lon=lon,
            field_x_m=fx,
            field_y_m=fy,
        )

    return FieldProfile(
        schema_version=schema_version,
        profile_id=profile_id,
        name=name,
        created_at=created_at,
        coordinate_convention=coordinate_convention,
        points=points,
        gps_quality=gps_quality,
        extra=extra,
        nested_unknowns=nested_unknowns,
    )


def validate_field_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
    """Run all semantic validation checks on *profile*.

    Returns a :class:`FieldProfileDiagnostics` with collected errors and
    warnings.  Validation is **fail-early** for structural issues but
    **collects** as many semantic issues as practical.
    """
    diag = FieldProfileDiagnostics()

    # -- schema version --------------------------------------------------
    if profile.schema_version != 1:
        diag.errors.append(
            f"Unsupported schema_version {profile.schema_version} (only 1 is supported)"
        )

    # -- profile_id -------------------------------------------------------
    if not profile.profile_id.strip():
        diag.errors.append("profile_id must be non-empty")

    # -- coordinate convention --------------------------------------------
    _validate_coordinate_convention(profile.coordinate_convention, diag)

    # -- mandatory points -------------------------------------------------
    if "origin" not in profile.points:
        diag.errors.append("Missing required point: origin")
    if "forward" not in profile.points:
        diag.errors.append("Missing required point: forward")

    if not diag.ok:
        return diag

    origin = profile.origin
    forward = profile.forward

    # -- validate every point's numeric fields -----------------------------
    for key, pt in profile.points.items():
        _validate_point_numerics(key, pt, diag)

    if not diag.ok:
        return diag

    # -- origin field_x / field_y should be 0 -----------------------------
    if abs(origin.field_x_m) > MAX_ORIGIN_DEVIATION_M:
        diag.errors.append(
            f"origin field_x_m is {origin.field_x_m}, far from 0 (max {MAX_ORIGIN_DEVIATION_M})"
        )
    elif abs(origin.field_x_m) > ORIGIN_EPSILON_M:
        diag.warnings.append(
            f"origin field_x_m is {origin.field_x_m}, normalised to 0.0"
        )
        origin.field_x_m = 0.0
    if abs(origin.field_y_m) > MAX_ORIGIN_DEVIATION_M:
        diag.errors.append(
            f"origin field_y_m is {origin.field_y_m}, far from 0 (max {MAX_ORIGIN_DEVIATION_M})"
        )
    elif abs(origin.field_y_m) > ORIGIN_EPSILON_M:
        diag.warnings.append(
            f"origin field_y_m is {origin.field_y_m}, normalised to 0.0"
        )
        origin.field_y_m = 0.0

    # -- O→F GPS baseline + heading ---------------------------------------
    baseline_m = _gps_distance_m(origin.lat, origin.lon, forward.lat, forward.lon)
    if baseline_m < MIN_GPS_BASELINE_M:
        diag.errors.append(
            f"O→F GPS baseline {baseline_m:.2f} m is below minimum "
            f"{MIN_GPS_BASELINE_M:.0f} m"
        )
    elif baseline_m < RECOMMENDED_GPS_BASELINE_M:
        diag.warnings.append(
            f"O→F GPS baseline {baseline_m:.2f} m is below recommended "
            f"{RECOMMENDED_GPS_BASELINE_M:.0f} m"
        )

    heading_rad = _gps_bearing_rad(origin.lat, origin.lon, forward.lat, forward.lon)

    # -- forward declared-coordinate checks --------------------------------
    if abs(forward.field_x_m) > FORWARD_X_TOLERANCE_M:
        diag.errors.append(
            f"forward field_x_m must be ≈0 (heading-aligned), got {forward.field_x_m}"
        )
    if forward.field_y_m <= 0.0:
        diag.errors.append(
            f"forward field_y_m must be > 0, got {forward.field_y_m}"
        )
    else:
        # Check forward declared field_y vs GPS-derived baseline.
        if abs(forward.field_y_m - baseline_m) > DECLARED_POSITION_TOLERANCE_M:
            diag.errors.append(
                f"forward field_y_m {forward.field_y_m} differs from GPS baseline "
                f"{baseline_m:.2f} by {abs(forward.field_y_m - baseline_m):.2f} m "
                f"(tolerance {DECLARED_POSITION_TOLERANCE_M} m)"
            )

    # -- left_check / right_check (optional) -------------------------------
    left = profile.left_check
    right = profile.right_check

    if left is not None or right is not None:
        _validate_lr_gps_geometry(profile, left, right, heading_rad, diag)

    # -- GPS quality thresholds self-validation ---------------------------
    _validate_gps_quality_thresholds(profile.gps_quality, diag)

    # -- unknown top-level keys → warning ----------------------------------
    if profile.extra:
        for key in sorted(profile.extra.keys()):
            diag.warnings.append(
                f"Unknown top-level key '{key}' (retained for forward compatibility)"
            )

    # -- nested unknown keys → warning -------------------------------------
    for msg in sorted(profile.nested_unknowns):
        diag.warnings.append(f"Unknown field '{msg}' (retained for forward compatibility)")

    return diag


# ===================================================================
# internal helpers — parsing
# ===================================================================


def _require_str(data: Dict[str, Any], key: str) -> None:
    if key not in data or data[key] is None or not isinstance(data[key], str) or not data[key].strip():
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"'{key}' is required and must be a non-empty string"])
        )


def _require_str_in_obj(obj: Dict[str, Any], key: str, path: str) -> str:
    if key not in obj:
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path}.{key} is required but missing"])
        )
    val = obj[key]
    if val is None or not isinstance(val, str) or not val.strip():
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"{path}.{key} must be a non-empty string, got {type(val).__name__}"])
        )
    return str(val)


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
    """Require *val* to be int-castable, finite, and >= 0."""
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
    """Require *val* to be a finite float >= 0."""
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


def _parse_coordinate_convention(
    data: Dict[str, Any], nested_unknowns: List[str]
) -> Dict[str, str]:
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
    _CONV_KEYS = {"field_x_positive", "field_y_positive", "altitude_positive"}
    for key in raw:
        if key not in _CONV_KEYS:
            nested_unknowns.append(f"coordinate_convention.{key}")
    return {
        "field_x_positive": str(raw.get("field_x_positive", "right")),
        "field_y_positive": str(raw.get("field_y_positive", "forward")),
        "altitude_positive": str(raw.get("altitude_positive", "up")),
    }


def _parse_gps_quality_thresholds(
    data: Dict[str, Any], nested_unknowns: List[str]
) -> GpsQualityThresholds:
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

    _GQ_KEYS = {"min_fix_type", "min_satellites", "max_eph", "max_epv"}
    for key in raw:
        if key not in _GQ_KEYS:
            nested_unknowns.append(f"gps_quality.{key}")

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


def _validate_gps_quality_thresholds(
    t: GpsQualityThresholds, diag: FieldProfileDiagnostics
) -> None:
    """Self-validate the threshold values (they should have been parsed strictly,
    but we double-check in case of programmatic construction)."""
    for name, val in [("min_fix_type", t.min_fix_type), ("min_satellites", t.min_satellites)]:
        if not isinstance(val, int) or val < 0:
            diag.errors.append(f"gps_quality.{name} must be a non-negative integer, got {val}")
    for name, val in [("max_eph", t.max_eph), ("max_epv", t.max_epv)]:
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(float(val)) or float(val) < 0.0:
            diag.errors.append(f"gps_quality.{name} must be finite and >= 0, got {val}")


def _validate_point_numerics(
    key: str, pt: FieldProfilePoint, diag: FieldProfileDiagnostics
) -> None:
    prefix = f"points.{key}"

    for attr in ("lat", "lon", "field_x_m", "field_y_m"):
        val = getattr(pt, attr)
        if not math.isfinite(val):
            diag.errors.append(f"{prefix}.{attr} is not finite: {val}")

    if pt.lat < -90.0 or pt.lat > 90.0:
        diag.errors.append(f"{prefix}.lat {pt.lat} out of range [-90, 90]")
    if pt.lon < -180.0 or pt.lon > 180.0:
        diag.errors.append(f"{prefix}.lon {pt.lon} out of range [-180, 180]")


def _project_gps_to_field(
    origin: FieldProfilePoint,
    pt: FieldProfilePoint,
    heading_rad: float,
) -> Tuple[float, float]:
    """Return (field_x_m, field_y_m) for *pt* by projecting its GPS position
    relative to *origin* into the FIELD frame defined by *heading_rad*."""
    d_north, d_east = _gps_enu_deltas(origin.lat, origin.lon, pt.lat, pt.lon)
    cos_h = math.cos(heading_rad)
    sin_h = math.sin(heading_rad)
    field_x = -d_north * sin_h + d_east * cos_h
    field_y = d_north * cos_h + d_east * sin_h
    return field_x, field_y


def _validate_lr_gps_geometry(
    profile: FieldProfile,
    left: Optional[FieldProfilePoint],
    right: Optional[FieldProfilePoint],
    heading_rad: float,
    diag: FieldProfileDiagnostics,
) -> None:
    """Validate L/R using BOTH declared and GPS-derived FIELD coordinates.

    Two-layer defence:
    1. Declared field_x_m sign checks (catches JSON typos).
    2. GPS-derived sign, cross-check, and proximity checks (authoritative).
    """
    origin = profile.origin

    gps_left_x: Optional[float] = None
    gps_left_y: Optional[float] = None
    gps_right_x: Optional[float] = None
    gps_right_y: Optional[float] = None

    # -- Layer 1: declared sign checks -----------------------------------
    if left is not None:
        if left.field_x_m >= 0.0:
            diag.errors.append(
                f"left_check declared field_x_m must be negative, got {left.field_x_m}"
            )
    if right is not None:
        if right.field_x_m <= 0.0:
            diag.errors.append(
                f"right_check declared field_x_m must be positive, got {right.field_x_m}"
            )

    # -- Layer 2: GPS-derived checks (authoritative) ---------------------
    if left is not None:
        gps_left_x, gps_left_y = _project_gps_to_field(origin, left, heading_rad)
        if gps_left_x >= 0.0:
            diag.errors.append(
                f"GPS-derived left_check field_x is {gps_left_x:.3f}, must be negative"
            )
        # Cross-check declared vs GPS-derived.
        if abs(gps_left_x - left.field_x_m) > DECLARED_POSITION_TOLERANCE_M:
            diag.errors.append(
                f"left_check declared field_x_m {left.field_x_m} differs from "
                f"GPS-derived {gps_left_x:.2f} by "
                f"{abs(gps_left_x - left.field_x_m):.2f} m "
                f"(tolerance {DECLARED_POSITION_TOLERANCE_M} m)"
            )
        if abs(gps_left_y - left.field_y_m) > DECLARED_POSITION_TOLERANCE_M:
            diag.errors.append(
                f"left_check declared field_y_m {left.field_y_m} differs from "
                f"GPS-derived {gps_left_y:.2f} by "
                f"{abs(gps_left_y - left.field_y_m):.2f} m "
                f"(tolerance {DECLARED_POSITION_TOLERANCE_M} m)"
            )

    if right is not None:
        gps_right_x, gps_right_y = _project_gps_to_field(origin, right, heading_rad)
        if gps_right_x <= 0.0:
            diag.errors.append(
                f"GPS-derived right_check field_x is {gps_right_x:.3f}, must be positive"
            )
        if abs(gps_right_x - right.field_x_m) > DECLARED_POSITION_TOLERANCE_M:
            diag.errors.append(
                f"right_check declared field_x_m {right.field_x_m} differs from "
                f"GPS-derived {gps_right_x:.2f} by "
                f"{abs(gps_right_x - right.field_x_m):.2f} m "
                f"(tolerance {DECLARED_POSITION_TOLERANCE_M} m)"
            )
        if abs(gps_right_y - right.field_y_m) > DECLARED_POSITION_TOLERANCE_M:
            diag.errors.append(
                f"right_check declared field_y_m {right.field_y_m} differs from "
                f"GPS-derived {gps_right_y:.2f} by "
                f"{abs(gps_right_y - right.field_y_m):.2f} m "
                f"(tolerance {DECLARED_POSITION_TOLERANCE_M} m)"
            )

    # -- GPS-level cross-checks when both exist ----------------------------
    if left is not None and right is not None and gps_left_x is not None and gps_right_x is not None:
        # GPS-level swap / same-side
        if gps_left_x > 0.0 and gps_right_x < 0.0:
            diag.errors.append(
                "L/R GPS coordinates appear swapped (GPS-derived L.x > 0, R.x < 0)"
            )
        elif gps_left_x > 0.0 and gps_right_x > 0.0:
            diag.errors.append(
                "L/R GPS coordinates are on the same side (both GPS-derived x > 0)"
            )
        elif gps_left_x < 0.0 and gps_right_x < 0.0:
            diag.errors.append(
                "L/R GPS coordinates are on the same side (both GPS-derived x < 0)"
            )
        else:
            # Signs are correct → proximity / degeneracy on GPS coords.
            lr_dist = math.hypot(
                gps_left_x - gps_right_x, gps_left_y - gps_right_y
            )
            if lr_dist < LR_COINCIDENT_M:
                diag.errors.append(
                    f"L/R GPS positions are coincident (distance {lr_dist:.6f} m)"
                )
            elif lr_dist < MIN_LR_GPS_BASELINE_M:
                diag.errors.append(
                    f"L/R GPS positions are too close ({lr_dist:.3f} m < {MIN_LR_GPS_BASELINE_M} m)"
                )
