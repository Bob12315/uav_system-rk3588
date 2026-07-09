"""Tests for app.coordinate_transform — FIELD ↔ LOCAL_NED conversion."""
from __future__ import annotations

import math

import pytest

from app.coordinate_transform import (
    FieldPoint,
    LocalNedPoint,
    FieldReferenceError,
    field_to_gps,
    field_to_local_ned,
    gps_to_local_ned,
    local_ned_to_field,
)
from app.field_reference import FieldReference


def _make_ref(yaw_rad=0.0, origin_n=10.0, origin_e=20.0, origin_z=-1.0):
    """Build a confirmed, ready FieldReference for transform tests."""
    ref = FieldReference()
    ref.is_confirmed = True
    ref.origin_local_n_m = origin_n
    ref.origin_local_e_m = origin_e
    ref.origin_local_z_m = origin_z
    ref.field_heading_yaw_rad = yaw_rad
    return ref


def _make_unready_ref():
    """Build a FieldReference that is NOT ready (unconfirmed)."""
    return FieldReference()


def _make_gps_ref(origin_lat=30.0, origin_lon=120.0, origin_n=100.0, origin_e=200.0):
    """Build a FieldReference with GPS origin fields set for gps_to_local_ned."""
    ref = FieldReference()
    ref.is_confirmed = True
    ref.origin_lat = origin_lat
    ref.origin_lon = origin_lon
    ref.origin_local_n_m = origin_n
    ref.origin_local_e_m = origin_e
    ref.field_heading_yaw_rad = 0.0  # not used by gps_to_local_ned
    return ref


# ---------------------------------------------------------------------------
# field_to_local_ned
# ---------------------------------------------------------------------------


def test_field_y_forward_yaw_zero():
    """FIELD +Y (forward) → LOCAL north when yaw=0."""
    ref = _make_ref(yaw_rad=0.0, origin_n=10.0, origin_e=20.0)
    result = field_to_local_ned(field_x_m=0.0, field_y_m=10.0, altitude_m=5.0, reference=ref)
    assert result.north_m == pytest.approx(20.0)   # 10 + 10*cos(0) + 0
    assert result.east_m == pytest.approx(20.0)     # 20 + 10*sin(0) + 0
    assert result.z_down_m == pytest.approx(-5.0)   # -altitude


def test_field_y_forward_yaw_pi_half():
    """FIELD +Y (forward) → LOCAL east when yaw=π/2."""
    ref = _make_ref(yaw_rad=math.pi / 2, origin_n=10.0, origin_e=20.0)
    result = field_to_local_ned(field_x_m=0.0, field_y_m=10.0, altitude_m=3.0, reference=ref)
    # forward = (cos(π/2)=0, sin(π/2)=1) = east
    assert result.north_m == pytest.approx(10.0)
    assert result.east_m == pytest.approx(30.0)   # 20 + 10
    assert result.z_down_m == pytest.approx(-3.0)


def test_field_x_right_yaw_zero():
    """FIELD +X (right) → LOCAL east when yaw=0 (right = -sin, cos)."""
    ref = _make_ref(yaw_rad=0.0, origin_n=10.0, origin_e=20.0)
    result = field_to_local_ned(field_x_m=5.0, field_y_m=0.0, altitude_m=0.0, reference=ref)
    # right = (-sin(0)=0, cos(0)=1) → local_e +5
    assert result.north_m == pytest.approx(10.0)
    assert result.east_m == pytest.approx(25.0)
    assert result.z_down_m == pytest.approx(0.0)


def test_field_x_right_yaw_pi_half():
    """FIELD +X (right) → LOCAL south when yaw=π/2 (right = -1, 0)."""
    ref = _make_ref(yaw_rad=math.pi / 2, origin_n=10.0, origin_e=20.0)
    result = field_to_local_ned(field_x_m=5.0, field_y_m=0.0, altitude_m=0.0, reference=ref)
    # right = (-sin(π/2)=-1, cos(π/2)=0) → local_n -5
    assert result.north_m == pytest.approx(5.0)
    assert result.east_m == pytest.approx(20.0)


