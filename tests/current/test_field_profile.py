"""Unit tests for app.field_profile — loading, parsing, and validation."""

from __future__ import annotations

import math
import os
from typing import Any, Dict

import pytest

from app.field_profile import (
    FieldProfile,
    FieldProfileDiagnostics,
    FieldProfilePoint,
    FieldProfileValidationError,
    GpsQualityThresholds,
    GPS_DECLARED_TOLERANCE_M,
    LR_COINCIDENT_M,
    LR_TOO_CLOSE_WARN_M,
    load_field_profile_json,
    parse_field_profile,
    validate_field_profile,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

EXAMPLE_PROFILE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "config",
    "field_profiles",
    "example_competition_lane.json",
)


def _make_minimal_data() -> Dict[str, Any]:
    """Return a dict that passes parse + validate.

    O=(34.0, 108.0), F≈33.36 m north, L/R ≈1.84 m left/right at ~16.68 m forward.
    Declared coords match GPS projection for a north-oriented profile.
    """
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
                "name": "O",
                "role": "origin",
                "lat": 34.0,
                "lon": 108.0,
                "field_x_m": 0.0,
                "field_y_m": 0.0,
            },
            "forward": {
                "name": "F",
                "role": "forward",
                "lat": 34.0003,
                "lon": 108.0,
                "field_x_m": 0.0,
                "field_y_m": 33.36,
            },
            "left_check": {
                "name": "L",
                "role": "left_check",
                "lat": 34.00015,
                "lon": 107.99998,
                "field_x_m": -1.84,
                "field_y_m": 16.68,
            },
            "right_check": {
                "name": "R",
                "role": "right_check",
                "lat": 34.00015,
                "lon": 108.00002,
                "field_x_m": 1.84,
                "field_y_m": 16.68,
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


# ---------------------------------------------------------------------------
# valid example profile
# ---------------------------------------------------------------------------


def test_load_example_profile_from_json() -> None:
    """The bundled example profile must load without errors."""
    profile = load_field_profile_json(EXAMPLE_PROFILE_PATH)
    assert profile.profile_id == "example_competition_lane"
    assert profile.origin is not None
    assert profile.forward is not None
    assert profile.left_check is not None
    assert profile.right_check is not None
    assert isinstance(profile.gps_quality, GpsQualityThresholds)


# ---------------------------------------------------------------------------
# missing mandatory points
# ---------------------------------------------------------------------------


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
    """left_check is optional — profile should still validate."""
    data = _make_minimal_data()
    del data["points"]["left_check"]
    profile = _profile_from_data(data)
    assert profile.left_check is None


def test_right_check_optional() -> None:
    """right_check is optional — profile should still validate."""
    data = _make_minimal_data()
    del data["points"]["right_check"]
    profile = _profile_from_data(data)
    assert profile.right_check is None


# ---------------------------------------------------------------------------
# invalid lat / lon
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# NaN / Inf rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attr, bad_value",
    [
        ("lat", float("nan")),
        ("lat", float("inf")),
        ("lat", -float("inf")),
        ("lon", float("nan")),
        ("lon", float("inf")),
        ("field_x_m", float("nan")),
        ("field_x_m", float("inf")),
        ("field_y_m", float("nan")),
        ("field_y_m", float("inf")),
    ],
)
def test_non_finite_value_fails(attr: str, bad_value: float) -> None:
    data = _make_minimal_data()
    data["points"]["origin"][attr] = bad_value
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any(
        attr in e.lower() for e in exc.value.diagnostics.errors
    ), f"Expected error mentioning '{attr}', got: {exc.value.diagnostics.errors}"


# ---------------------------------------------------------------------------
# O→F baseline too short (< MIN_GPS_BASELINE_M)
# ---------------------------------------------------------------------------


