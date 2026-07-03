"""Tests for RuntimeContextBuilder field-reference bridge methods."""
from __future__ import annotations

import math

import pytest

from app.runtime_context import RuntimeContextBuilder


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _builder():
    return RuntimeContextBuilder()


def _confirm(builder, yaw=0.5, ox=10.0, oy=20.0, oz=-1.0, source="test", ts=1000.0):
    return builder.confirm_field_reference(
        field_heading_yaw_rad=yaw,
        origin_local_x=ox,
        origin_local_y=oy,
        origin_local_z=oz,
        source=source,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# confirm_field_reference
# ---------------------------------------------------------------------------


def test_confirm_sets_confirmed_flags():
    b = _builder()
    assert not b.field_heading_confirmed
    assert not b.field_origin_confirmed

    ok = _confirm(b)
    assert ok is True
    assert b.field_heading_confirmed is True
    assert b.field_origin_confirmed is True


def test_confirm_stores_values():
    b = _builder()
    _confirm(b, yaw=0.8, ox=1.0, oy=2.0, oz=-3.0, source="unit_test", ts=1234.5)
    assert b.field_heading_yaw_rad == pytest.approx(0.8)
    assert b.field_heading_source == "unit_test"
    assert b.field_heading_time == pytest.approx(1234.5)
    assert b.field_origin_local_x == pytest.approx(1.0)
    assert b.field_origin_local_y == pytest.approx(2.0)
    assert b.field_origin_local_z == pytest.approx(-3.0)
    assert b.field_origin_time == pytest.approx(1234.5)


def test_confirm_normalizes_yaw():
    b = _builder()
    _confirm(b, yaw=3.0 * math.pi)  # 3π rounds to π
    assert b.field_heading_yaw_rad == pytest.approx(math.pi, abs=1e-9)


def test_confirm_accepts_none_origin_z():
    b = _builder()
    ok = b.confirm_field_reference(
        field_heading_yaw_rad=0.3,
        origin_local_x=5.0,
        origin_local_y=6.0,
        origin_local_z=None,
        source="test",
    )
    assert ok is True
    assert b.field_origin_local_z is None


def test_confirm_rejects_none_yaw():
    b = _builder()
    ok = b.confirm_field_reference(
        field_heading_yaw_rad=None,
        origin_local_x=1.0,
        origin_local_y=2.0,
    )
    assert ok is False
    assert b.field_heading_confirmed is False


def test_confirm_rejects_nan_yaw():
    b = _builder()
    ok = b.confirm_field_reference(
        field_heading_yaw_rad=float("nan"),
        origin_local_x=1.0,
        origin_local_y=2.0,
    )
    assert ok is False


def test_confirm_rejects_none_origin():
    b = _builder()
    ok = b.confirm_field_reference(
        field_heading_yaw_rad=0.5,
        origin_local_x=None,
        origin_local_y=2.0,
    )
    assert ok is False


def test_no_old_confirm_field_heading():
    """The deprecated confirm_field_heading() method must not exist."""
    b = _builder()
    assert not hasattr(b, "confirm_field_heading"), (
        "Old confirm_field_heading(yaw_rad, drone, source) must not exist"
    )


# ---------------------------------------------------------------------------
# field_transform_ready
# ---------------------------------------------------------------------------


def test_transform_not_ready_initially():
    b = _builder()
    assert b.field_transform_ready() is False


def test_transform_ready_after_confirm():
    b = _builder()
    _confirm(b)
    assert b.field_transform_ready() is True


def test_transform_not_ready_missing_origin():
    b = _builder()
    b.field_heading_confirmed = True
    b.field_heading_yaw_rad = 0.5
    assert b.field_transform_ready() is False  # origin not confirmed


def test_transform_not_ready_missing_heading():
    b = _builder()
    b.field_origin_confirmed = True
    b.field_origin_local_x = 1.0
    b.field_origin_local_y = 2.0
    assert b.field_transform_ready() is False  # heading not confirmed


# ---------------------------------------------------------------------------
# field_transform dict
# ---------------------------------------------------------------------------


def test_field_transform_dict():
    b = _builder()
    _confirm(b, yaw=0.7, ox=3.0, oy=4.0, oz=-5.0)
    tf = b.field_transform()
    assert tf["heading_yaw_rad"] == pytest.approx(0.7)
    assert tf["origin_local_x"] == pytest.approx(3.0)
    assert tf["origin_local_y"] == pytest.approx(4.0)
    assert tf["origin_local_z"] == pytest.approx(-5.0)
    assert tf["confirmed"] is True
    assert tf["convention"] == "field_y_forward_field_x_right"


# ---------------------------------------------------------------------------
# local_to_field_xy / field_to_local_xy
# ---------------------------------------------------------------------------


def test_local_to_field_xy_yaw_zero():
    b = _builder()
    _confirm(b, yaw=0.0, ox=10.0, oy=20.0)
    # Point 10 m north of origin: local_x=20.0, local_y=20.0
    result = b.local_to_field_xy(20.0, 20.0)
    assert result is not None
    fx, fy = result
    assert fx == pytest.approx(0.0)   # no east offset → field_x=0
    assert fy == pytest.approx(10.0)  # 10 m north → field_y=10


def test_field_to_local_xy_yaw_zero():
    b = _builder()
    _confirm(b, yaw=0.0, ox=10.0, oy=20.0)
    result = b.field_to_local_xy(0.0, 10.0)
    assert result is not None
    ln, le = result
    assert ln == pytest.approx(20.0)
    assert le == pytest.approx(20.0)


def test_local_to_field_xy_not_ready():
    b = _builder()
    assert b.local_to_field_xy(1.0, 2.0) is None


def test_field_to_local_xy_not_ready():
    b = _builder()
    assert b.field_to_local_xy(1.0, 2.0) is None


def test_local_to_field_xy_invalid_input():
    b = _builder()
    _confirm(b)
    assert b.local_to_field_xy(None, 2.0) is None
    assert b.local_to_field_xy(1.0, None) is None


# ---------------------------------------------------------------------------
# field_position_from_drone
# ---------------------------------------------------------------------------


def test_field_position_from_valid_drone():
    b = _builder()
    _confirm(b, yaw=0.0, ox=0.0, oy=0.0)
    # Drone at 0 north, 10 east → field_x=10, field_y=0 with yaw=0
    drone = {"local_position_valid": True, "local_x": 0.0, "local_y": 10.0, "local_z": -3.0}
    result = b.field_position_from_drone(drone)
    assert result is not None
    assert result["x"] == pytest.approx(10.0)
    assert result["y"] == pytest.approx(0.0)
    assert result["z"] == pytest.approx(-3.0)
    assert result["source"] == "field_heading"
    assert result["confirmed"] is True


def test_field_position_from_invalid_drone():
    b = _builder()
    _confirm(b)
    drone = {"local_position_valid": False, "local_x": 0.0, "local_y": 0.0, "local_z": 0.0}
    assert b.field_position_from_drone(drone) is None


def test_field_position_from_nondict():
    b = _builder()
    _confirm(b)
    assert b.field_position_from_drone(None) is None


# ---------------------------------------------------------------------------
# clear_field_heading
# ---------------------------------------------------------------------------


def test_clear_field_heading():
    b = _builder()
    _confirm(b)
    assert b.field_heading_confirmed is True

    b.clear_field_heading()

    assert b.field_heading_confirmed is False
    assert b.field_origin_confirmed is False
    assert b.field_heading_yaw_rad is None
    assert b.field_heading_source == ""
    assert b.field_heading_time is None
    assert b.field_origin_local_x is None
    assert b.field_origin_local_y is None
    assert b.field_origin_local_z is None
    assert b.field_origin_time is None
    assert b.field_transform_ready() is False