def test_field_combined_yaw_pi_quarter():
    """Combined FIELD x,y at yaw=π/4."""
    ref = _make_ref(yaw_rad=math.pi / 4, origin_n=0.0, origin_e=0.0)
    result = field_to_local_ned(field_x_m=2.0, field_y_m=2.0, altitude_m=1.0, reference=ref)
    cos45 = math.cos(math.pi / 4)
    sin45 = math.sin(math.pi / 4)
    expected_n = 2.0 * cos45 + 2.0 * (-sin45)  # = 0
    expected_e = 2.0 * sin45 + 2.0 * cos45    # = 2*sqrt(2) ≈ 2.828
    assert result.north_m == pytest.approx(expected_n)
    assert result.east_m == pytest.approx(expected_e)
    assert result.z_down_m == pytest.approx(-1.0)


def test_altitude_to_z_down():
    """altitude_m positive-up → z_down_m negative-down."""
    ref = _make_ref()
    result = field_to_local_ned(field_x_m=0.0, field_y_m=0.0, altitude_m=7.5, reference=ref)
    assert result.z_down_m == pytest.approx(-7.5)


def test_unready_reference_raises():
    """Calling field_to_local_ned with unready reference raises FieldReferenceError."""
    ref = _make_unready_ref()
    with pytest.raises(FieldReferenceError, match="not ready"):
        field_to_local_ned(1.0, 2.0, 3.0, reference=ref)


# ---------------------------------------------------------------------------
# local_ned_to_field
# ---------------------------------------------------------------------------


def test_local_ned_to_field_yaw_zero():
    """Inverse: LOCAL north → FIELD +Y when yaw=0."""
    ref = _make_ref(yaw_rad=0.0, origin_n=10.0, origin_e=20.0)
    result = local_ned_to_field(north_m=20.0, east_m=20.0, z_down_m=-4.0, reference=ref)
    assert result.field_x_m == pytest.approx(0.0)
    assert result.field_y_m == pytest.approx(10.0)
    assert result.altitude_m == pytest.approx(4.0)


def test_local_ned_to_field_yaw_pi_half():
    """Inverse: LOCAL east → FIELD +Y when yaw=π/2."""
    ref = _make_ref(yaw_rad=math.pi / 2, origin_n=10.0, origin_e=20.0)
    result = local_ned_to_field(north_m=10.0, east_m=30.0, z_down_m=-2.0, reference=ref)
    assert result.field_x_m == pytest.approx(0.0)
    assert result.field_y_m == pytest.approx(10.0)
    assert result.altitude_m == pytest.approx(2.0)


def test_local_ned_to_field_yaw_pi_quarter():
    """Inverse: round-trip consistency at yaw=π/4."""
    ref = _make_ref(yaw_rad=math.pi / 4, origin_n=5.0, origin_e=5.0)
    result = local_ned_to_field(north_m=15.0, east_m=15.0, z_down_m=-10.0, reference=ref)
    # round-trip
    back = field_to_local_ned(
        field_x_m=result.field_x_m,
        field_y_m=result.field_y_m,
        altitude_m=result.altitude_m,
        reference=ref,
    )
    assert back.north_m == pytest.approx(15.0)
    assert back.east_m == pytest.approx(15.0)
    assert back.z_down_m == pytest.approx(-10.0)


def test_local_ned_to_field_unready_raises():
    """Calling local_ned_to_field with unready reference raises FieldReferenceError."""
    ref = _make_unready_ref()
    with pytest.raises(FieldReferenceError, match="not ready"):
        local_ned_to_field(1.0, 2.0, -3.0, reference=ref)


# ---------------------------------------------------------------------------
# LocalNedPoint / FieldPoint dataclasses
# ---------------------------------------------------------------------------


def test_local_ned_point_fields():
    p = LocalNedPoint(north_m=1.0, east_m=2.0, z_down_m=-3.0)
    assert p.north_m == 1.0
    assert p.east_m == 2.0
    assert p.z_down_m == -3.0