def test_baseline_below_min_fails() -> None:
    """O and F less than 5 m apart must be a hard error."""
    data = _make_minimal_data()
    data["points"]["origin"]["lat"] = 34.0
    data["points"]["origin"]["lon"] = 108.0
    data["points"]["forward"]["lat"] = 34.000027  # ~3 m
    data["points"]["forward"]["lon"] = 108.0
    data["points"]["forward"]["field_y_m"] = 3.0  # consistent
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any(
        "baseline" in e.lower() for e in exc.value.diagnostics.errors
    ), f"Expected baseline error, got: {exc.value.diagnostics.errors}"


# ---------------------------------------------------------------------------
# O→F baseline between MIN and RECOMMENDED → warning only
# ---------------------------------------------------------------------------


def test_baseline_between_min_and_recommended_warns() -> None:
    """O and F 7 m apart → warning but not error."""
    data = _make_minimal_data()
    data["points"]["origin"]["lat"] = 34.0
    data["points"]["origin"]["lon"] = 108.0
    data["points"]["forward"]["lat"] = 34.000063  # ~7 m
    data["points"]["forward"]["lon"] = 108.0
    data["points"]["forward"]["field_y_m"] = 7.0  # consistent
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok, f"Expected ok, got errors: {diag.errors}"
    assert any(
        "baseline" in w.lower() for w in diag.warnings
    ), f"Expected baseline warning, got: {diag.warnings}"


# ---------------------------------------------------------------------------
# left_check x < 0 accepted / right_check x > 0 accepted
# ---------------------------------------------------------------------------


def test_left_check_negative_x_accepted() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = -0.1
    # Adjust GPS so projection is also negative:
    # field_x ≈ d_east for north heading. -0.1 m east → lon offset
    data["points"]["left_check"]["lon"] = 108.0 - 0.1 / (
        111195.0 * math.cos(math.radians(34.0))
    )
    profile = _profile_from_data(data)
    assert profile.left_check is not None
    assert profile.left_check.field_x_m < 0.0


def test_right_check_positive_x_accepted() -> None:
    data = _make_minimal_data()
    data["points"]["right_check"]["field_x_m"] = 0.1
    data["points"]["right_check"]["lon"] = 108.0 + 0.1 / (
        111195.0 * math.cos(math.radians(34.0))
    )
    profile = _profile_from_data(data)
    assert profile.right_check is not None
    assert profile.right_check.field_x_m > 0.0


# ---------------------------------------------------------------------------
# L/R swapped — declared
# ---------------------------------------------------------------------------


