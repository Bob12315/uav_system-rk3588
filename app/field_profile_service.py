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
from typing import Any, Dict, List, Optional

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
        """Return absolute paths to every ``*.json`` file under *profile_dir*.

        Does **not** validate the files — only discovers them.
        """
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
        """Load and validate a field profile.

        If *name_or_path* is an existing file path it is used directly.
        Otherwise it is resolved relative to *profile_dir* (with a
        ``.json`` suffix appended if missing).
        """
        if os.path.isfile(name_or_path):
            return load_field_profile_json(name_or_path)

        if profile_dir is None:
            raise FileNotFoundError(
                f"Field profile not found: {name_or_path} "
                f"(no profile_dir supplied)"
            )

        if not name_or_path.endswith(".json"):
            name_or_path = name_or_path + ".json"

        full_path = os.path.join(profile_dir, name_or_path)
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"Field profile not found: {full_path}")

        return load_field_profile_json(full_path)

    @staticmethod
    def validate_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
        """Re-validate an already-loaded profile.  Convenience wrapper."""
        return validate_field_profile(profile)

    # ------------------------------------------------------------------
    # binding
    # ------------------------------------------------------------------

    @staticmethod
    def bind_profile_to_current_vehicle(
        profile: FieldProfile,
        current_lat: float,
        current_lon: float,
        current_local_n_m: float,
        current_local_e_m: float,
        current_local_z_m: float,
        gps_fix_type: int,
        satellites_visible: int,
        gps_eph: Optional[float],
        gps_epv: Optional[float],
        timestamp: Optional[float] = None,
    ) -> BindResult:
        """Compute a bind candidate from *profile* and current vehicle state.

        Returns a :class:`BindResult` — the caller decides what to do
        with it.  This method does **not** write to RuntimeContext,
        confirm, freeze, or send any MAVLink message.
        """
        errors: List[str] = []
        warnings: List[str] = []

        thresholds: GpsQualityThresholds = profile.gps_quality

        # -- validate inputs are finite ----------------------------------
        for name, val in [
            ("current_lat", current_lat),
            ("current_lon", current_lon),
            ("current_local_n_m", current_local_n_m),
            ("current_local_e_m", current_local_e_m),
            ("current_local_z_m", current_local_z_m),
        ]:
            if not math.isfinite(val):
                errors.append(f"{name} is not finite: {val}")

        # -- GPS quality (fail-closed) -----------------------------------
        gps_quality = GpsQuality(
            fix_type=gps_fix_type,
            satellites_visible=satellites_visible,
            eph=gps_eph,
            epv=gps_epv,
        )

        if gps_fix_type < thresholds.min_fix_type:
            errors.append(
                f"GPS fix_type {gps_fix_type} < required {thresholds.min_fix_type}"
            )
        if satellites_visible < thresholds.min_satellites:
            errors.append(
                f"GPS satellites {satellites_visible} < required {thresholds.min_satellites}"
            )

        # eph / epv: missing, negative, or non-finite → fail
        for label, value, threshold in [
            ("eph", gps_eph, thresholds.max_eph),
            ("epv", gps_epv, thresholds.max_epv),
        ]:
            if value is None:
                errors.append(f"GPS {label} is missing")
            elif not math.isfinite(value):
                errors.append(f"GPS {label} is not finite: {value}")
            elif value < 0.0:
                errors.append(f"GPS {label} is negative: {value}")
            elif value > threshold:
                errors.append(
                    f"GPS {label} {value} > max allowed {threshold}"
                )

        if errors:
            return BindResult(
                ok=False,
                profile_id=profile.profile_id,
                diagnostics=FieldProfileDiagnostics(errors=errors, warnings=warnings),
                warnings=warnings,
                errors=errors,
                gps_quality=gps_quality,
            )

        # -- geometry ----------------------------------------------------
        origin = profile.origin
        forward = profile.forward

        # d_OC: ENU delta from origin GPS to current GPS
        d_north, d_east = _gps_enu_deltas(
            origin.lat, origin.lon, current_lat, current_lon
        )

        origin_local_n_m = current_local_n_m - d_north
        origin_local_e_m = current_local_e_m - d_east
        origin_local_z_m = current_local_z_m  # keep as-is

        # field heading from O → F
        heading_rad = _gps_bearing_rad(origin.lat, origin.lon, forward.lat, forward.lon)
        heading_deg = math.degrees(heading_rad)

        # current FIELD position: rotate d_OC by -heading
        cos_h = math.cos(heading_rad)
        sin_h = math.sin(heading_rad)
        current_field_x_m = -d_north * sin_h + d_east * cos_h
        current_field_y_m = d_north * cos_h + d_east * sin_h

        # baseline
        baseline_m = _gps_distance_m(origin.lat, origin.lon, forward.lat, forward.lon)

        # check-point projections
        check_points: List[CheckPointResult] = []
        for role in ("left_check", "right_check"):
            pt = profile.points.get(role)
            if pt is not None:
                check_points.append(
                    CheckPointResult(
                        name=pt.name,
                        role=pt.role,
                        expected_field_x_m=pt.field_x_m,
                        expected_field_y_m=pt.field_y_m,
                    )
                )

        return BindResult(
            ok=True,
            profile_id=profile.profile_id,
            origin_local_n_m=origin_local_n_m,
            origin_local_e_m=origin_local_e_m,
            origin_local_z_m=origin_local_z_m,
            field_heading_yaw_rad=heading_rad,
            field_heading_deg=heading_deg,
            current_field_x_m=current_field_x_m,
            current_field_y_m=current_field_y_m,
            baseline_m=baseline_m,
            diagnostics=FieldProfileDiagnostics(errors=[], warnings=warnings),
            warnings=warnings,
            errors=[],
            gps_quality=gps_quality,
            check_points=check_points,
        )
