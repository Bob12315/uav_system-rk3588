"""Unit tests for app.field_profile_service — binding computation."""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional

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
from app.field_reference import (
    _gps_bearing_rad,
    _gps_distance_m,
    _gps_enu_deltas,
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


def _load_example() -> FieldProfile:
    return load_field_profile_json(EXAMPLE_PROFILE_PATH)


def _profile_from_data(data: Dict[str, Any]) -> FieldProfile:
    profile = parse_field_profile(data)
    diag = validate_field_profile(profile)
    if not diag.ok:
        raise FieldProfileValidationError(diag)
    return profile


def _make_north_profile() -> FieldProfile:
    data: Dict[str, Any] = {
        "schema_version": 1, "profile_id": "north_test", "name": "North",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "points": {
            "origin": {"name": "O", "role": "origin", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
            "forward": {"name": "F", "role": "forward", "lat": 34.0003, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 33.36},
        },
    }
    return _profile_from_data(data)


def _make_east_profile() -> FieldProfile:
    dlon = 33.36 / _DEG_TO_M_LON_AT_34
    data: Dict[str, Any] = {
        "schema_version": 1, "profile_id": "east_test", "name": "East",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "points": {
            "origin": {"name": "O", "role": "origin", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
            "forward": {"name": "F", "role": "forward", "lat": 34.0, "lon": 108.0 + dlon, "field_x_m": 0.0, "field_y_m": 33.36},
        },
    }
    return _profile_from_data(data)


def _make_south_profile() -> FieldProfile:
    data: Dict[str, Any] = {
        "schema_version": 1, "profile_id": "south_test", "name": "South",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "points": {
            "origin": {"name": "O", "role": "origin", "lat": 34.0003, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
            "forward": {"name": "F", "role": "forward", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 33.36},
        },
    }
    return _profile_from_data(data)


def _make_west_profile() -> FieldProfile:
    dlon = 33.36 / _DEG_TO_M_LON_AT_34
    data: Dict[str, Any] = {
        "schema_version": 1, "profile_id": "west_test", "name": "West",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "points": {
            "origin": {"name": "O", "role": "origin", "lat": 34.0, "lon": 108.0 + dlon, "field_x_m": 0.0, "field_y_m": 0.0},
            "forward": {"name": "F", "role": "forward", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 33.36},
        },
    }
    return _profile_from_data(data)


def _make_northeast_profile() -> FieldProfile:
    dlat = 23.58 / _DEG_TO_M_LAT
    dlon = 23.58 / _DEG_TO_M_LON_AT_34
    data: Dict[str, Any] = {
        "schema_version": 1, "profile_id": "ne_test", "name": "NE",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "points": {
            "origin": {"name": "O", "role": "origin", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
            "forward": {"name": "F", "role": "forward", "lat": 34.0 + dlat, "lon": 108.0 + dlon, "field_x_m": 0.0, "field_y_m": 33.36},
        },
    }
    return _profile_from_data(data)


def _bind(
    profile: FieldProfile,
    current_lat: Any = 34.0,
    current_lon: Any = 108.0,
    current_local_n_m: Any = 100.0,
    current_local_e_m: Any = 200.0,
    current_local_z_m: Any = -50.0,
    gps_fix_type: Any = 3,
    satellites_visible: Any = 12,
    gps_eph: Any = 1.0,
    gps_epv: Any = 2.0,
    timestamp: Optional[float] = None,
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


# ===================================================================
# existing binding tests
# ===================================================================


def test_bind_at_origin_gives_zero_field_position() -> None:
    profile = _load_example()
    origin = profile.origin
    result = _bind(profile, current_lat=origin.lat, current_lon=origin.lon)
    assert result.ok
    assert result.current_field_x_m == pytest.approx(0.0, abs=1e-6)
    assert result.current_field_y_m == pytest.approx(0.0, abs=1e-6)
    assert result.origin_local_n_m == pytest.approx(100.0)
    assert result.origin_local_e_m == pytest.approx(200.0)
    assert result.origin_local_z_m == pytest.approx(-50.0)


def test_bind_at_forward_gives_field_y_equals_baseline() -> None:
    profile = _load_example()
    forward = profile.forward
    origin = profile.origin
    result = _bind(profile, current_lat=forward.lat, current_lon=forward.lon)
    assert result.ok
    expected_baseline = _gps_distance_m(origin.lat, origin.lon, forward.lat, forward.lon)
    assert result.current_field_x_m == pytest.approx(0.0, abs=1e-3)
    assert result.current_field_y_m == pytest.approx(expected_baseline, rel=1e-6)
    assert result.baseline_m == pytest.approx(expected_baseline, rel=1e-6)


def test_heading_north() -> None:
    profile = _make_north_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(0.0, abs=1e-6)


def test_heading_east() -> None:
    profile = _make_east_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(math.pi / 2, abs=1e-6)


def test_heading_south() -> None:
    profile = _make_south_profile()
    result = _bind(profile)
    assert result.ok
    assert abs(result.field_heading_yaw_rad) == pytest.approx(math.pi, abs=1e-6)


def test_heading_west() -> None:
    profile = _make_west_profile()
    result = _bind(profile)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(-math.pi / 2, abs=1e-6)


def test_diagonal_heading_bind() -> None:
    profile = _make_northeast_profile()
    result = _bind(profile, current_lat=34.0, current_lon=108.0)
    assert result.ok
    assert result.field_heading_yaw_rad == pytest.approx(math.pi / 4, abs=1e-4)


def test_diagonal_heading_field_position() -> None:
    profile = _make_northeast_profile()
    result = _bind(profile, current_lat=profile.forward.lat, current_lon=profile.forward.lon)
    assert result.ok
    assert result.current_field_x_m == pytest.approx(0.0, abs=1e-3)
    assert result.current_field_y_m == pytest.approx(result.baseline_m, rel=1e-6)


def test_arbitrary_local_ned_offset() -> None:
    profile = _load_example()
    origin = profile.origin
    current_lat = origin.lat + 10.0 / _DEG_TO_M_LAT
    current_lon = origin.lon + 15.0 / _DEG_TO_M_LON_AT_34
    result = _bind(profile, current_lat=current_lat, current_lon=current_lon,
                   current_local_n_m=500.0, current_local_e_m=-300.0, current_local_z_m=-75.0)
    assert result.ok
    d_north, d_east = _gps_enu_deltas(origin.lat, origin.lon, current_lat, current_lon)
    assert result.origin_local_n_m + d_north == pytest.approx(500.0, abs=1e-6)
    assert result.origin_local_e_m + d_east == pytest.approx(-300.0, abs=1e-6)


def test_bind_preserves_altitude_sign() -> None:
    profile = _load_example()
    for z in (-50.0, 0.0, 10.0, -0.001):
        result = _bind(profile, current_local_z_m=z)
        assert result.ok
        assert result.origin_local_z_m == pytest.approx(z)


def test_gps_fix_type_too_low_fails() -> None:
    result = _bind(_load_example(), gps_fix_type=2)
    assert not result.ok
    assert any("fix_type" in e.lower() for e in result.errors)


def test_gps_satellites_too_low_fails() -> None:
    result = _bind(_load_example(), satellites_visible=8)
    assert not result.ok
    assert any("satellites" in e.lower() for e in result.errors)


def test_gps_eph_missing_fails() -> None:
    result = _bind(_load_example(), gps_eph=None)
    assert not result.ok
    assert any("eph" in e.lower() for e in result.errors)


def test_gps_epv_missing_fails() -> None:
    result = _bind(_load_example(), gps_epv=None)
    assert not result.ok
    assert any("epv" in e.lower() for e in result.errors)


def test_gps_eph_negative_fails() -> None:
    result = _bind(_load_example(), gps_eph=-0.5)
    assert not result.ok
    assert any("eph" in e.lower() for e in result.errors)


def test_gps_epv_negative_fails() -> None:
    result = _bind(_load_example(), gps_epv=-1.0)
    assert not result.ok
    assert any("epv" in e.lower() for e in result.errors)


def test_gps_eph_nan_fails() -> None:
    result = _bind(_load_example(), gps_eph=float("nan"))
    assert not result.ok
    assert any("eph" in e.lower() for e in result.errors)


def test_gps_epv_inf_fails() -> None:
    result = _bind(_load_example(), gps_epv=float("inf"))
    assert not result.ok
    assert any("epv" in e.lower() for e in result.errors)


def test_gps_eph_exceeds_max_fails() -> None:
    result = _bind(_load_example(), gps_eph=10.0)
    assert not result.ok
    assert any("eph" in e.lower() for e in result.errors)


def test_gps_epv_exceeds_max_fails() -> None:
    result = _bind(_load_example(), gps_epv=6.0)
    assert not result.ok
    assert any("epv" in e.lower() for e in result.errors)


def test_current_lat_out_of_range_fails() -> None:
    result = _bind(_load_example(), current_lat=91.0)
    assert not result.ok


def test_current_lon_out_of_range_fails() -> None:
    result = _bind(_load_example(), current_lon=181.0)
    assert not result.ok


def test_current_local_n_nan_fails() -> None:
    result = _bind(_load_example(), current_local_n_m=float("nan"))
    assert not result.ok


def test_current_local_e_inf_fails() -> None:
    result = _bind(_load_example(), current_local_e_m=float("inf"))
    assert not result.ok


def test_current_local_z_nan_fails() -> None:
    result = _bind(_load_example(), current_local_z_m=float("nan"))
    assert not result.ok


def test_bind_with_invalid_profile_fails() -> None:
    data: Dict[str, Any] = {
        "schema_version": 1, "profile_id": "bad", "name": "Bad",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "points": {
            "origin": {"name": "O", "role": "origin", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
            "forward": {"name": "F", "role": "forward", "lat": 34.0003, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 33.36},
            "left_check": {"name": "L", "role": "left_check", "lat": 34.00015, "lon": 107.99998, "field_x_m": 5.0, "field_y_m": 16.68},
        },
    }
    profile = parse_field_profile(data)
    result = FieldProfileService.bind_profile_to_current_vehicle(
        profile=profile,
        current_lat=34.0, current_lon=108.0,
        current_local_n_m=100.0, current_local_e_m=200.0, current_local_z_m=-50.0,
        gps_fix_type=3, satellites_visible=12,
        gps_eph=1.0, gps_epv=2.0,
    )
    assert not result.ok


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


def test_timestamp_stored() -> None:
    result = _bind(_load_example(), timestamp=1234567890.5)
    assert result.ok
    assert result.timestamp == pytest.approx(1234567890.5)


def test_timestamp_none_when_omitted() -> None:
    result = _bind(_load_example())
    assert result.ok
    assert result.timestamp is None


def test_check_points_are_populated() -> None:
    result = _bind(_load_example())
    assert result.ok
    roles = {cp.role for cp in result.check_points}
    assert "left_check" in roles
    assert "right_check" in roles


def test_field_position_consistent_with_heading() -> None:
    profile = _make_north_profile()
    origin = profile.origin
    current_lon = origin.lon + 10.0 / _DEG_TO_M_LON_AT_34
    result = _bind(profile, current_lat=origin.lat, current_lon=current_lon)
    assert result.ok
    assert result.current_field_x_m > 0.0
    assert result.current_field_y_m == pytest.approx(0.0, abs=0.1)


def test_field_position_north_of_origin() -> None:
    profile = _make_north_profile()
    origin = profile.origin
    current_lat = origin.lat + 10.0 / _DEG_TO_M_LAT
    result = _bind(profile, current_lat=current_lat, current_lon=origin.lon)
    assert result.ok
    assert result.current_field_y_m > 0.0
    assert result.current_field_x_m == pytest.approx(0.0, abs=0.1)


# ===================================================================
# NEW: input type hardening — no TypeError/ValueError leak
# ===================================================================


def test_current_lat_none_ok_false() -> None:
    result = _bind(_load_example(), current_lat=None)
    assert not result.ok


def test_current_lat_string_ok_false() -> None:
    result = _bind(_load_example(), current_lat="bad")
    assert not result.ok


def test_current_lat_nan_ok_false() -> None:
    result = _bind(_load_example(), current_lat=float("nan"))
    assert not result.ok


def test_current_lat_inf_ok_false() -> None:
    result = _bind(_load_example(), current_lat=float("inf"))
    assert not result.ok


def test_current_lon_none_ok_false() -> None:
    result = _bind(_load_example(), current_lon=None)
    assert not result.ok


def test_current_lon_string_ok_false() -> None:
    result = _bind(_load_example(), current_lon="bad")
    assert not result.ok


def test_current_lon_nan_ok_false() -> None:
    result = _bind(_load_example(), current_lon=float("nan"))
    assert not result.ok


def test_current_lon_inf_ok_false() -> None:
    result = _bind(_load_example(), current_lon=float("inf"))
    assert not result.ok


def test_current_local_n_none_ok_false() -> None:
    result = _bind(_load_example(), current_local_n_m=None)
    assert not result.ok


def test_current_local_n_string_ok_false() -> None:
    result = _bind(_load_example(), current_local_n_m="bad")
    assert not result.ok


def test_current_local_e_none_ok_false() -> None:
    result = _bind(_load_example(), current_local_e_m=None)
    assert not result.ok


def test_current_local_e_inf_neg_ok_false() -> None:
    result = _bind(_load_example(), current_local_e_m=-float("inf"))
    assert not result.ok


def test_current_local_z_none_ok_false() -> None:
    result = _bind(_load_example(), current_local_z_m=None)
    assert not result.ok


def test_current_local_z_string_ok_false() -> None:
    result = _bind(_load_example(), current_local_z_m="bad")
    assert not result.ok


def test_gps_fix_type_none_ok_false() -> None:
    result = _bind(_load_example(), gps_fix_type=None)
    assert not result.ok


def test_gps_fix_type_string_ok_false() -> None:
    result = _bind(_load_example(), gps_fix_type="abc")
    assert not result.ok


def test_gps_fix_type_bool_ok_false() -> None:
    result = _bind(_load_example(), gps_fix_type=True)
    assert not result.ok


def test_gps_fix_type_nan_ok_false() -> None:
    result = _bind(_load_example(), gps_fix_type=float("nan"))
    assert not result.ok


def test_gps_fix_type_inf_ok_false() -> None:
    result = _bind(_load_example(), gps_fix_type=float("inf"))
    assert not result.ok


def test_gps_fix_type_negative_ok_false() -> None:
    result = _bind(_load_example(), gps_fix_type=-1)
    assert not result.ok


def test_gps_fix_type_fractional_ok_false() -> None:
    result = _bind(_load_example(), gps_fix_type=3.5)
    assert not result.ok


def test_satellites_visible_none_ok_false() -> None:
    result = _bind(_load_example(), satellites_visible=None)
    assert not result.ok


def test_satellites_visible_string_ok_false() -> None:
    result = _bind(_load_example(), satellites_visible="abc")
    assert not result.ok


def test_satellites_visible_bool_ok_false() -> None:
    result = _bind(_load_example(), satellites_visible=False)
    assert not result.ok


def test_satellites_visible_nan_ok_false() -> None:
    result = _bind(_load_example(), satellites_visible=float("nan"))
    assert not result.ok


def test_satellites_visible_inf_ok_false() -> None:
    result = _bind(_load_example(), satellites_visible=float("inf"))
    assert not result.ok


def test_satellites_visible_negative_ok_false() -> None:
    result = _bind(_load_example(), satellites_visible=-5)
    assert not result.ok


def test_satellites_visible_fractional_ok_false() -> None:
    result = _bind(_load_example(), satellites_visible=10.5)
    assert not result.ok


def test_gps_eph_string_ok_false() -> None:
    result = _bind(_load_example(), gps_eph="bad")
    assert not result.ok


def test_gps_eph_bool_ok_false() -> None:
    result = _bind(_load_example(), gps_eph=True)
    assert not result.ok


def test_gps_epv_string_ok_false() -> None:
    result = _bind(_load_example(), gps_epv="bad")
    assert not result.ok


def test_gps_epv_bool_ok_false() -> None:
    result = _bind(_load_example(), gps_epv=False)
    assert not result.ok


# ===================================================================
# verify no TypeError/ValueError leak for all bad inputs
# ===================================================================


@pytest.mark.parametrize("kw, bad_value", [
    ("current_lat", None), ("current_lat", "bad"), ("current_lat", float("nan")),
    ("current_lon", None), ("current_lon", "bad"), ("current_lon", float("inf")),
    ("current_local_n_m", None), ("current_local_n_m", "bad"),
    ("current_local_e_m", None), ("current_local_e_m", float("nan")),
    ("current_local_z_m", None), ("current_local_z_m", "bad"),
    ("gps_fix_type", None), ("gps_fix_type", "abc"), ("gps_fix_type", True), ("gps_fix_type", 3.5),
    ("satellites_visible", None), ("satellites_visible", "abc"), ("satellites_visible", False), ("satellites_visible", 10.5),
    ("gps_eph", "bad"), ("gps_eph", True), ("gps_eph", -0.1),
    ("gps_epv", "bad"), ("gps_epv", False), ("gps_epv", -1.0),
])
def test_bad_input_returns_ok_false_no_exception(kw: str, bad_value: Any) -> None:
    """Every bad input must return BindResult(ok=False), never raise."""
    profile = _load_example()
    kwargs: Dict[str, Any] = {
        "current_lat": 34.0, "current_lon": 108.0,
        "current_local_n_m": 100.0, "current_local_e_m": 200.0, "current_local_z_m": -50.0,
        "gps_fix_type": 3, "satellites_visible": 12,
        "gps_eph": 1.0, "gps_epv": 2.0,
    }
    kwargs[kw] = bad_value
    # Must not raise.
    result = FieldProfileService.bind_profile_to_current_vehicle(profile=profile, **kwargs)
    assert not result.ok, f"Expected ok=False for {kw}={bad_value!r}, got ok=True"