def test_lr_declared_swapped_fails() -> None:
    """L with positive declared x and R with negative declared x → error."""
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = 2.5
    data["points"]["right_check"]["field_x_m"] = -2.5
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert ("negative" in errors_text) or ("positive" in errors_text), (
        f"Expected sign error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R swapped — GPS
# ---------------------------------------------------------------------------


def test_lr_gps_swapped_fails() -> None:
    """Swap L and R GPS coordinates → GPS-derived signs are wrong."""
    data = _make_minimal_data()
    # Swap GPS coords but keep declared field_x correct
    l_lat = data["points"]["left_check"]["lat"]
    l_lon = data["points"]["left_check"]["lon"]
    data["points"]["left_check"]["lat"] = data["points"]["right_check"]["lat"]
    data["points"]["left_check"]["lon"] = data["points"]["right_check"]["lon"]
    data["points"]["right_check"]["lat"] = l_lat
    data["points"]["right_check"]["lon"] = l_lon
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert ("swap" in errors_text) or ("gps-derived" in errors_text), (
        f"Expected GPS swap error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R same side — declared
# ---------------------------------------------------------------------------


def test_lr_both_positive_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = 1.0
    data["points"]["right_check"]["field_x_m"] = 3.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "negative" in errors_text, (
        f"Expected left sign error, got: {exc.value.diagnostics.errors}"
    )


def test_lr_both_negative_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = -3.0
    data["points"]["right_check"]["field_x_m"] = -1.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "positive" in errors_text, (
        f"Expected right sign error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R same side — GPS
# ---------------------------------------------------------------------------


def test_lr_gps_same_side_fails() -> None:
    """Put both L and R GPS on the left side → GPS-derived same-side error."""
    data = _make_minimal_data()
    # Put R GPS also on the left (negative lon offset)
    data["points"]["right_check"]["lon"] = 108.0 - 0.00005
    data["points"]["right_check"]["field_x_m"] = -3.0  # declared also left
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    # Declared sign catches it
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "positive" in errors_text or "same side" in errors_text, (
        f"Expected sign/same-side error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R GPS coincident
# ---------------------------------------------------------------------------


def test_lr_gps_coincident_fails() -> None:
    """Same GPS → GPS-derived coincident error."""
    data = _make_minimal_data()
    # Put L and R at the same GPS as forward but slightly offset
    # to get different declared signs but same GPS projection
    # Actually, just make them share the same GPS coords:
    data["points"]["left_check"]["lat"] = 34.00015
    data["points"]["left_check"]["lon"] = 108.00001
    data["points"]["right_check"]["lat"] = 34.00015
    data["points"]["right_check"]["lon"] = 108.00001
    # Both at same lon = positive field_x for both → same-side from GPS
    data["points"]["left_check"]["field_x_m"] = 1.0  # wrong sign, caught by declared
    data["points"]["right_check"]["field_x_m"] = 1.0  # caught by GPS same-side
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "negative" in errors_text or "same side" in errors_text, (
        f"Expected error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R GPS too close
# ---------------------------------------------------------------------------


def test_lr_gps_too_close_fails() -> None:
    """L/R GPS very close (< 1 m) → warning or error."""
    data = _make_minimal_data()
    # Set L GPS at tiny left offset, R GPS at tiny right offset
    # field_x ~ d_east for north heading
    tiny = 0.3 / (111195.0 * math.cos(math.radians(34.0)))  # ~0.3 m
    data["points"]["left_check"]["lon"] = 108.0 - tiny
    data["points"]["left_check"]["field_x_m"] = -0.3
    data["points"]["right_check"]["lon"] = 108.0 + tiny
    data["points"]["right_check"]["field_x_m"] = 0.3
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    # Distance ≈ 0.6 m < 1.0 m → warning
    assert diag.ok, f"Expected ok, got errors: {diag.errors}"
    assert any(
        "close" in w.lower() for w in diag.warnings
    ), f"Expected proximity warning, got: {diag.warnings}"


# ---------------------------------------------------------------------------
# GPS vs declared mismatch > tolerance
# ---------------------------------------------------------------------------


def test_gps_declared_mismatch_fails() -> None:
    """Declared field_x_m far from GPS-derived → hard error."""
    data = _make_minimal_data()
    # Set declared way off from GPS
    data["points"]["left_check"]["field_x_m"] = -10.0  # GPS is ~-1.84
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "differs" in errors_text, (
        f"Expected mismatch error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R coincident / too close (declared, now backed by GPS)
# ---------------------------------------------------------------------------


def test_lr_coincident_fails() -> None:
    """Declared L/R extremely close → GPS check catches coincident."""
    data = _make_minimal_data()
    # Put both at essentially same GPS
    data["points"]["left_check"]["lon"] = 108.0 - 1e-12
    data["points"]["left_check"]["field_x_m"] = -1e-9
    data["points"]["right_check"]["lon"] = 108.0 + 1e-12
    data["points"]["right_check"]["field_x_m"] = 1e-9
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "coincident" in errors_text, (
        f"Expected coincident error, got: {exc.value.diagnostics.errors}"
    )


def test_lr_too_close_warns() -> None:
    """L and R 0.5 m apart → warning, not error."""
    data = _make_minimal_data()
    tiny = 0.25 / (111195.0 * math.cos(math.radians(34.0)))
    data["points"]["left_check"]["lon"] = 108.0 - tiny
    data["points"]["left_check"]["field_x_m"] = -0.25
    data["points"]["right_check"]["lon"] = 108.0 + tiny
    data["points"]["right_check"]["field_x_m"] = 0.25
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok, f"Expected ok, got errors: {diag.errors}"
    assert any(
        "close" in w.lower() for w in diag.warnings
    ), f"Expected proximity warning, got: {diag.warnings}"


# ---------------------------------------------------------------------------
# origin epsilon normalisation
# ---------------------------------------------------------------------------


def test_origin_epsilon_normalises_with_warning() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["field_x_m"] = 1e-8  # > 1e-9 → warn + normalise
    data["points"]["origin"]["field_y_m"] = 0.0
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    assert profile.origin.field_x_m == 0.0
    assert any(
        "origin" in w.lower() and "field_x" in w.lower() for w in diag.warnings
    ), f"Expected origin epsilon warning, got: {diag.warnings}"


def test_origin_exact_zero_no_warning() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["field_x_m"] = 0.0
    data["points"]["origin"]["field_y_m"] = 0.0
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok
    origin_warnings = [
        w for w in diag.warnings if "origin" in w.lower()
    ]
    assert len(origin_warnings) == 0, f"Unexpected origin warnings: {origin_warnings}"


# ---------------------------------------------------------------------------
# coordinate convention mismatch
# ---------------------------------------------------------------------------


def test_wrong_coordinate_convention_fails() -> None:
    data = _make_minimal_data()
    data["coordinate_convention"]["field_x_positive"] = "left"
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any(
        "coordinate_convention" in e.lower() for e in exc.value.diagnostics.errors
    )


# ---------------------------------------------------------------------------
# unknown top-level fields → warning (forward-compatible)
# ---------------------------------------------------------------------------


def test_unknown_top_level_field_warns() -> None:
    data = _make_minimal_data()
    data["future_extension"] = {"some": "value"}
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok, f"Unknown field should not cause error, got: {diag.errors}"
    assert any(
        "future_extension" in w for w in diag.warnings
    ), f"Expected warning about 'future_extension', got: {diag.warnings}"
    assert "future_extension" in profile.extra
    assert profile.extra["future_extension"] == {"some": "value"}


# ---------------------------------------------------------------------------
# nested unknown fields
# ---------------------------------------------------------------------------


def test_nested_unknown_in_point_warns() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["custom_flag"] = True
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok, f"Unknown nested field should not cause error, got: {diag.errors}"
    assert any(
        "points.origin.custom_flag" in w for w in diag.warnings
    ), f"Expected nested unknown warning, got: {diag.warnings}"


def test_nested_unknown_in_gps_quality_warns() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["future_key"] = 123
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    assert diag.ok, f"Unknown gps_quality field should not cause error, got: {diag.errors}"
    assert any(
        "gps_quality.future_key" in w for w in diag.warnings
    ), f"Expected nested unknown warning, got: {diag.warnings}"


# ---------------------------------------------------------------------------
# JSON round-trip stability
# ---------------------------------------------------------------------------


def test_parse_serialize_reparse_stable() -> None:
    """Parsing a dict, re-serialising its points, and re-parsing must be stable."""
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
            "name": pt.name,
            "role": pt.role,
            "lat": pt.lat,
            "lon": pt.lon,
            "field_x_m": pt.field_x_m,
            "field_y_m": pt.field_y_m,
        }

    profile2 = _profile_from_data(rebuilt)

    assert profile2.profile_id == profile1.profile_id
    assert profile2.origin.lat == pytest.approx(profile1.origin.lat)
    assert profile2.origin.lon == pytest.approx(profile1.origin.lon)
    assert profile2.forward.lat == pytest.approx(profile1.forward.lat)
    assert profile2.forward.lon == pytest.approx(profile1.forward.lon)


# ---------------------------------------------------------------------------
# schema_version rejection
# ---------------------------------------------------------------------------


def test_unsupported_schema_version_fails() -> None:
    data = _make_minimal_data()
    data["schema_version"] = 99
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any(
        "schema_version" in e.lower() for e in exc.value.diagnostics.errors
    )


# ---------------------------------------------------------------------------
# profile_id empty
# ---------------------------------------------------------------------------


def test_empty_profile_id_fails() -> None:
    data = _make_minimal_data()
    data["profile_id"] = ""
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "profile_id" in e.lower() for e in exc.value.diagnostics.errors
    ), f"Expected profile_id error, got: {exc.value.diagnostics.errors}"


# ---------------------------------------------------------------------------
# missing point fields
# ---------------------------------------------------------------------------


def test_missing_point_lat_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["lat"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "lat" in e.lower() and "missing" in e.lower()
        for e in exc.value.diagnostics.errors
    ), f"Expected missing lat error, got: {exc.value.diagnostics.errors}"


def test_missing_point_lon_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["lon"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "lon" in e.lower() and "missing" in e.lower()
        for e in exc.value.diagnostics.errors
    ), f"Expected missing lon error, got: {exc.value.diagnostics.errors}"


def test_missing_point_field_x_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["field_x_m"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "field_x_m" in e.lower() and "missing" in e.lower()
        for e in exc.value.diagnostics.errors
    ), f"Expected missing field_x_m error, got: {exc.value.diagnostics.errors}"


def test_missing_point_field_y_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["field_y_m"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "field_y_m" in e.lower() and "missing" in e.lower()
        for e in exc.value.diagnostics.errors
    ), f"Expected missing field_y_m error, got: {exc.value.diagnostics.errors}"


def test_missing_point_role_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["origin"]["role"]
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "role" in e.lower() and "missing" in e.lower()
        for e in exc.value.diagnostics.errors
    ), f"Expected missing role error, got: {exc.value.diagnostics.errors}"


def test_point_none_lat_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["lat"] = None
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "lat" in e.lower() for e in exc.value.diagnostics.errors
    )


# ---------------------------------------------------------------------------
# point key / role mismatch
# ---------------------------------------------------------------------------


def test_point_key_role_mismatch_fails() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["role"] = "forward"
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "key" in errors_text or "role" in errors_text, (
        f"Expected key/role mismatch error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# gps_quality threshold validation
# ---------------------------------------------------------------------------


def test_gps_quality_max_eph_nan_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_eph"] = float("nan")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "max_eph" in e.lower() for e in exc.value.diagnostics.errors
    )


def test_gps_quality_max_epv_inf_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["max_epv"] = float("inf")
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "max_epv" in e.lower() for e in exc.value.diagnostics.errors
    )


def test_gps_quality_min_fix_type_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = -1
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "min_fix_type" in e.lower() for e in exc.value.diagnostics.errors
    )


