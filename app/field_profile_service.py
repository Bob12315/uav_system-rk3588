"""Field Profile Service — loads profiles and computes bind candidates.

This service is a **pure-logic** layer.  It does NOT write to
RuntimeContext, does NOT confirm/freeze, and does NOT send MAVLink
commands.  Callers receive a :class:`BindResult` and decide what to do
with it.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .field_profile import (
    FieldProfile,
    FieldProfileDiagnostics,
    FieldProfilePoint,
    FieldProfileValidationError,
    GpsQuality,
    GpsQualityThresholds,
    load_field_profile_json,
    validate_field_profile,
)
from .field_reference import (  # noqa: E501  (Phase B private import)
    _gps_bearing_rad,
    _gps_distance_m,
    _gps_enu_deltas,
)


# ---------------------------------------------------------------------------
# safe input parsers (no TypeError / ValueError leak)
# ---------------------------------------------------------------------------


def _safe_float(value: Any, label: str) -> Tuple[bool, float, Optional[str]]:
    """Parse *value* as a finite float.  Returns (ok, parsed, error).

    Rejects None, bool, str, non-numeric types, NaN, Inf.
    Never raises TypeError or ValueError.
    """
    if value is None:
        return False, 0.0, f"{label} is None"
    if isinstance(value, bool):
        return False, 0.0, f"{label} must be a number, got bool"
    if not isinstance(value, (int, float)):
        return False, 0.0, f"{label} must be a number, got {type(value).__name__}"
    try:
        fv = float(value)
    except (ValueError, TypeError):
        return False, 0.0, f"{label} cannot be converted to float: {value}"
    if not math.isfinite(fv):
        return False, 0.0, f"{label} is not finite: {fv}"
    return True, fv, None


def _safe_float_nonneg(value: Any, label: str) -> Tuple[bool, float, Optional[str]]:
    """Like :func:`_safe_float` but also requires >= 0."""
    ok, fv, err = _safe_float(value, label)
    if not ok:
        return ok, fv, err
    if fv < 0.0:
        return False, 0.0, f"{label} must be >= 0, got {fv}"
    return True, fv, None


def _safe_int_noneg(value: Any, label: str) -> Tuple[bool, int, Optional[str]]:
    """Parse *value* as a non-negative integer (exact, no truncation).

    Rejects None, bool, str, non-numeric, NaN, Inf, negative, fractional.
    Never raises TypeError or ValueError.
    """
    if value is None:
        return False, 0, f"{label} is None"
    if isinstance(value, bool):
        return False, 0, f"{label} must be a number, got bool"
    if not isinstance(value, (int, float)):
        return False, 0, f"{label} must be a number, got {type(value).__name__}"
    try:
        fv = float(value)
    except (ValueError, TypeError):
        return False, 0, f"{label} cannot be converted to number: {value}"
    if not math.isfinite(fv):
        return False, 0, f"{label} is not finite: {fv}"
    if fv < 0.0:
        return False, 0, f"{label} must be >= 0, got {fv}"
    if fv != math.floor(fv):
        return False, 0, f"{label} must be an integer, got {fv}"
    return True, int(fv), None


# ---------------------------------------------------------------------------
# bind result
# ---------------------------------------------------------------------------


@dataclass
class CheckPointResult:
    """Computed check-point position at bind time."""

    name: str
    role: str
    expected_field_x_m: float
    expected_field_y_m: float


@dataclass
class BindResult:
    """Result of :meth:`FieldProfileService.bind_profile_to_current_vehicle`.

    *ok* is ``True`` when GPS quality passes and geometry is computable.
    The caller is responsible for confirming / freezing / sending.
    """

    ok: bool
    profile_id: str
    origin_local_n_m: Optional[float] = None
    origin_local_e_m: Optional[float] = None
    origin_local_z_m: Optional[float] = None
    field_heading_yaw_rad: Optional[float] = None
    field_heading_deg: Optional[float] = None
    current_field_x_m: Optional[float] = None
    current_field_y_m: Optional[float] = None
    baseline_m: Optional[float] = None
    diagnostics: FieldProfileDiagnostics = field(default_factory=FieldProfileDiagnostics)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    gps_quality: Optional[GpsQuality] = None
    check_points: List[CheckPointResult] = field(default_factory=list)
    timestamp: Optional[float] = None


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------


class FieldProfileService:
    """Stateless service for loading and binding field profiles."""

    # ------------------------------------------------------------------
    # profile discovery & loading
    # ------------------------------------------------------------------

    @staticmethod
    def list_profiles(profile_dir: str) -> List[str]:
        """Return absolute paths to every ``*.json`` file under *profile_dir*."""
        if not os.path.isdir(profile_dir):
            return []
        results: List[str] = []
        for entry in sorted(os.listdir(profile_dir)):
            if entry.startswith("."):
                continue
            full = os.path.join(profile_dir, entry)
            if os.path.isfile(full) and entry.endswith(".json"):
                results.append(os.path.abspath(full))
        return results

    @staticmethod
    def load_profile(name_or_path: str, profile_dir: Optional[str] = None) -> FieldProfile:
        """Load and validate a field profile.  Rejects path traversal."""
        if os.path.isfile(name_or_path):
            return load_field_profile_json(name_or_path)

        if profile_dir is None:
            raise FileNotFoundError(
                f"Field profile not found: {name_or_path} (no profile_dir supplied)"
            )

        if not name_or_path.endswith(".json"):
            name_or_path = name_or_path + ".json"

        profile_dir_real = os.path.realpath(profile_dir)
        full_path = os.path.realpath(os.path.join(profile_dir, name_or_path))

        if not full_path.startswith(profile_dir_real + os.sep) and full_path != profile_dir_real:
            raise ValueError(f"Field profile path escapes profile_dir: {name_or_path}")

        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"Field profile not found: {full_path}")

        return load_field_profile_json(full_path)

    @staticmethod
    def validate_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
        """Re-validate an already-loaded profile."""
        return validate_field_profile(profile)

    # ------------------------------------------------------------------
    # binding
    # ------------------------------------------------------------------

    @staticmethod
    def bind_profile_to_current_vehicle(
        profile: FieldProfile,
        current_lat: Any = None,
        current_lon: Any = None,
        current_local_n_m: Any = None,
        current_local_e_m: Any = None,
        current_local_z_m: Any = None,
        gps_fix_type: Any = None,
        satellites_visible: Any = None,
        gps_eph: Any = None,
        gps_epv: Any = None,
        timestamp: Optional[float] = None,
    ) -> BindResult:
        """Compute a bind candidate.  All inputs are safely parsed — no
        TypeError or ValueError will leak.
        """
        errors: List[str] = []
        warnings: List[str] = []

        # -- re-validate profile -------------------------------------------
        profile_diag = validate_field_profile(profile)
        if not profile_diag.ok:
            errors.extend(profile_diag.errors)
            warnings.extend(profile_diag.warnings)
            return BindResult(
                ok=False, profile_id=profile.profile_id,
                diagnostics=FieldProfileDiagnostics(errors=list(errors), warnings=list(warnings)),
                warnings=list(warnings), errors=list(errors),
                timestamp=timestamp,
            )

        thresholds: GpsQualityThresholds = profile.gps_quality

        # -- safe-parse current_lat ----------------------------------------
        ok_lat, f_lat, err_lat = _safe_float(current_lat, "current_lat")
        if not ok_lat:
            errors.append(err_lat)
        elif f_lat < -90.0 or f_lat > 90.0:
            errors.append(f"current_lat {f_lat} out of range [-90, 90]")

        # -- safe-parse current_lon ----------------------------------------
        ok_lon, f_lon, err_lon = _safe_float(current_lon, "current_lon")
        if not ok_lon:
            errors.append(err_lon)
        elif f_lon < -180.0 or f_lon > 180.0:
            errors.append(f"current_lon {f_lon} out of range [-180, 180]")

        # -- safe-parse LOCAL_NED ------------------------------------------
        ok_n, f_n, err_n = _safe_float(current_local_n_m, "current_local_n_m")
        if not ok_n:
            errors.append(err_n)
        ok_e, f_e, err_e = _safe_float(current_local_e_m, "current_local_e_m")
        if not ok_e:
            errors.append(err_e)
        ok_z, f_z, err_z = _safe_float(current_local_z_m, "current_local_z_m")
        if not ok_z:
            errors.append(err_z)

        # -- safe-parse gps_fix_type (must be non-negative integer) ---------
        ok_fix, fix_int, err_fix = _safe_int_noneg(gps_fix_type, "gps_fix_type")
        if not ok_fix:
            errors.append(err_fix)

        # -- safe-parse satellites_visible (must be non-negative integer) ---
        ok_sats, sats_int, err_sats = _safe_int_noneg(satellites_visible, "satellites_visible")
        if not ok_sats:
            errors.append(err_sats)

        # -- safe-parse gps_eph / gps_epv (must be finite >= 0, or None) ---
        eph_ok: bool = False
        eph_val: float = 0.0
        if gps_eph is None:
            errors.append("GPS eph is missing")
        else:
            eph_ok, eph_val, err_eph = _safe_float_nonneg(gps_eph, "GPS eph")
            if not eph_ok:
                errors.append(err_eph)

        epv_ok: bool = False
        epv_val: float = 0.0
        if gps_epv is None:
            errors.append("GPS epv is missing")
        else:
            epv_ok, epv_val, err_epv = _safe_float_nonneg(gps_epv, "GPS epv")
            if not epv_ok:
                errors.append(err_epv)

        # -- GPS quality object -------------------------------------------
        gps_quality = GpsQuality(
            fix_type=fix_int if ok_fix else 0,
            satellites_visible=sats_int if ok_sats else 0,
            eph=eph_val if eph_ok else gps_eph,
            epv=epv_val if epv_ok else gps_epv,
        )

        # -- threshold checks (only when input parsed ok) ------------------
        if ok_fix and fix_int < thresholds.min_fix_type:
            errors.append(f"GPS fix_type {fix_int} < required {thresholds.min_fix_type}")
        if ok_sats and sats_int < thresholds.min_satellites:
            errors.append(f"GPS satellites {sats_int} < required {thresholds.min_satellites}")
        if eph_ok and eph_val > thresholds.max_eph:
            errors.append(f"GPS eph {eph_val} > max allowed {thresholds.max_eph}")
        if epv_ok and epv_val > thresholds.max_epv:
            errors.append(f"GPS epv {epv_val} > max allowed {thresholds.max_epv}")

        if errors:
            return BindResult(
                ok=False, profile_id=profile.profile_id,
                diagnostics=FieldProfileDiagnostics(errors=list(errors), warnings=list(warnings)),
                warnings=list(warnings), errors=list(errors),
                gps_quality=gps_quality, timestamp=timestamp,
            )

        # -- geometry (all inputs now known-safe) --------------------------
        origin = profile.origin
        forward = profile.forward

        d_north, d_east = _gps_enu_deltas(origin.lat, origin.lon, f_lat, f_lon)

        origin_local_n_m_val = f_n - d_north
        origin_local_e_m_val = f_e - d_east
        origin_local_z_m_val = f_z

        heading_rad = _gps_bearing_rad(origin.lat, origin.lon, forward.lat, forward.lon)
        heading_deg = math.degrees(heading_rad)

        cos_h = math.cos(heading_rad)
        sin_h = math.sin(heading_rad)
        current_field_x_m = -d_north * sin_h + d_east * cos_h
        current_field_y_m = d_north * cos_h + d_east * sin_h

        baseline_m = _gps_distance_m(origin.lat, origin.lon, forward.lat, forward.lon)

        check_points: List[CheckPointResult] = []
        for role in ("left_check", "right_check"):
            pt = profile.points.get(role)
            if pt is not None:
                check_points.append(CheckPointResult(
                    name=pt.name, role=pt.role,
                    expected_field_x_m=pt.field_x_m,
                    expected_field_y_m=pt.field_y_m,
                ))

        return BindResult(
            ok=True, profile_id=profile.profile_id,
            origin_local_n_m=origin_local_n_m_val,
            origin_local_e_m=origin_local_e_m_val,
            origin_local_z_m=origin_local_z_m_val,
            field_heading_yaw_rad=heading_rad,
            field_heading_deg=heading_deg,
            current_field_x_m=current_field_x_m,
            current_field_y_m=current_field_y_m,
            baseline_m=baseline_m,
            diagnostics=FieldProfileDiagnostics(errors=[], warnings=list(warnings)),
            warnings=list(warnings), errors=[],
            gps_quality=gps_quality,
            check_points=check_points,
            timestamp=timestamp,
        )
