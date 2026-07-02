"""Unit tests for app.field_profile — loading, parsing, and validation."""

from __future__ import annotations

import os
from typing import Any, Dict

import pytest

from app.field_profile import (
    FieldProfile,
    FieldProfileDiagnostics,
    FieldProfilePoint,
    FieldProfileValidationError,
    GpsQualityThresholds,
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
    """Return a dict that passes parse + validate."""
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
                "field_y_m": 40.0,
            },
            "left_check": {
                "name": "L",
                "role": "left_check",
                "lat": 34.00015,
                "lon": 107.99998,
                "field_x_m": -2.5,
                "field_y_m": 20.0,
            },
            "right_check": {
                "name": "R",
                "role": "right_check",
                "lat": 34.00015,
                "lon": 108.00002,
                "field_x_m": 2.5,
                "field_y_m": 20.0,
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
    assert "origin" in str(exc.value).lower() or any(
        "origin" in e.lower() for e in exc.value.diagnostics.errors
    )


def test_missing_forward_fails() -> None:
    data = _make_minimal_data()
    del data["points"]["forward"]
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    assert "forward" in str(exc.value).lower() or any(
        "forward" in e.lower() for e in exc.value.diagnostics.errors
    )


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
    data["points"]["origin"]["lat"] = -90.0
    data["points"]["forward"]["lat"] = -89.9997  # keep ~33m baseline
    profile = _profile_from_data(data)
    assert profile.origin.lat == -90.0


def test_lon_negative_180_accepted() -> None:
    data = _make_minimal_data()
    data["points"]["origin"]["lon"] = -180.0
    data["points"]["forward"]["lon"] = -180.0  # pure north baseline
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
    # ~3 m baseline (pure north)
    # 1 deg lat ≈ 111,195 m → 3 m ≈ 0.000027 deg
    data["points"]["origin"]["lat"] = 34.0
    data["points"]["origin"]["lon"] = 108.0
    data["points"]["forward"]["lat"] = 34.000027
    data["points"]["forward"]["lon"] = 108.0
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
    # ~7 m baseline (pure north)
    # 7 m ≈ 0.000063 deg
    data["points"]["origin"]["lat"] = 34.0
    data["points"]["origin"]["lon"] = 108.0
    data["points"]["forward"]["lat"] = 34.000063
    data["points"]["forward"]["lon"] = 108.0
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
    profile = _profile_from_data(data)
    assert profile.left_check is not None
    assert profile.left_check.field_x_m < 0.0


def test_right_check_positive_x_accepted() -> None:
    data = _make_minimal_data()
    data["points"]["right_check"]["field_x_m"] = 0.1
    profile = _profile_from_data(data)
    assert profile.right_check is not None
    assert profile.right_check.field_x_m > 0.0


# ---------------------------------------------------------------------------
# L/R swapped
# ---------------------------------------------------------------------------


def test_lr_swapped_fails() -> None:
    """L with positive x and R with negative x → swapped error."""
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = 2.5
    data["points"]["right_check"]["field_x_m"] = -2.5
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "swap" in errors_text or "inverted" in errors_text, (
        f"Expected swapped error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R same side
# ---------------------------------------------------------------------------


def test_lr_both_positive_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = 1.0
    data["points"]["right_check"]["field_x_m"] = 3.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "same side" in errors_text, (
        f"Expected same-side error, got: {exc.value.diagnostics.errors}"
    )


def test_lr_both_negative_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = -3.0
    data["points"]["right_check"]["field_x_m"] = -1.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "same side" in errors_text, (
        f"Expected same-side error, got: {exc.value.diagnostics.errors}"
    )


# ---------------------------------------------------------------------------
# L/R coincident / too close
# ---------------------------------------------------------------------------


def test_lr_coincident_fails() -> None:
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = -2.5
    data["points"]["left_check"]["field_y_m"] = 20.0
    data["points"]["right_check"]["field_x_m"] = -2.5
    data["points"]["right_check"]["field_y_m"] = 20.0
    # With L.x < 0 and R.x < 0 we already get same-side error, so test
    # with swapped-names but formally correct signs:
    # Actually the coincident check only fires when individual signs are ok.
    # Set them = same exact coords:
    data["points"]["right_check"]["field_x_m"] = -2.5
    data["points"]["left_check"]["field_x_m"] = -2.5
    data["points"]["right_check"]["field_y_m"] = 20.0
    data["points"]["left_check"]["field_y_m"] = 20.0
    # Both negative → same-side error caught first (before degeneracy check).
    # So coincident is only tested when signs are correct.  Set them to
    # correct signs but identical coords:
    data["points"]["left_check"]["field_x_m"] = -2.5
    data["points"]["right_check"]["field_x_m"] = 2.5
    data["points"]["left_check"]["field_y_m"] = 20.0
    data["points"]["right_check"]["field_y_m"] = 20.0
    # That's not coincident (5 m apart).  Make them truly coincident:
    data["points"]["left_check"]["field_x_m"] = 0.0  # not < 0 → sign error
    # Hmm.  To get coincident with correct signs we need L=-d, R=+d, d→0.
    # But d=0.0 means L.x=0 → left_check x>=0 error.
    # The truly coincident case without sign issues is essentially untestable
    # unless both are at (0,0) which violates sign rules.
    # Instead: L/R at different y but same x=0 → sign error for both.
    # The coincident check is most relevant when L/R have correct sign but
    # are extremely close (distance < LR_COINCIDENT_M).  We can test with
    # L.x=-1e-9, R.x=+1e-9 → distance ≈ 2e-9 < 1e-6 → coincident error.
    data["points"]["left_check"]["field_x_m"] = -1e-9
    data["points"]["right_check"]["field_x_m"] = 1e-9
    data["points"]["left_check"]["field_y_m"] = 20.0
    data["points"]["right_check"]["field_y_m"] = 20.0
    with pytest.raises(FieldProfileValidationError) as exc:
        _profile_from_data(data)
    errors_text = " ".join(exc.value.diagnostics.errors).lower()
    assert "coincident" in errors_text, (
        f"Expected coincident error, got: {exc.value.diagnostics.errors}"
    )


def test_lr_too_close_warns() -> None:
    """L and R 0.5 m apart → warning, not error."""
    data = _make_minimal_data()
    data["points"]["left_check"]["field_x_m"] = -0.25
    data["points"]["right_check"]["field_x_m"] = 0.25
    data["points"]["left_check"]["field_y_m"] = 20.0
    data["points"]["right_check"]["field_y_m"] = 20.0
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
    # Verify the extra data is preserved.
    assert "future_extension" in profile.extra
    assert profile.extra["future_extension"] == {"some": "value"}


# ---------------------------------------------------------------------------
# JSON round-trip stability
# ---------------------------------------------------------------------------


def test_parse_serialize_reparse_stable() -> None:
    """Parsing a dict, re-serialising its points, and re-parsing must be stable."""
    data = _make_minimal_data()
    profile1 = _profile_from_data(data)

    # Rebuild a JSON-like dict and re-parse
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
# missing file
# ---------------------------------------------------------------------------


def test_load_nonexistent_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_field_profile_json("/nonexistent/path/profile.json")
