"""Unit tests for app.field_profile — loading, parsing, and validation."""

from __future__ import annotations

import math
import os
from typing import Any, Dict

import pytest

from app.field_profile import (
    DECLARED_POSITION_TOLERANCE_M,
    FieldProfile,
    FieldProfileDiagnostics,
    FieldProfilePoint,
    FieldProfileValidationError,
    FORWARD_X_TOLERANCE_M,
    GpsQualityThresholds,
    LR_COINCIDENT_M,
    MAX_ORIGIN_DEVIATION_M,
    MIN_LR_GPS_BASELINE_M,
    ORIGIN_EPSILON_M,
    load_field_profile_json,
    parse_field_profile,
    validate_field_profile,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

EXAMPLE_PROFILE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "config", "field_profiles", "example_competition_lane.json",
)

_DEG_TO_M_LAT = 111194.9
_DEG_TO_M_LON_AT_34 = 111194.9 * math.cos(math.radians(34.0))


def _make_minimal_data() -> Dict[str, Any]:
    """Self-consistent profile: O at (34,108), F ~33.36 m north, L/R ~1.84 m."""
    return {
        "schema_version": 1,
        "profile_id": "test_profile",
        "name": "Test Profile",
        "created_at": "2025-01-01T00:00:00Z",
        "coordinate_convention": {
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        },
        "points": {
            "origin": {
                "name": "O", "role": "origin",
                "lat": 34.0, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 0.0,
            },
            "forward": {
                "name": "F", "role": "forward",
                "lat": 34.0003, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 33.36,
            },
            "left_check": {
                "name": "L", "role": "left_check",
                "lat": 34.00015, "lon": 107.99998,
                "field_x_m": -1.84, "field_y_m": 16.68,
            },
            "right_check": {
                "name": "R", "role": "right_check",
                "lat": 34.00015, "lon": 108.00002,
                "field_x_m": 1.84, "field_y_m": 16.68,
            },
        },
        "gps_quality": {
            "min_fix_type": 3,
            "min_satellites": 10,
            "max_eph": 2.5,
            "max_epv": 5.0,
        },
    }


def _profile_from_data(data: Dict[str, Any]) -> FieldProfile:
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    if not diag.ok:
        raise FieldProfileValidationError(diag)
    return profile


# ===================================================================
# existing tests (preserved, updated where needed)
# ===================================================================


def test_load_example_profile_from_json() -> None:
    profile = load_field_profile_json(EXAMPLE_PROFILE_PATH)
    assert profile.profile_id == "example_competition_lane"
    assert profile.origin is not None
    assert profile.forward is not None
    assert isinstance(profile.gps_quality, GpsQualityThresholds)


def test_missing_origin_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any("origin" in e.lower() for e in exc.value.diagnostics.errors)


def test_missing_forward_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["forward"]
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any("forward" in e.lower() for e in exc.value.diagnostics.errors)


def test_left_check_optional() -> None:
    data = _make_minimal_data()
    del data["points"]["left_check"]
    profile = _profile_from_data(data)
    assert profile.left_check is None


def test_right_check_optional() -> None:
    data = _make_minimal_data()
    del data["points"]["right_check"]
    profile = _profile_from_data(data)
    assert profile.right_check is None


def test_lat_out_of_range_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["lat"] = 91.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any("lat" in e.lower() and "91" in e for e in exc.value.diagnostics.errors)


def test_lon_out_of_range_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["lon"] = 181.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any("lon" in e.lower() and "181" in e for e in exc.value.diagnostics.errors)


def test_lat_negative_90_accepted() -> None:
    data = _make_minimal_data()
    del data["points"]["left_check"]
    del data["points"]["right_check"]
    data["points"]["origin"]["lat"] = -90.0
    data["points"]["forward"]["lat"] = -89.9997
    data["points"]["forward"]["lon"] = 108.0
    profile = _profile_from_data(data)
    assert profile.origin.lat == -90.0


def test_lon_negative_180_accepted() -> None:
    data = _make_minimal_data()
    del data["points"]["left_check"]
    del data["points"]["right_check"]
    data["points"]["origin"]["lon"] = -180.0
    data["points"]["forward"]["lon"] = -180.0
    data["points"]["forward"]["lat"] = 34.0003
    profile = _profile_from_data(data)
    assert profile.origin.lon == -180.0


@pytest.mark.parametrize("attr, bad_value", [
    ("lat", float("nan")), ("lat", float("inf")), ("lat", -float("inf")),
    ("lon", float("nan")), ("lon", float("inf")),
    ("field_x_m", float("nan")), ("field_x_m", float("inf")),
    ("field_y_m", float("nan")), ("field_y_m", float("inf")),
])
def test_non_finite_value_fails(attr: str, bad_value: float) -> None:
    data = _make_minimal_data()
    data["points"]["origin"][attr] = bad_value
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any(attr in e.lower() for e in exc.value.diagnostics.errors)


