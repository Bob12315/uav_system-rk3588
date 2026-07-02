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
from typing import Any, Dict, List, Optional, Tuple

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
normalise to exactly 0.0."""

LR_COINCIDENT_M = 1e-6
"""Distance below which left_check and right_check are considered coincident
(degenerate geometry → hard error)."""

LR_TOO_CLOSE_WARN_M = 1.0
"""Distance below which left_check and right_check trigger a proximity warning."""


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

    Performs only structural conversion — no semantic validation.
    Call :func:`validate_field_profile` afterwards.
    """
    _require_str(data, "profile_id")
    _require_str(data, "name")

    # Track unknown top-level keys for forward compatibility.
    _KNOWN_KEYS = {
        "schema_version", "profile_id", "name", "created_at",
        "coordinate_convention", "points", "gps_quality",
    }
    extra: Dict[str, Any] = {}
    for key, value in data.items():
        if key not in _KNOWN_KEYS:
            extra[key] = value

    schema_version = int(data.get("schema_version", 1))
    profile_id = str(data["profile_id"])
    name = str(data["name"])
    created_at = str(data.get("created_at", ""))
    coordinate_convention = _parse_coordinate_convention(data)
    gps_quality = _parse_gps_quality_thresholds(data)

    raw_points: Dict[str, Any] = data.get("points", {}) or {}
    points: Dict[str, FieldProfilePoint] = {}
    for key, raw_pt in raw_points.items():
        if not isinstance(raw_pt, dict):
            raise FieldProfileValidationError(
                FieldProfileDiagnostics(
                    errors=[f"points.{key} must be a JSON object, got {type(raw_pt).__name__}"]
                )
            )
        points[key] = FieldProfilePoint(
            name=str(raw_pt.get("name", key)),
            role=str(raw_pt.get("role", key)),
            lat=float(raw_pt.get("lat", 0.0)),
            lon=float(raw_pt.get("lon", 0.0)),
            field_x_m=float(raw_pt.get("field_x_m", 0.0)),
            field_y_m=float(raw_pt.get("field_y_m", 0.0)),
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

    # Early exit if origin/forward are missing — remaining checks need them.
    if not diag.ok:
        return diag

    origin = profile.origin
    forward = profile.forward

    # -- validate every point's numeric fields -----------------------------
    for key, pt in profile.points.items():
        _validate_point_numerics(key, pt, diag)

    # If any numeric field is non-finite we cannot safely do geometry checks.
    if not diag.ok:
        return diag

    # -- origin field_x / field_y should be 0 -----------------------------
    if abs(origin.field_x_m) > ORIGIN_EPSILON_M:
        diag.warnings.append(
            f"origin field_x_m is {origin.field_x_m}, normalised to 0.0"
        )
        origin.field_x_m = 0.0
    if abs(origin.field_y_m) > ORIGIN_EPSILON_M:
        diag.warnings.append(
            f"origin field_y_m is {origin.field_y_m}, normalised to 0.0"
        )
        origin.field_y_m = 0.0

    # -- O→F GPS baseline --------------------------------------------------
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

    # -- left_check / right_check (optional) -------------------------------
    left = profile.left_check
    right = profile.right_check

    if left is not None:
        if left.field_x_m >= 0.0:
            diag.errors.append(
                f"left_check field_x_m must be negative, got {left.field_x_m}"
            )
    if right is not None:
        if right.field_x_m <= 0.0:
            diag.errors.append(
                f"right_check field_x_m must be positive, got {right.field_x_m}"
            )

    # L/R swapped / same-side checks (only meaningful when both exist)
    if left is not None and right is not None:
        # If we already flagged an individual sign error, skip cross-checks
        # to avoid duplicate / confusing messages.
        individual_ok = (left.field_x_m < 0.0) and (right.field_x_m > 0.0)
        if not individual_ok:
            # Already caught above — but add a consolidated message.
            if left.field_x_m > 0.0 and right.field_x_m < 0.0:
                diag.errors.append("L and R appear swapped (signs are inverted)")
            elif left.field_x_m > 0.0 and right.field_x_m > 0.0:
                diag.errors.append("L and R are on the same side (both positive)")
            elif left.field_x_m < 0.0 and right.field_x_m < 0.0:
                diag.errors.append("L and R are on the same side (both negative)")
        else:
            # Proximity / degeneracy checks
            lr_distance = math.hypot(
                left.field_x_m - right.field_x_m,
                left.field_y_m - right.field_y_m,
            )
            if lr_distance < LR_COINCIDENT_M:
                diag.errors.append(
                    f"L and R are coincident (distance {lr_distance:.6f} m)"
                )
            elif lr_distance < LR_TOO_CLOSE_WARN_M:
                diag.warnings.append(
                    f"L and R are very close ({lr_distance:.3f} m < {LR_TOO_CLOSE_WARN_M} m)"
                )

    # -- unknown top-level keys → warning (forward-compatible) -------------
    if profile.extra:
        for key in sorted(profile.extra.keys()):
            diag.warnings.append(f"Unknown top-level key '{key}' (retained for forward compatibility)")

    return diag


# ===================================================================
# internal helpers
# ===================================================================


def _require_str(data: Dict[str, Any], key: str) -> None:
    if key not in data or not isinstance(data[key], str) or not data[key].strip():
        raise FieldProfileValidationError(
            FieldProfileDiagnostics(errors=[f"'{key}' is required and must be a non-empty string"])
        )


def _parse_coordinate_convention(data: Dict[str, Any]) -> Dict[str, str]:
    raw = data.get("coordinate_convention", None)
    if raw is None or not isinstance(raw, dict):
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


def _parse_gps_quality_thresholds(data: Dict[str, Any]) -> GpsQualityThresholds:
    raw = data.get("gps_quality", None)
    if raw is None or not isinstance(raw, dict):
        return GpsQualityThresholds()
    return GpsQualityThresholds(
        min_fix_type=int(raw.get("min_fix_type", 3)),
        min_satellites=int(raw.get("min_satellites", 10)),
        max_eph=float(raw.get("max_eph", 2.5)),
        max_epv=float(raw.get("max_epv", 5.0)),
    )


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
