"""Unit tests for app.field_profile_service — binding computation."""

from __future__ import annotations

import math
import os
from typing import Any, Dict

import pytest

from app.field_profile import (
    FieldProfile,
    FieldProfileDiagnostics,
    FieldProfileValidationError,
    load_field_profile_json,
    parse_field_profile,
    validate_field_profile,
)
from app.field_profile_service import (
    BindResult,
    CheckPointResult,
    FieldProfileService,
)
from app.field_reference import (  # Phase B private import for verification
    _gps_bearing_rad,
    _gps_distance_m,
    _gps_enu_deltas,
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


def _load_example() -> FieldProfile:
    return load_field_profile_json(EXAMPLE_PROFILE_PATH)


def _make_north_profile() -> FieldProfile:
    """O→F purely north, ~33.4 m baseline."""
    data: Dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "north_test",
        "name": "North Test",
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
                "lat": 34.0003,  # ~33.4 m north
                "lon": 108.0,
                "field_x_m": 0.0,
                "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


def _make_east_profile() -> FieldProfile:
    """O→F purely east, ~33.4 m baseline."""
    data: Dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "east_test",
        "name": "East Test",
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
                "lat": 34.0,
                "lon": 108.0003,  # ~33.4 m east
                "field_x_m": 0.0,
                "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


def _make_south_profile() -> FieldProfile:
    """O→F purely south, ~33.4 m baseline."""
    data: Dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "south_test",
        "name": "South Test",
        "coordinate_convention": {
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        },
        "points": {
            "origin": {
                "name": "O",
                "role": "origin",
                "lat": 34.0003,
                "lon": 108.0,
                "field_x_m": 0.0,
                "field_y_m": 0.0,
            },
            "forward": {
                "name": "F",
                "role": "forward",
                "lat": 34.0,
                "lon": 108.0,
                "field_x_m": 0.0,
                "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


def _make_west_profile() -> FieldProfile:
    """O→F purely west, ~33.4 m baseline."""
    data: Dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "west_test",
        "name": "West Test",
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
                "lon": 108.0003,
                "field_x_m": 0.0,
                "field_y_m": 0.0,
            },
            "forward": {
                "name": "F",
                "role": "forward",
                "lat": 34.0,
                "lon": 108.0,
                "field_x_m": 0.0,
                "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


def _profile_from_data(data: Dict[str, Any]) -> FieldProfile:
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    if not diag.ok:
        raise FieldProfileValidationError(diag)
    return profile


def _bind(
    profile: FieldProfile,
    current_lat: float = 34.0,
    current_lon: float = 108.0,
    current_local_n_m: float = 100.0,
    current_local_e_m: float = 200.0,
    current_local_z_m: float = -50.0,
    gps_fix_type: int = 3,
    satellites_visible: int = 12,
    gps_eph: float = 1.0,
    gps_epv: float = 2.0,
) -> BindResult:
    return FieldProfileService.bind_profile_to_current_vehicle(
        profile=profile,
        current_lat=current_lat,
        current_lon=current_lon,
        current_local_n_m=current_local_n_m,
        current_local_e_m=current_local_e_m,
        current_local_z_m=current_local_z_m,
        gps_fix_type=gps_fix_type,
        satellites_visible=satellites_visible,
        gps_eph=gps_eph,
        gps_epv=gps_epv,
    )


# ---------------------------------------------------------------------------
# current GPS at O → field ≈ (0, 0), origin_local = current_local
# ---------------------------------------------------------------------------


def test_bind_at_origin_gives_zero_field_position() -> None:
    """When vehicle GPS equals origin GPS, field position is (0,0) and
    origin_local equals current_local."""
    profile = _load_example()
    origin = profile.origin

    result = _bind(
        profile,
        current_lat=origin.lat,
        current_lon=origin.lon,
        current_local_n_m=100.0,
        current_local_e_m=200.0,
        current_local_z_m=-50.0,
    )

    assert result.ok
    assert result.current_field_x_m == pytest.approx(0.0, abs=1e-6)
    assert result.current_field_y_m == pytest.approx(0.0, abs=1e-6)
    assert result.origin_local_n_m == pytest.approx(100.0)
    assert result.origin_local_e_m == pytest.approx(200.0)
    assert result.origin_local_z_m == pytest.approx(-50.0)


# ---------------------------------------------------------------------------
# current GPS at F → field_y ≈ baseline, field_x ≈ 0
# ---------------------------------------------------------------------------


def test_bind_at_forward_gives_field_y_equals_baseline() -> None:
    """When vehicle GPS equals forward GPS, field_y ≈ baseline, field_x ≈ 0."""
    profile = _load_example()
    forward = profile.forward
    origin = profile.origin

    result = _bind(
        profile,
        current_lat=forward.lat,
        current_lon=forward.lon,
        current_local_n_m=100.0,
        current_local_e_m=200.0,
        current_local_z_m=-50.0,
    )

    assert result.ok
    assert result.current_field_x_m == pytest.approx(0.0, abs=1e-3)
    expected_baseline = _gps_distance_m(
        origin.lat, origin.lon, forward.lat, forward.lon
    )
    assert result.current_field_y_m == pytest.approx(expected_baseline, rel=1e-6)
    assert result.baseline_m == pytest.approx(expected_baseline, rel=1e-6)


# ---------------------------------------------------------------------------
# heading cardinal directions
# ---------------------------------------------------------------------------


def test_heading_north() -> None:
    """O→F purely north → heading ≈ 0 rad (0°)."""
    profile = _make_north_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(0.0, abs=1e-6)
    assert result.field_heading_deg == pytest.approx(0.0, abs=1e-3)


def test_heading_east() -> None:
    """O→F purely east → heading ≈ π/2 rad (90°)."""
    profile = _make_east_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(math.pi / 2, abs=1e-6)
    assert result.field_heading_deg == pytest.approx(90.0, abs=1e-3)


def test_heading_south() -> None:
    """O→F purely south → heading ≈ ±π rad (180° or -180°)."""
    profile = _make_south_profile()
    result = _bind(profile)
    assert result.ok
    # Normalised to (-π, π], so south is π or -π (both ≈ 180° absolute).
    assert abs(result.field_heading_yaw_rad) == pytest.approx(math.pi, abs=1e-6)
    assert abs(result.field_heading_deg) == pytest.approx(180.0, abs=1e-3)


def test_heading_west() -> None:
    """O→F purely west → heading ≈ -π/2 rad (-90°)."""
    profile = _make_west_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(-math.pi / 2, abs=1e-6)
    assert result.field_heading_deg == pytest.approx(-90.0, abs=1e-3)


# ---------------------------------------------------------------------------
# arbitrary LOCAL_NED offset → origin_local back-calculated correctly
# ---------------------------------------------------------------------------


def test_arbitrary_local_ned_offset() -> None:
    """Given an arbitrary local position, the computed origin_local must
    satisfy: current_local - d_OC == origin_local."""
    profile = _load_example()
    origin = profile.origin

    # Place vehicle at a GPS offset from origin
    # ~10 m north, ~15 m east of origin (using 1 deg ≈ 111,195 m)
    current_lat = origin.lat + 10.0 / 111195.0
    current_lon = origin.lon + 15.0 / (111195.0 * math.cos(math.radians(origin.lat)))

    current_n = 500.0
    current_e = -300.0
    current_z = -75.0

    result = _bind(
        profile,
        current_lat=current_lat,
        current_lon=current_lon,
        current_local_n_m=current_n,
        current_local_e_m=current_e,
        current_local_z_m=current_z,
    )

    assert result.ok

    # Verify: origin_local + d_OC should equal current_local
    d_north, d_east = _gps_enu_deltas(
        origin.lat, origin.lon, current_lat, current_lon
    )
    assert result.origin_local_n_m + d_north == pytest.approx(current_n, abs=1e-6)
    assert result.origin_local_e_m + d_east == pytest.approx(current_e, abs=1e-6)


# ---------------------------------------------------------------------------
# altitude / z_down preserved as-is
# ---------------------------------------------------------------------------


def test_bind_preserves_altitude_sign() -> None:
    """origin_local_z_m must equal current_local_z_m unchanged (no sign flip)."""
    profile = _load_example()

    for z in (-50.0, 0.0, 10.0, -0.001):
        result = _bind(profile, current_local_z_m=z)
        assert result.ok
        assert result.origin_local_z_m == pytest.approx(z)


# ---------------------------------------------------------------------------
# GPS quality — fix_type too low
# ---------------------------------------------------------------------------


def test_gps_fix_type_too_low_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_fix_type=2)  # need ≥ 3
    assert not result.ok
    assert any("fix_type" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# GPS quality — satellites too low
# ---------------------------------------------------------------------------


def test_gps_satellites_too_low_fails() -> None:
    profile = _load_example()
    result = _bind(profile, satellites_visible=8)  # need ≥ 10
    assert not result.ok
    assert any("satellites" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# GPS quality — eph / epv missing
# ---------------------------------------------------------------------------


def test_gps_eph_missing_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_eph=None)
    assert not result.ok
    assert any("eph" in e.lower() and "missing" in e.lower() for e in result.errors)


def test_gps_epv_missing_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_epv=None)
    assert not result.ok
    assert any("epv" in e.lower() and "missing" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# GPS quality — eph / epv negative
# ---------------------------------------------------------------------------


def test_gps_eph_negative_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_eph=-0.5)
    assert not result.ok
    assert any("eph" in e.lower() and "negative" in e.lower() for e in result.errors)


def test_gps_epv_negative_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_epv=-1.0)
    assert not result.ok
    assert any("epv" in e.lower() and "negative" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# GPS quality — eph / epv non-finite
# ---------------------------------------------------------------------------


def test_gps_eph_nan_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_eph=float("nan"))
    assert not result.ok
    assert any("eph" in e.lower() for e in result.errors)


def test_gps_epv_inf_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_epv=float("inf"))
    assert not result.ok
    assert any("epv" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# eph / epv exceeds threshold
# ---------------------------------------------------------------------------


def test_gps_eph_exceeds_max_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_eph=10.0)  # max is 2.5
    assert not result.ok
    assert any("eph" in e.lower() for e in result.errors)