def test_baseline_below_min_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["lat"] = 34.0
    data["points"]["forward"]["lat"] = 34.000027  # ~3 m
    data["points"]["forward"]["lon"] = 108.0
    data["points"]["forward"]["field_y_m"] = 3.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any("baseline" in e.lower() for e in exc.value.diagnostics.errors)


def test_baseline_between_min_and_recommended_warns() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["lat"] = 34.0
    data["points"]["forward"]["lat"] = 34.000063  # ~7 m
    data["points"]["forward"]["lon"] = 108.0
    data["points"]["forward"]["field_y_m"] = 7.0
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    assert any("baseline" in w.lower() for w in diag.warnings)


def test_left_check_negative_x_accepted() -> None:
    data = _make_minimal_data()
    tiny = 0.1 / _DEG_TO_M_LON_AT_34
    data["points"]["left_check"]["lon"] = 108.0 - tiny
    data["points"]["left_check"]["field_x_m"] = -0.1
    profile = _profile_from_data(data)
    assert profile.left_check is not None
    assert profile.left_check.field_x_m < 0.0


def test_right_check_positive_x_accepted() -> None:
    data = _make_minimal_data()
    tiny = 0.1 / _DEG_TO_M_LON_AT_34
    data["points"]["right_check"]["lon"] = 108.0 + tiny
    data["points"]["right_check"]["field_x_m"] = 0.1
    profile = _profile_from_data(data)
    assert profile.right_check is not None
    assert profile.right_check.field_x_m > 0.0


def test_lr_declared_swapped_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = 2.5
    data["points"]["right_check"]["field_x_m"] = -2.5
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "negative" in errors_text or "positive" in errors_text


def test_lr_gps_swapped_fails() -> None:
    data = _make_minimal_data()
    l_lat, l_lon = data["points"]["left_check"]["lat"], data["points"]["left_check"]["lon"]
    data["points"]["left_check"]["lat"] = data["points"]["right_check"]["lat"]
    data["points"]["left_check"]["lon"] = data["points"]["right_check"]["lon"]
    data["points"]["right_check"]["lat"] = l_lat
    data["points"]["right_check"]["lon"] = l_lon
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "swap" in errors_text or "gps-derived" in errors_text


def test_lr_both_positive_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = 1.0
    data["points"]["right_check"]["field_x_m"] = 3.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "negative" in errors_text


def test_lr_both_negative_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = -3.0
    data["points"]["right_check"]["field_x_m"] = -1.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "positive" in errors_text


def test_lr_gps_same_side_fails() -> None:
    data = _make_minimal_data()
    data["points"]["right_check"]["lon"] = 108.0 - 0.00005
    data["points"]["right_check"]["field_x_m"] = -3.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "positive" in errors_text or "same side" in errors_text


def test_lr_gps_coincident_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["lat"] = 34.00015
    data["points"]["left_check"]["lon"] = 108.00001
    data["points"]["right_check"]["lat"] = 34.00015
    data["points"]["right_check"]["lon"] = 108.00001
    data["points"]["left_check"]["field_x_m"] = 1.0
    data["points"]["right_check"]["field_x_m"] = 1.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "negative" in errors_text or "same side" in errors_text


def test_lr_gps_too_close_fails() -> None:
    """L/R GPS < MIN_LR_GPS_BASELINE_M → hard error."""
    data = _make_minimal_data()
    tiny = 0.3 / _DEG_TO_M_LON_AT_34
    data["points"]["left_check"]["lon"] = 108.0 - tiny
    data["points"]["left_check"]["field_x_m"] = -0.3
    data["points"]["right_check"]["lon"] = 108.0 + tiny
    data["points"]["right_check"]["field_x_m"] = 0.3
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "close" in errors_text or "coincident" in errors_text, (
        f"Expected hard error, got: {exc.value.diagnostics.errors}"
    )


def test_gps_declared_mismatch_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = -10.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "differs" in errors_text


def test_lr_coincident_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["lon"] = 108.0 - 1e-12
    data["points"]["left_check"]["field_x_m"] = -1e-9
    data["points"]["right_check"]["lon"] = 108.0 + 1e-12
    data["points"]["right_check"]["field_x_m"] = 1e-9
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "coincident" in errors_text


def test_origin_epsilon_normalises_with_warning() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["field_x_m"] = 1e-8
    data["points"]["origin"]["field_y_m"] = 0.0
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    assert profile.origin.field_x_m == 0.0
    assert any("origin" in w.lower() and "field_x" in w.lower() for w in diag.warnings)


