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


def _profile_from_data(data: Dict[str, Any]) -> FieldProfile:
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    if not diag.ok:
        raise FieldProfileValidationError(diag)
    return profile


# -- cardinal direction profiles with self-consistent GPS/declared coords ----

# 1 degree latitude ≈ 111,195 m  (EARTH_RADIUS_M * π/180)
_DEG_TO_M_LAT = 111194.9
# 1 degree longitude at 34° ≈ 111,195 * cos(34°) ≈ 92,193 m
_DEG_TO_M_LON_AT_34 = 111194.9 * math.cos(math.radians(34.0))


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
                "name": "O", "role": "origin",
                "lat": 34.0, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 0.0,
            },
            "forward": {
                "name": "F", "role": "forward",
                "lat": 34.0003, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


def _make_east_profile() -> FieldProfile:
    """O→F purely east, ~27.7 m baseline."""
    dlon = 33.36 / _DEG_TO_M_LON_AT_34  # lon delta for 33.36 m at 34° lat
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
                "name": "O", "role": "origin",
                "lat": 34.0, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 0.0,
            },
            "forward": {
                "name": "F", "role": "forward",
                "lat": 34.0, "lon": 108.0 + dlon,
                "field_x_m": 0.0, "field_y_m": 33.36,
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
                "name": "O", "role": "origin",
                "lat": 34.0003, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 0.0,
            },
            "forward": {
                "name": "F", "role": "forward",
                "lat": 34.0, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


def _make_west_profile() -> FieldProfile:
    """O→F purely west, ~27.7 m baseline."""
    dlon = 33.36 / _DEG_TO_M_LON_AT_34
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
                "name": "O", "role": "origin",
                "lat": 34.0, "lon": 108.0 + dlon,
                "field_x_m": 0.0, "field_y_m": 0.0,
            },
            "forward": {
                "name": "F", "role": "forward",
                "lat": 34.0, "lon": 108.0,
                "field_x_m": 0.0, "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


def _make_northeast_profile() -> FieldProfile:
    """O→F northeast, ~33.4 m baseline each axis."""
    dlat = 23.58 / _DEG_TO_M_LAT  # ~23.58 m north
    dlon = 23.58 / _DEG_TO_M_LON_AT_34  # ~23.58 m east
    data: Dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "ne_test",
        "name": "NE Test",
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
                "lat": 34.0 + dlat, "lon": 108.0 + dlon,
                "field_x_m": 0.0, "field_y_m": 33.36,
            },
        },
    }
    return _profile_from_data(data)


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
    timestamp: float = None,
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
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# current GPS at O → field ≈ (0, 0), origin_local = current_local
# ---------------------------------------------------------------------------


def test_bind_at_origin_gives_zero_field_position() -> None:
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
    profile = _make_north_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(0.0, abs=1e-6)
    assert result.field_heading_deg == pytest.approx(0.0, abs=1e-3)


def test_heading_east() -> None:
    profile = _make_east_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(math.pi / 2, abs=1e-6)
    assert result.field_heading_deg == pytest.approx(90.0, abs=1e-3)


def test_heading_south() -> None:
    profile = _make_south_profile()
    result = _bind(profile)
    assert result.ok
    assert abs(result.field_heading_yaw_rad) == pytest.approx(math.pi, abs=1e-6)
    assert abs(result.field_heading_deg) == pytest.approx(180.0, abs=1e-3)


def test_heading_west() -> None:
    profile = _make_west_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(-math.pi / 2, abs=1e-6)
    assert result.field_heading_deg == pytest.approx(-90.0, abs=1e-3)


# ---------------------------------------------------------------------------
# diagonal heading bind
# ---------------------------------------------------------------------------


def test_diagonal_heading_bind() -> None:
    """Northeast heading: current pos at origin → field (0,0), heading ~45°."""
    profile = _make_northeast_profile()
    result = _bind(profile, current_lat=34.0, current_lon=108.0)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(math.pi / 4, abs=1e-4)
    assert result.field_heading_deg == pytest.approx(45.0, abs=1e-1)
    assert result.current_field_x_m == pytest.approx(0.0, abs=1e-6)
    assert result.current_field_y_m == pytest.approx(0.0, abs=1e-6)


