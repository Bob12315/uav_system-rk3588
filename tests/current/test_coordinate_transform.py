from __future__ import annotations

import math

import pytest

from app.coordinate_transform import (
    FieldPoint,
    LocalNedPoint,
    field_to_local_ned,
    local_ned_to_field,
)
from app.field_reference import FieldReference, FieldReferenceError
from app.runtime_context import RuntimeContextBuilder


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_ready_ref(
    origin_n: float = 0.0,
    origin_e: float = 0.0,
    yaw: float = 0.0,
) -> FieldReference:
    """Return a confirmed, ready FieldReference."""
    ref = FieldReference()
    ref.set_origin_local_position(origin_n, origin_e)
    ref.set_manual_heading(yaw)
    ref.confirm()
    assert ref.is_ready()
    return ref


# ---------------------------------------------------------------------------
# dataclass smoke
# ---------------------------------------------------------------------------

def test_local_ned_point_construction() -> None:
    p = LocalNedPoint(north_m=1.0, east_m=2.0, z_down_m=-3.0)
    assert p.north_m == 1.0
    assert p.east_m == 2.0
    assert p.z_down_m == -3.0


def test_field_point_construction() -> None:
    p = FieldPoint(field_x_m=1.0, field_y_m=2.0, altitude_m=3.0)
    assert p.field_x_m == 1.0
    assert p.field_y_m == 2.0
    assert p.altitude_m == 3.0


# ---------------------------------------------------------------------------
# heading = 0
# ---------------------------------------------------------------------------

def test_heading_zero_field_plus_y_is_local_north() -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=0.0)
    result = field_to_local_ned(field_x_m=0.0, field_y_m=5.0, altitude_m=3.0, reference=ref)
    # FIELD +Y = forward = north when yaw=0
    assert result.north_m == pytest.approx(15.0)  # 10 + 5
    assert result.east_m == pytest.approx(20.0)   # unchanged
    assert result.z_down_m == pytest.approx(-3.0)


def test_heading_zero_field_plus_x_is_local_east() -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=0.0)
    result = field_to_local_ned(field_x_m=4.0, field_y_m=0.0, altitude_m=3.0, reference=ref)
    # FIELD +X = right = east when yaw=0
    assert result.north_m == pytest.approx(10.0)  # unchanged
    assert result.east_m == pytest.approx(24.0)   # 20 + 4
    assert result.z_down_m == pytest.approx(-3.0)


def test_heading_zero_origin_offset() -> None:
    """Non-zero origin with heading=0."""
    ref = _make_ready_ref(origin_n=100.0, origin_e=200.0, yaw=0.0)
    result = field_to_local_ned(field_x_m=0.0, field_y_m=10.0, altitude_m=2.0, reference=ref)
    assert result.north_m == pytest.approx(110.0)
    assert result.east_m == pytest.approx(200.0)
    assert result.z_down_m == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# heading = pi/2
# ---------------------------------------------------------------------------

def test_heading_pi_over_2_field_plus_y_is_local_east() -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=math.pi / 2.0)
    result = field_to_local_ned(field_x_m=0.0, field_y_m=5.0, altitude_m=3.0, reference=ref)
    # FIELD +Y = forward = east when yaw=pi/2
    assert result.north_m == pytest.approx(10.0)
    assert result.east_m == pytest.approx(25.0)  # 20 + 5


def test_heading_pi_over_2_field_plus_x_is_local_south() -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=math.pi / 2.0)
    result = field_to_local_ned(field_x_m=4.0, field_y_m=0.0, altitude_m=3.0, reference=ref)
    # FIELD +X = right = south when yaw=pi/2
    assert result.north_m == pytest.approx(6.0)   # 10 - 4
    assert result.east_m == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# heading = pi
# ---------------------------------------------------------------------------

def test_heading_pi_field_plus_y_is_local_south() -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=math.pi)
    result = field_to_local_ned(field_x_m=0.0, field_y_m=5.0, altitude_m=3.0, reference=ref)
    # FIELD +Y = forward = south when yaw=pi
    assert result.north_m == pytest.approx(5.0)   # 10 - 5
    assert result.east_m == pytest.approx(20.0)


def test_heading_pi_field_plus_x_is_local_west() -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=math.pi)
    result = field_to_local_ned(field_x_m=4.0, field_y_m=0.0, altitude_m=3.0, reference=ref)
    # FIELD +X = right = west when yaw=pi
    assert result.north_m == pytest.approx(10.0)
    assert result.east_m == pytest.approx(16.0)   # 20 - 4


# ---------------------------------------------------------------------------
# altitude → z_down
# ---------------------------------------------------------------------------

def test_altitude_3_meters_z_down_negative_3() -> None:
    ref = _make_ready_ref()
    result = field_to_local_ned(field_x_m=0.0, field_y_m=0.0, altitude_m=3.0, reference=ref)
    assert result.z_down_m == pytest.approx(-3.0)


