"""Field Profile Service — loads profiles and computes bind candidates.

This service is a **pure-logic** layer.  It does NOT write to
RuntimeContext, does NOT confirm/freeze, and does NOT send MAVLink
commands.  Callers receive a :class:`BindResult` and decide what to do
with it.

Schema v2: takeoff anchor + centerline profile only.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .field_profile import (
    CenterlineFitResult,
    CenterlinePoint,
    FieldProfile,
    FieldProfileDiagnostics,
    FieldProfileValidationError,
    GpsQuality,
    GpsQualityThresholds,
    fit_centerline,
    load_field_profile_json,
    validate_field_profile,
)
from .field_reference import (
    EARTH_RADIUS_M,
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
# centerline residual row
# ---------------------------------------------------------------------------


@dataclass
class CenterlineResidualRow:
    """Per-point residual info for the bind result."""

    name: str
    lat: float
    lon: float
    residual_m: float
    expected_field_y_m: Optional[float] = None
    fitted_field_y_m: Optional[float] = None


# ---------------------------------------------------------------------------
# bind result
# ---------------------------------------------------------------------------


@dataclass
class BindResult:
    """Result of :meth:`FieldProfileService.takeoff_anchor_centerline`.

    *ok* is ``True`` when GPS quality passes, start error is within bounds,
    and centerline fitting succeeds within residual limits.
    """

    ok: bool
    profile_id: str
    origin_local_n_m: Optional[float] = None
    origin_local_e_m: Optional[float] = None
    origin_local_z_m: Optional[float] = None
    field_heading_yaw_rad: Optional[float] = None
    field_heading_deg: Optional[float] = None
    baseline_m: Optional[float] = None
    current_start_error_m: Optional[float] = None
    """Distance from current GPS to anchor GPS (diagnostic only)."""
    yaw_error_deg: Optional[float] = None
    """Difference between current yaw and field heading (display only)."""
    diagnostics: FieldProfileDiagnostics = field(default_factory=FieldProfileDiagnostics)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    gps_quality: Optional[GpsQuality] = None
    centerline_residuals: List[CenterlineResidualRow] = field(default_factory=list)
    max_residual_m: Optional[float] = None
    rms_residual_m: Optional[float] = None
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

    _PROFILE_ROOT_DIRS: list[str] = []  # set by SystemRunner / caller

    @staticmethod
    def load_profile(name_or_path: str, profile_dir: Optional[str] = None) -> FieldProfile:
        """Load and validate a field profile.  Strict path containment.

        - *profile_dir* is always required (no bare abs-path bypass).
        - Absolute paths, ``..``, and directory separators in
          *name_or_path* are rejected.
        - The resolved real path must be inside *profile_dir*.
        - Only ``.json`` files are accepted.
        """
        if profile_dir is None:
            raise FileNotFoundError(
                f"Field profile not found: {name_or_path} (no profile_dir supplied)"
            )

        if not isinstance(name_or_path, str) or not name_or_path.strip():
            raise ValueError("Field profile id must be a non-empty string")
        if name_or_path != name_or_path.strip() or name_or_path in {".", ".."}:
            raise ValueError(f"Invalid field profile id: {name_or_path!r}")

        # Reject absolute paths and traversal characters.
        if os.path.isabs(name_or_path):
            raise ValueError(f"Field profile path must be relative: {name_or_path}")
        if ".." in name_or_path:
            raise ValueError(f"Field profile path must not contain '..': {name_or_path}")
        if "/" in name_or_path or "\\" in name_or_path:
            raise ValueError(
                f"Field profile path must not contain directory separators: {name_or_path}"
            )
        explicit_ext = os.path.splitext(name_or_path)[1]
        if explicit_ext and explicit_ext != ".json":
            raise ValueError(
                f"Field profile explicit extension must be .json: {name_or_path}"
            )
        if not explicit_ext:
            name_or_path = name_or_path + ".json"

        profile_dir_real = os.path.realpath(profile_dir)
        full_path = os.path.realpath(os.path.join(profile_dir_real, name_or_path))

        # Containment: resolved path must start with profile_dir_real + sep.
        common = os.path.commonpath([profile_dir_real, full_path])
        if common != profile_dir_real:
            raise ValueError(f"Field profile path escapes profile_dir: {name_or_path}")

        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"Field profile not found: {full_path}")

        # Reject symlinks that escape.
        if os.path.islink(full_path):
            link_target = os.path.realpath(full_path)
            if os.path.commonpath([profile_dir_real, link_target]) != profile_dir_real:
                raise ValueError(
                    f"Field profile symlink escapes profile_dir: {name_or_path}"
                )

        return load_field_profile_json(full_path)

    @staticmethod
    def validate_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
        """Re-validate an already-loaded profile."""
        return validate_field_profile(profile)

    # ------------------------------------------------------------------
    # binding — centerline only
    # ------------------------------------------------------------------

    @staticmethod
    def takeoff_anchor_centerline(
        profile: FieldProfile,
        current_lat: Any = None,
        current_lon: Any = None,
        current_local_n_m: Any = None,
        current_local_e_m: Any = None,
        current_local_z_m: Any = None,
        current_yaw_rad: Any = None,
        gps_fix_type: Any = None,
        satellites_visible: Any = None,
        gps_eph: Any = None,
        gps_epv: Any = None,
        timestamp: Optional[float] = None,
    ) -> BindResult:
        """Bind a centerline profile to the current vehicle takeoff position.

        Key design rules:
        - **origin_local = current LOCAL_NED directly** (never derived from GPS).
        - **current GPS is only used for start_error** (distance to anchor).
        - **field_heading comes from centerline fitting** (not from yaw/GPS bearing).
        - **yaw_error is display-only** (never affects heading).
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
        binding_policy = profile.binding_policy

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

        # -- safe-parse current_yaw (optional, for display) ----------------
        yaw_ok = False
        f_yaw = 0.0
        if current_yaw_rad is not None:
            yaw_ok, f_yaw, _ = _safe_float(current_yaw_rad, "current_yaw_rad")

        # -- safe-parse gps_fix_type (must be non-negative integer) ---------
        ok_fix, fix_int, err_fix = _safe_int_noneg(gps_fix_type, "gps_fix_type")
        if not ok_fix:
            errors.append(err_fix)

        # -- safe-parse satellites_visible (must be non-negative integer) ---
        ok_sats, sats_int, err_sats = _safe_int_noneg(satellites_visible, "satellites_visible")
        if not ok_sats:
            errors.append(err_sats)

        # -- safe-parse gps_eph / gps_epv ----------------------------------
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

        # -- origin_local = current LOCAL_NED directly ---------------------
        # This is the KEY design rule: GPS does NOT redefine the origin.
        origin_local_n_m_val = f_n
        origin_local_e_m_val = f_e
        origin_local_z_m_val = f_z

        # -- compute current_start_error_m (GPS to anchor, check only) -----
        anchor = profile.anchor
        start_error_m = _gps_distance_m(anchor.lat, anchor.lon, f_lat, f_lon)

        if start_error_m > binding_policy.max_start_error_m:
            errors.append(
                f"Current GPS is {start_error_m:.2f} m from anchor GPS, "
                f"exceeds max_start_error_m {binding_policy.max_start_error_m:.2f} m"
            )
        elif start_error_m > binding_policy.warn_start_error_m:
            warnings.append(
                f"Current GPS is {start_error_m:.2f} m from anchor GPS, "
                f"exceeds warn_start_error_m {binding_policy.warn_start_error_m:.2f} m"
            )

        # -- centerline fitting --------------------------------------------
        fit_result = fit_centerline(anchor, profile.centerline_points, binding_policy)
        fit_diag = fit_result.diagnostics

        if not fit_diag.ok:
            errors.extend(fit_diag.errors)
        warnings.extend(fit_diag.warnings)

        if errors:
            return BindResult(
                ok=False, profile_id=profile.profile_id,
                origin_local_n_m=origin_local_n_m_val,
                origin_local_e_m=origin_local_e_m_val,
                origin_local_z_m=origin_local_z_m_val,
                current_start_error_m=start_error_m,
                diagnostics=FieldProfileDiagnostics(errors=list(errors), warnings=list(warnings)),
                warnings=list(warnings), errors=list(errors),
                gps_quality=gps_quality,
                max_residual_m=fit_result.max_residual_m,
                rms_residual_m=fit_result.rms_residual_m,
                timestamp=timestamp,
            )

        # -- compute yaw_error (display only) ------------------------------
        yaw_error_deg: Optional[float] = None
        if yaw_ok:
            yaw_error_deg = math.degrees(
                _normalize_angle(f_yaw - fit_result.field_heading_yaw_rad)
            )

        # -- build residual rows -------------------------------------------
        residual_rows: List[CenterlineResidualRow] = []
        for i, pt in enumerate(profile.centerline_points):
            enu_n, enu_e = _gps_enu_deltas(anchor.lat, anchor.lon, pt.lat, pt.lon)
            cos_h = math.cos(fit_result.field_heading_yaw_rad)
            sin_h = math.sin(fit_result.field_heading_yaw_rad)
            along_track = enu_n * cos_h + enu_e * sin_h
            residual_rows.append(CenterlineResidualRow(
                name=pt.name, lat=pt.lat, lon=pt.lon,
                residual_m=fit_result.point_residuals[i] if i < len(fit_result.point_residuals) else 0.0,
                expected_field_y_m=pt.expected_field_y_m,
                fitted_field_y_m=along_track,
            ))

        return BindResult(
            ok=True, profile_id=profile.profile_id,
            origin_local_n_m=origin_local_n_m_val,
            origin_local_e_m=origin_local_e_m_val,
            origin_local_z_m=origin_local_z_m_val,
            field_heading_yaw_rad=fit_result.field_heading_yaw_rad,
            field_heading_deg=fit_result.field_heading_deg,
            baseline_m=fit_result.baseline_m,
            current_start_error_m=start_error_m,
            yaw_error_deg=yaw_error_deg,
            diagnostics=FieldProfileDiagnostics(errors=[], warnings=list(warnings)),
            warnings=list(warnings), errors=[],
            gps_quality=gps_quality,
            centerline_residuals=residual_rows,
            max_residual_m=fit_result.max_residual_m,
            rms_residual_m=fit_result.rms_residual_m,
            timestamp=timestamp,
        )


    # ------------------------------------------------------------------
    # map preview — pure geometry, no runtime mutation
    # ------------------------------------------------------------------

    @staticmethod
    def build_map_preview(profile: FieldProfile) -> dict:
        """Build a map-preview response from a loaded FieldProfile.

        Pure geometry: does NOT modify RuntimeContext, does NOT freeze,
        does NOT send MAVLink commands.
        """
        import math as _math

        anchor = profile.anchor
        geom = profile.field_geometry
        fit_result = fit_centerline(anchor, profile.centerline_points, profile.binding_policy)

        heading_rad = fit_result.field_heading_yaw_rad
        heading_deg = fit_result.field_heading_deg

        # ----- helper: FIELD (x, y) -> GPS (lat, lon) --------------------
        def _field_to_gps(fx: float, fy: float):
            dx = fx - anchor.field_x_m
            dy = fy - anchor.field_y_m
            cos_h = _math.cos(heading_rad)
            sin_h = _math.sin(heading_rad)
            d_north = dy * cos_h - dx * sin_h
            d_east = dy * sin_h + dx * cos_h
            lat_rad = _math.radians(anchor.lat)
            lat_deg_out = anchor.lat + _math.degrees(d_north / EARTH_RADIUS_M)
            lon_deg_out = anchor.lon + _math.degrees(d_east / (EARTH_RADIUS_M * _math.cos(lat_rad)))
            return lat_deg_out, lon_deg_out

        # ----- geometry helpers -------------------------------------------
        lw = geom.lane_half_width_m
        x_min = -lw
        x_max = +lw

        # field box
        field_y_max = (
            geom.recce_area_y_max
            if geom.recce_area_y_max is not None
            else geom.recce_center_y_m + 2.5
        )
        field_y_min = 0.0

        # drop box
        drop_y_min = (
            geom.drop_area_y_min
            if geom.drop_area_y_min is not None
            else geom.drop_center_y_m - 2.5
        )
        drop_y_max = (
            geom.drop_area_y_max
            if geom.drop_area_y_max is not None
            else geom.drop_center_y_m + 2.5
        )

        # recce box
        recce_y_min = (
            geom.recce_area_y_min
            if geom.recce_area_y_min is not None
            else geom.recce_center_y_m - 2.5
        )
        recce_y_max = (
            geom.recce_area_y_max
            if geom.recce_area_y_max is not None
            else geom.recce_center_y_m + 2.5
        )

        def _make_corners(box_id: str, label: str, kind: str,
                          prefix: str, bx_min: float, bx_max: float,
                          by_min: float, by_max: float):
            pts = [
                (bx_min, by_min),  # bottom-left  (field frame)
                (bx_max, by_min),  # bottom-right
                (bx_max, by_max),  # top-right
                (bx_min, by_max),  # top-left
            ]
            corners = []
            for idx, (fx, fy) in enumerate(pts):
                lat, lon = _field_to_gps(fx, fy)
                corners.append({
                    "name": f"{prefix}{idx + 1}",
                    "field_x": round(fx, 6),
                    "field_y": round(fy, 6),
                    "lat": round(lat, 8),
                    "lon": round(lon, 8),
                })
            return {
                "id": box_id,
                "label": label,
                "kind": kind,
                "corners": corners,
            }

        boxes = [
            _make_corners("field", "比赛场地", "field_bounds", "F",
                          x_min, x_max, field_y_min, field_y_max),
            _make_corners("drop", "投放区", "drop_area", "D",
                          x_min, x_max, drop_y_min, drop_y_max),
            _make_corners("recce", "侦察区", "recce_area", "R",
                          x_min, x_max, recce_y_min, recce_y_max),
        ]

        return {
            "ok": True,
            "profile_id": profile.profile_id,
            "name": profile.name,
            "reference": {
                "origin_lat": anchor.lat,
                "origin_lon": anchor.lon,
                "field_heading_yaw_rad": round(heading_rad, 8),
                "field_heading_deg": round(heading_deg, 6),
            },
            "geometry": {
                "lane_half_width_m": lw,
                "field_y_min": field_y_min,
                "field_y_max": field_y_max,
                "drop_y_min": round(drop_y_min, 6),
                "drop_y_max": round(drop_y_max, 6),
                "recce_y_min": round(recce_y_min, 6),
                "recce_y_max": round(recce_y_max, 6),
            },
            "boxes": boxes,
        }


def _normalize_angle(rad: float) -> float:
    """Normalize angle to (-pi, pi]."""
    return math.atan2(math.sin(rad), math.cos(rad))