def test_diagonal_heading_field_position() -> None:
    """Northeast heading: vehicle at F GPS → field_y ≈ baseline, field_x ≈ 0."""
    profile = _make_northeast_profile()
    result = _bind(
        profile,
        current_lat=profile.forward.lat,
        current_lon=profile.forward.lon,
    )
    assert result.ok
    assert result.current_field_x_m == pytest.approx(0.0, abs=1e-3)
    assert result.current_field_y_m == pytest.approx(result.baseline_m, rel=1e-6)


# ---------------------------------------------------------------------------
# arbitrary LOCAL_NED offset → origin_local back-calculated correctly
# ---------------------------------------------------------------------------


def test_arbitrary_local_ned_offset() -> None:
    profile = _load_example()
    origin = profile.origin

    current_lat = origin.lat + 10.0 / _DEG_TO_M_LAT
    current_lon = origin.lon + 15.0 / _DEG_TO_M_LON_AT_34

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
    d_north, d_east = _gps_enu_deltas(
        origin.lat, origin.lon, current_lat, current_lon
    )
    assert result.origin_local_n_m + d_north == pytest.approx(current_n, abs=1e-6)
    assert result.origin_local_e_m + d_east == pytest.approx(current_e, abs=1e-6)


# ---------------------------------------------------------------------------
# altitude / z_down preserved as-is
# ---------------------------------------------------------------------------


def test_bind_preserves_altitude_sign() -> None:
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
    result = _bind(profile, gps_fix_type=2)
    assert not result.ok
    assert any("fix_type" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# GPS quality — satellites too low
# ---------------------------------------------------------------------------


def test_gps_satellites_too_low_fails() -> None:
    profile = _load_example()
    result = _bind(profile, satellites_visible=8)
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
    result = _bind(profile, gps_eph=10.0)
    assert not result.ok
    assert any("eph" in e.lower() for e in result.errors)


def test_gps_epv_exceeds_max_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_epv=6.0)
    assert not result.ok
    assert any("epv" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# bind input validation — current_lat / current_lon out of range
# ---------------------------------------------------------------------------


def test_current_lat_out_of_range_fails() -> None:
    profile = _load_example()
    result = _bind(profile, current_lat=91.0)
    assert not result.ok
    assert any("current_lat" in e.lower() for e in result.errors)


def test_current_lon_out_of_range_fails() -> None:
    profile = _load_example()
    result = _bind(profile, current_lon=181.0)
    assert not result.ok
    assert any("current_lon" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# bind input validation — LOCAL_NED NaN / Inf
# ---------------------------------------------------------------------------


def test_current_local_n_nan_fails() -> None:
    profile = _load_example()
    result = _bind(profile, current_local_n_m=float("nan"))
    assert not result.ok
    assert any("current_local_n_m" in e.lower() for e in result.errors)


def test_current_local_e_inf_fails() -> None:
    profile = _load_example()
    result = _bind(profile, current_local_e_m=float("inf"))
    assert not result.ok
    assert any("current_local_e_m" in e.lower() for e in result.errors)


def test_current_local_z_nan_fails() -> None:
    profile = _load_example()
    result = _bind(profile, current_local_z_m=float("nan"))
    assert not result.ok
    assert any("current_local_z_m" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# bind input validation — gps_fix_type invalid
# ---------------------------------------------------------------------------


def test_gps_fix_type_none_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_fix_type=None)
    assert not result.ok
    assert any("fix_type" in e.lower() for e in result.errors)


def test_gps_fix_type_nan_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_fix_type=float("nan"))
    assert not result.ok
    assert any("fix_type" in e.lower() for e in result.errors)


def test_gps_fix_type_negative_fails() -> None:
    profile = _load_example()
    result = _bind(profile, gps_fix_type=-1)
    assert not result.ok
    assert any("fix_type" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# bind input validation — satellites_visible invalid
# ---------------------------------------------------------------------------


def test_satellites_visible_none_fails() -> None:
    profile = _load_example()
    result = _bind(profile, satellites_visible=None)
    assert not result.ok
    assert any("satellites" in e.lower() for e in result.errors)


def test_satellites_visible_nan_fails() -> None:
    profile = _load_example()
    result = _bind(profile, satellites_visible=float("nan"))
    assert not result.ok
    assert any("satellites" in e.lower() for e in result.errors)


def test_satellites_visible_negative_fails() -> None:
    profile = _load_example()
    result = _bind(profile, satellites_visible=-5)
    assert not result.ok
    assert any("satellites" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# bind input validation — profile not validated
# ---------------------------------------------------------------------------


def test_bind_with_invalid_profile_fails() -> None:
    """Construct a profile that would fail validation, bypass it, then bind."""
    data: Dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "bad",
        "name": "Bad",
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
                "field_x_m": 5.0, "field_y_m": 16.68,  # wrong sign
            },
        },
    }
    # parse succeeds but validate will fail → bind re-validates and fails
    profile = parse_field_profile(data)
    result = FieldProfileService.bind_profile_to_current_vehicle(
        profile=profile,
        current_lat=34.0, current_lon=108.0,
        current_local_n_m=100.0, current_local_e_m=200.0, current_local_z_m=-50.0,
        gps_fix_type=3, satellites_visible=12,
        gps_eph=1.0, gps_epv=2.0,
    )
    assert not result.ok