def test_origin_exact_zero_no_warning() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["field_x_m"] = 0.0
    data["points"]["origin"]["field_y_m"] = 0.0
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    assert len([w for w in diag.warnings if "origin" in w.lower()]) == 0


# ===================================================================
# NEW: origin large deviation → hard fail
# ===================================================================


def test_origin_field_x_large_deviation_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["field_x_m"] = 100.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "origin" in errors_text and "field_x" in errors_text


def test_origin_field_y_large_deviation_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["field_y_m"] = 100.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "origin" in errors_text and "field_y" in errors_text


def test_origin_not_silently_zeroed_on_large_error() -> None:
    """validate_field_profile must not silently zero a large origin deviation."""
    data = _make_minimal_data()
    data["points"]["origin"]["field_x_m"] = 100.0
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert not diag.ok
    # The profile's origin field_x_m must NOT have been changed to 0.
    assert profile.origin.field_x_m == 100.0


# ===================================================================
# NEW: schema_version parse hardening
# ===================================================================


def test_schema_version_non_numeric_string_fails() -> None:
    data = _make_minimal_data()
    data["schema_version"] = "abc"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("schema_version" in e.lower() for e in exc.value.diagnostics.errors)


def test_schema_version_none_fails() -> None:
    data = _make_minimal_data()
    data["schema_version"] = None
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("schema_version" in e.lower() for e in exc.value.diagnostics.errors)


def test_schema_version_bool_fails() -> None:
    data = _make_minimal_data()
    data["schema_version"] = True
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("schema_version" in e.lower() for e in exc.value.diagnostics.errors)


def test_schema_version_nan_fails() -> None:
    data = _make_minimal_data()
    data["schema_version"] = float("nan")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("schema_version" in e.lower() for e in exc.value.diagnostics.errors)


def test_schema_version_inf_fails() -> None:
    data = _make_minimal_data()
    data["schema_version"] = float("inf")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("schema_version" in e.lower() for e in exc.value.diagnostics.errors)


# ===================================================================
# NEW: gps_quality / coordinate_convention / points type hardening
# ===================================================================


def test_gps_quality_not_object_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"] = "not_an_object"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("gps_quality" in e.lower() for e in exc.value.diagnostics.errors)


def test_coordinate_convention_not_object_fails() -> None:
    data = _make_minimal_data()
    data["coordinate_convention"] = 123
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("coordinate_convention" in e.lower() for e in exc.value.diagnostics.errors)


def test_gps_quality_null_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"] = None
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("gps_quality" in e.lower() and "null" in e.lower() for e in exc.value.diagnostics.errors)


def test_coordinate_convention_null_fails() -> None:
    data = _make_minimal_data()
    data["coordinate_convention"] = None
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("coordinate_convention" in e.lower() and "null" in e.lower() for e in exc.value.diagnostics.errors)


def test_points_not_object_fails() -> None:
    data = _make_minimal_data()
    data["points"] = []
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("points" in e.lower() for e in exc.value.diagnostics.errors)


def test_point_not_object_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"] = "not_an_object"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("origin" in e.lower() for e in exc.value.diagnostics.errors)


# ===================================================================
# NEW: gps_quality threshold hardening
# ===================================================================


def test_gq_min_fix_type_bool_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = True
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_fix_type" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_fix_type_string_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = "abc"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_fix_type" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_fix_type_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = -1
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_fix_type" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_fix_type_fractional_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = 3.5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_fix_type" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_fix_type_nan_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = float("nan")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_fix_type" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_satellites_bool_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_satellites"] = False
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_satellites" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_satellites_string_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_satellites"] = "xyz"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_satellites" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_satellites_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_satellites"] = -5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_satellites" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_satellites_fractional_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_satellites"] = 10.5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_satellites" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_min_satellites_nan_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_satellites"] = float("nan")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_satellites" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_eph_bool_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_eph"] = True
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_eph" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_eph_string_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_eph"] = "bad"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_eph" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_eph_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_eph"] = -0.1
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_eph" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_eph_nan_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_eph"] = float("nan")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_eph" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_eph_inf_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_eph"] = float("inf")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_eph" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_epv_bool_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_epv"] = False
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_epv" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_epv_string_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_epv"] = "bad"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_epv" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_epv_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_epv"] = -0.5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_epv" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_epv_nan_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_epv"] = float("nan")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_epv" in e.lower() for e in exc.value.diagnostics.errors)


def test_gq_max_epv_inf_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_epv"] = float("inf")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_epv" in e.lower() for e in exc.value.diagnostics.errors)