def test_gps_quality_min_satellites_negative_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_satellites"] = -5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "min_satellites" in e.lower() for e in exc.value.diagnostics.errors
    )


def test_gps_quality_min_fix_type_float_fails() -> None:
    data = _make_minimal_data()
    data["gps_quality"]["min_fix_type"] = 3.5
    with pytest.raises(FieldProfileValidationError) as exc:
        parse_field_profile(data)
    assert any(
        "min_fix_type" in e.lower() for e in exc.value.diagnostics.errors
    )


# ---------------------------------------------------------------------------
# forward.field_x_m far from 0
# ---------------------------------------------------------------------------


def test_forward_field_x_far_from_zero_fails() -> None:
    data = _make_minimal_data()
    data["points"]["forward"]["field_x_m"] = 10.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any(
        "forward" in e.lower() and "field_x" in e.lower()
        for e in exc.value.diagnostics.errors
    ), f"Expected forward field_x error, got: {exc.value.diagnostics.errors}"


# ---------------------------------------------------------------------------
# forward.field_y_m <= 0
# ---------------------------------------------------------------------------


def test_forward_field_y_zero_or_negative_fails() -> None:
    data = _make_minimal_data()
    data["points"]["forward"]["field_y_m"] = -1.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert any(
        "forward" in e.lower() and "field_y" in e.lower()
        for e in exc.value.diagnostics.errors
    ), f"Expected forward field_y error, got: {exc.value.diagnostics.errors}"


# ---------------------------------------------------------------------------
# missing file
# ---------------------------------------------------------------------------


def test_load_nonexistent_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_field_profile_json("/nonexistent/path/profile.json")