def test_gps_epv_exceeds_max_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_epv=6.0)  # max is 5.0
    assert not result.ok
    assert any("epv" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# bind result does not implicitly confirm / freeze / send
# ---------------------------------------------------------------------------


def test_bind_result_has_no_side_effects() -> None:
    """BindResult is a pure data class — accessing it must not trigger any
    system state change."""
    profile = _load_example()
    result = _bind(profile)

    # The result is just data.
    assert isinstance(result, BindResult)
    assert result.ok

    # No confirm/freeze/send attributes exist on the result.
    assert not hasattr(result, "is_confirmed")
    assert not hasattr(result, "is_frozen")
    assert not hasattr(result, "sent_commands")

    # Calling bind twice gives the same result (idempotent).
    result2 = _bind(profile)
    assert result2.origin_local_n_m == pytest.approx(result.origin_local_n_m)
    assert result2.origin_local_e_m == pytest.approx(result.origin_local_e_m)
    assert result2.field_heading_yaw_rad == pytest.approx(result.field_heading_yaw_rad)


# ---------------------------------------------------------------------------
# check_points populated
# ---------------------------------------------------------------------------


def test_check_points_are_populated() -> None:
    """When the profile has L and R, they appear in check_points."""
    profile = _load_example()
    result = _bind(profile)

    assert result.ok
    roles = {cp.role for cp in result.check_points}
    assert "left_check" in roles
    assert "right_check" in roles


# ---------------------------------------------------------------------------
# current_field_x/y round-trip consistency
# ---------------------------------------------------------------------------


def test_field_position_consistent_with_heading() -> None:
    """For a north-oriented profile, a GPS offset east should give
    positive field_x (right)."""
    profile = _make_north_profile()
    origin = profile.origin

    # Vehicle ~10 m east of origin
    current_lon = origin.lon + 10.0 / (
        111195.0 * math.cos(math.radians(origin.lat))
    )

    result = _bind(profile, current_lat=origin.lat, current_lon=current_lon)

    assert result.ok
    # Heading north → east offset = positive field_x (right side)
    assert result.current_field_x_m > 0.0
    assert result.current_field_y_m == pytest.approx(0.0, abs=0.1)


def test_field_position_north_of_origin() -> None:
    """For a north-oriented profile, a GPS offset north should give
    positive field_y (forward)."""
    profile = _make_north_profile()
    origin = profile.origin

    # Vehicle ~10 m north of origin
    current_lat = origin.lat + 10.0 / 111195.0

    result = _bind(profile, current_lat=current_lat, current_lon=origin.lon)

    assert result.ok
    assert result.current_field_y_m > 0.0
    assert result.current_field_x_m == pytest.approx(0.0, abs=0.1)