# ---------------------------------------------------------------------------
# bind result does not implicitly confirm / freeze / send
# ---------------------------------------------------------------------------


def test_bind_result_has_no_side_effects() -> None:
    profile = _load_example()
    result = _bind(profile)

    assert isinstance(result, BindResult)
    assert result.ok

    assert not hasattr(result, "is_confirmed")
    assert not hasattr(result, "is_frozen")
    assert not hasattr(result, "sent_commands")

    result2 = _bind(profile)
    assert result2.origin_local_n_m == pytest.approx(result.origin_local_n_m)
    assert result2.origin_local_e_m == pytest.approx(result.origin_local_e_m)
    assert result2.field_heading_yaw_rad == pytest.approx(result.field_heading_yaw_rad)


# ---------------------------------------------------------------------------
# timestamp stored in BindResult
# ---------------------------------------------------------------------------


def test_timestamp_stored() -> None:
    profile = _load_example()
    result = _bind(profile, timestamp=1234567890.5)
    assert result.ok
    assert result.timestamp == pytest.approx(1234567890.5)


def test_timestamp_none_when_omitted() -> None:
    profile = _load_example()
    result = _bind(profile)
    assert result.ok
    assert result.timestamp is None


# ---------------------------------------------------------------------------
# check_points populated
# ---------------------------------------------------------------------------


def test_check_points_are_populated() -> None:
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
    """For a north-oriented profile, a GPS offset east → positive field_x."""
    profile = _make_north_profile()
    origin = profile.origin

    current_lon = origin.lon + 10.0 / _DEG_TO_M_LON_AT_34
    result = _bind(profile, current_lat=origin.lat, current_lon=current_lon)

    assert result.ok
    assert result.current_field_x_m > 0.0
    assert result.current_field_y_m == pytest.approx(0.0, abs=0.1)


def test_field_position_north_of_origin() -> None:
    """For a north-oriented profile, a GPS offset north → positive field_y."""
    profile = _make_north_profile()
    origin = profile.origin

    current_lat = origin.lat + 10.0 / _DEG_TO_M_LAT
    result = _bind(profile, current_lat=current_lat, current_lon=origin.lon)

    assert result.ok
    assert result.current_field_y_m > 0.0
    assert result.current_field_x_m == pytest.approx(0.0, abs=0.1)