# ===================================================================
# forward checks
# ===================================================================


def test_forward_field_x_far_from_zero_fails() -> None:
    data = _make_minimal_data()
    data["points"]["forward"]["field_x_m"] = 5.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "forward" in errors_text and "field_x" in errors_text


def test_forward_field_y_zero_or_negative_fails() -> None:
    data = _make_minimal_data()
    data["points"]["forward"]["field_y_m"] = -1.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "forward" in errors_text and "field_y" in errors_text


# ===================================================================
# remaining existing tests
# ===================================================================


def test_wrong_coordinate_convention_fails() -> None:
    data = _make_minimal_data()
    data["coordinate_convention"]["field_x_positive"] = "left"
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any("coordinate_convention" in e.lower() for e in exc.value.diagnostics.errors)


def test_unknown_top_level_field_warns() -> None:
    data = _make_minimal_data()
    data["future_extension"] = {"some": "value"}
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    assert any("future_extension" in w for w in diag.warnings)
    assert "future_extension" in profile.extra


def test_nested_unknown_in_point_warns() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["custom_flag"] = True
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    assert any("points.origin.custom_flag" in w for w in diag.warnings)


def test_nested_unknown_in_gps_quality_warns() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["future_key"] = 123
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    assert any("gps_quality.future_key" in w for w in diag.warnings)


def test_parse_serialize_reparse_stable() -> None:
    data = _make_minimal_data()
    profile1 = _profile_from_data(data)
    rebuilt: Dict[str, Any] = {
        "schema_version": profile1.schema_version,
        "profile_id": profile1.profile_id,
        "name": profile1.name,
        "created_at": profile1.created_at,
        "coordinate_convention": dict(profile1.coordinate_convention),
        "points": {},
        "gps_quality": {
            "min_fix_type": profile1.gps_quality.min_fix_type,
            "min_satellites": profile1.gps_quality.min_satellites,
            "max_eph": profile1.gps_quality.max_eph,
            "max_epv": profile1.gps_quality.max_epv,
        },
    }
    for key, pt in profile1.points.items():
        rebuilt["points"][key] = {
            "name": pt.name, "role": pt.role,
            "lat": pt.lat, "lon": pt.lon,
            "field_x_m": pt.field_x_m, "field_y_m": pt.field_y_m,
        }
    profile2 = _profile_from_data(rebuilt)
    assert profile2.profile_id == profile1.profile_id
    assert profile2.origin.lat == pytest.approx(profile1.origin.lat)


def test_unsupported_schema_version_fails() -> None:
    data = _make_minimal_data()
    data["schema_version"] = 99
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any("schema_version" in e.lower() for e in exc.value.diagnostics.errors)


def test_empty_profile_id_fails() -> None:
    data = _make_minimal_data()
    data["profile_id"] = ""
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("profile_id" in e.lower() for e in exc.value.diagnostics.errors)


def test_missing_point_lat_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["lat"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("lat" in e.lower() and "missing" in e.lower() for e in exc.value.diagnostics.errors)


def test_missing_point_lon_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["lon"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("lon" in e.lower() and "missing" in e.lower() for e in exc.value.diagnostics.errors)


def test_missing_point_field_x_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["field_x_m"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("field_x_m" in e.lower() and "missing" in e.lower() for e in exc.value.diagnostics.errors)


def test_missing_point_field_y_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["field_y_m"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("field_y_m" in e.lower() and "missing" in e.lower() for e in exc.value.diagnostics.errors)


def test_missing_point_role_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["role"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("role" in e.lower() and "missing" in e.lower() for e in exc.value.diagnostics.errors)


def test_point_none_lat_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["lat"] = None
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("lat" in e.lower() for e in exc.value.diagnostics.errors)


def test_point_key_role_mismatch_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["role"] = "forward"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "key" in errors_text or "role" in errors_text


def test_gps_quality_max_eph_nan_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_eph"] = float("nan")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_eph" in e.lower() for e in exc.value.diagnostics.errors)


def test_gps_quality_max_epv_inf_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_epv"] = float("inf")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("max_epv" in e.lower() for e in exc.value.diagnostics.errors)


def test_gps_quality_min_fix_type_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = -1
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_fix_type" in e.lower() for e in exc.value.diagnostics.errors)


def test_gps_quality_min_satellites_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_satellites"] = -5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_satellites" in e.lower() for e in exc.value.diagnostics.errors)


def test_gps_quality_min_fix_type_float_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = 3.5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any("min_fix_type" in e.lower() for e in exc.value.diagnostics.errors)


def test_load_nonexistent_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_field_profile_json("/nonexistent/path/profile.json")