def test_field_point_fields():
    p = FieldPoint(field_x_m=1.0, field_y_m=2.0, altitude_m=3.0)
    assert p.field_x_m == 1.0
    assert p.field_y_m == 2.0
    assert p.altitude_m == 3.0


# ---------------------------------------------------------------------------
# gps_to_local_ned
# ---------------------------------------------------------------------------


def test_gps_to_local_ned_origin_to_origin():
    """Origin GPS → local should equal origin_local."""
    ref = _make_gps_ref(origin_lat=30.0, origin_lon=120.0, origin_n=100.0, origin_e=200.0)
    result = gps_to_local_ned(lat=30.0, lon=120.0, altitude_m=5.0, reference=ref)
    assert result.north_m == pytest.approx(100.0)
    assert result.east_m == pytest.approx(200.0)
    assert result.z_down_m == pytest.approx(-5.0)


def test_gps_to_local_ned_north_offset():
    """GPS north of origin → positive local north offset."""
    ref = _make_gps_ref(origin_lat=30.0, origin_lon=120.0, origin_n=100.0, origin_e=200.0)
    # 1 degree north ≈ 111 km, use a tiny offset
    dlat = 0.0001  # ~11.1 m north
    result = gps_to_local_ned(lat=30.0 + dlat, lon=120.0, altitude_m=0.0, reference=ref)
    assert result.north_m > 100.0
    assert result.north_m == pytest.approx(100.0 + dlat * 60 * 1852, rel=1e-3)
    assert result.east_m == pytest.approx(200.0, abs=0.02)


def test_gps_to_local_ned_east_offset():
    """GPS east of origin → positive local east offset."""
    ref = _make_gps_ref(origin_lat=30.0, origin_lon=120.0, origin_n=100.0, origin_e=200.0)
    dlon = 0.0001  # ~9.6 m east at lat=30
    result = gps_to_local_ned(lat=30.0, lon=120.0 + dlon, altitude_m=0.0, reference=ref)
    assert result.east_m > 200.0
    assert result.north_m == pytest.approx(100.0, abs=0.02)


def test_field_to_gps_to_local_ned_roundtrip():
    """field→GPS→local_ned should match field→local_ned directly."""
    # Build a ref with both GPS and local origin, plus heading
    ref = FieldReference()
    ref.is_confirmed = True
    ref.origin_lat = 30.0
    ref.origin_lon = 120.0
    ref.origin_local_n_m = 100.0
    ref.origin_local_e_m = 200.0
    ref.field_heading_yaw_rad = math.radians(45.0)

    field_x, field_y, alt = 5.0, 10.0, 3.0
    # Direct field → local
    direct = field_to_local_ned(field_x, field_y, alt, reference=ref)
    # field → GPS → local
    gps = field_to_gps(field_x, field_y, alt, reference=ref)
    via_gps = gps_to_local_ned(gps.lat, gps.lon, alt, reference=ref)

    assert via_gps.north_m == pytest.approx(direct.north_m, abs=0.02)
    assert via_gps.east_m == pytest.approx(direct.east_m, abs=0.02)
    assert via_gps.z_down_m == pytest.approx(direct.z_down_m)


def test_gps_to_local_ned_missing_gps_origin_raises():
    """Calling gps_to_local_ned without GPS origin raises FieldReferenceError."""
    ref = _make_ref()  # no origin_lat/origin_lon
    with pytest.raises(FieldReferenceError, match="missing GPS or LOCAL origin"):
        gps_to_local_ned(lat=30.0, lon=120.0, altitude_m=5.0, reference=ref)


def test_gps_to_local_ned_missing_local_origin_raises():
    """Calling gps_to_local_ned without LOCAL origin raises FieldReferenceError."""
    ref = FieldReference()
    ref.is_confirmed = True
    ref.origin_lat = 30.0
    ref.origin_lon = 120.0
    # origin_local_n_m / origin_local_e_m not set
    with pytest.raises(FieldReferenceError, match="missing GPS or LOCAL origin"):
        gps_to_local_ned(lat=30.0, lon=120.0, altitude_m=5.0, reference=ref)