def test_altitude_zero_z_down_zero() -> None:
    ref = _make_ready_ref()
    result = field_to_local_ned(field_x_m=0.0, field_y_m=0.0, altitude_m=0.0, reference=ref)
    assert result.z_down_m == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# roundtrip: field → local → field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fx", "fy", "alt", "yaw"),
    [
        (0.0, 0.0, 3.0, 0.0),
        (0.0, 10.0, 5.0, 0.0),
        (5.0, 0.0, 2.0, 0.0),
        (3.0, 4.0, 1.0, math.pi / 2.0),
        (-2.0, 8.0, 3.5, math.pi),
        (1.5, -3.0, 0.5, -math.pi / 4.0),
        (0.0, 0.0, 0.0, 1.234),
        (-7.0, -2.0, 10.0, 2.718),
    ],
)
def test_roundtrip_field_local_field(
    fx: float, fy: float, alt: float, yaw: float,
) -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=yaw)
    local = field_to_local_ned(fx, fy, alt, ref)
    back = local_ned_to_field(local.north_m, local.east_m, local.z_down_m, ref)
    assert back.field_x_m == pytest.approx(fx)
    assert back.field_y_m == pytest.approx(fy)
    assert back.altitude_m == pytest.approx(alt)


# ---------------------------------------------------------------------------
# roundtrip: local → field → local
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("n", "e", "zd", "yaw"),
    [
        (10.0, 20.0, -3.0, 0.0),
        (15.0, 20.0, -5.0, 0.0),
        (10.0, 25.0, -2.0, math.pi / 2.0),
        (5.0, 20.0, -1.0, math.pi),
    ],
)
def test_roundtrip_local_field_local(
    n: float, e: float, zd: float, yaw: float,
) -> None:
    ref = _make_ready_ref(origin_n=10.0, origin_e=20.0, yaw=yaw)
    field = local_ned_to_field(n, e, zd, ref)
    back = field_to_local_ned(field.field_x_m, field.field_y_m, field.altitude_m, ref)
    assert back.north_m == pytest.approx(n)
    assert back.east_m == pytest.approx(e)
    assert back.z_down_m == pytest.approx(zd)


# ---------------------------------------------------------------------------
# unconfirmed / not-ready rejection
# ---------------------------------------------------------------------------

def test_unconfirmed_reference_raises() -> None:
    ref = FieldReference()  # not confirmed
    with pytest.raises(FieldReferenceError, match="not ready"):
        field_to_local_ned(0.0, 0.0, 3.0, ref)


def test_missing_origin_raises() -> None:
    ref = FieldReference()
    ref.set_manual_heading(0.0)
    # heading set but no origin — confirm fails without origin_source
    ref.set_origin_gps(30.0, 120.0)
    ref.confirm()
    # confirmed but no LOCAL_NED origin → not ready
    with pytest.raises(FieldReferenceError, match="not ready"):
        field_to_local_ned(0.0, 0.0, 3.0, ref)


def test_missing_heading_raises() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    # origin set but no heading_source → confirm fails
    with pytest.raises(FieldReferenceError):
        ref.confirm()
    with pytest.raises(FieldReferenceError, match="not ready"):
        field_to_local_ned(0.0, 0.0, 3.0, ref)


# ---------------------------------------------------------------------------
# local_ned_to_field also rejects unready
# ---------------------------------------------------------------------------

def test_local_ned_to_field_unconfirmed_raises() -> None:
    ref = FieldReference()
    with pytest.raises(FieldReferenceError, match="not ready"):
        local_ned_to_field(0.0, 0.0, 0.0, ref)


# ---------------------------------------------------------------------------
# cross-validate with RuntimeContextBuilder.field_to_local_xy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("field_x", "field_y"),
    [
        (0.0, 0.0),
        (0.0, 5.0),
        (3.0, 0.0),
        (2.0, 4.0),
        (-1.0, 3.0),
    ],
)
def test_matches_runtime_context_field_to_local_xy(
    field_x: float, field_y: float,
) -> None:
    """CoordinateTransform results must match the existing
    RuntimeContextBuilder.field_to_local_xy for the same inputs."""
    origin_n = 10.0
    origin_e = 20.0
    yaw = 0.5

    # existing path
    builder = RuntimeContextBuilder()
    drone = {
        "local_position_valid": True,
        "local_x": origin_n,
        "local_y": origin_e,
        "local_z": -1.0,
    }
    assert builder.confirm_field_heading(yaw_rad=yaw, drone=drone, source="test")
    expected_n, expected_e = builder.field_to_local_xy(field_x, field_y)

    # new path
    ref = _make_ready_ref(origin_n=origin_n, origin_e=origin_e, yaw=yaw)
    result = field_to_local_ned(field_x, field_y, altitude_m=1.0, reference=ref)

    assert result.north_m == pytest.approx(expected_n)
    assert result.east_m == pytest.approx(expected_e)
