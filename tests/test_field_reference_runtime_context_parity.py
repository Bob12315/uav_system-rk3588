"""Parity tests: verify that the new CoordinateTransform functions produce
identical results to the existing RuntimeContextBuilder conversions.

These tests do NOT modify any production code — they only import, call,
and assert.
"""

from __future__ import annotations

import math

import pytest

from app.coordinate_transform import (
    field_to_local_ned,
    local_ned_to_field,
)
from app.field_reference import FieldReference, FieldReferenceError
from app.runtime_context import RuntimeContextBuilder


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_ready_ref(
    origin_n: float,
    origin_e: float,
    yaw: float,
) -> FieldReference:
    ref = FieldReference()
    ref.set_origin_local_position(origin_n, origin_e)
    ref.set_manual_heading(yaw)
    ref.confirm()
    assert ref.is_ready()
    return ref


def _make_ready_builder(
    origin_n: float,
    origin_e: float,
    yaw: float,
) -> RuntimeContextBuilder:
    builder = RuntimeContextBuilder()
    drone = {
        "local_position_valid": True,
        "local_x": origin_n,
        "local_y": origin_e,
        "local_z": -1.0,
    }
    assert builder.confirm_field_heading(yaw_rad=yaw, drone=drone, source="test")
    return builder


# ---------------------------------------------------------------------------
# field_to_local — extended angle coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("yaw_rad", "field_x", "field_y"),
    [
        # yaw = 0
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 10.0),
        (0.0, 5.0, 0.0),
        (0.0, -3.0, 7.0),
        # yaw = pi/2
        (math.pi / 2.0, 0.0, 0.0),
        (math.pi / 2.0, 0.0, 10.0),
        (math.pi / 2.0, 5.0, 0.0),
        (math.pi / 2.0, -3.0, 4.0),
        # yaw = pi
        (math.pi, 0.0, 0.0),
        (math.pi, 0.0, 5.0),
        (math.pi, 4.0, 0.0),
        # yaw = -pi/4  (north-west)
        (-math.pi / 4.0, 0.0, 10.0),
        (-math.pi / 4.0, 5.0, 0.0),
        # yaw = 3*pi/4  (south-east)
        (3.0 * math.pi / 4.0, 3.0, 4.0),
        (3.0 * math.pi / 4.0, -1.0, 2.0),
        # yaw = 0.5 (arbitrary)
        (0.5, 2.0, 4.0),
        (0.5, -1.5, 3.0),
    ],
)
def test_field_to_local_matches_runtime_context(
    yaw_rad: float,
    field_x: float,
    field_y: float,
) -> None:
    origin_n = 10.0
    origin_e = 20.0

    builder = _make_ready_builder(origin_n, origin_e, yaw_rad)
    expected_n, expected_e = builder.field_to_local_xy(field_x, field_y)

    ref = _make_ready_ref(origin_n, origin_e, yaw_rad)
    result = field_to_local_ned(field_x, field_y, altitude_m=1.0, reference=ref)

    assert result.north_m == pytest.approx(expected_n)
    assert result.east_m == pytest.approx(expected_e)


# ---------------------------------------------------------------------------
# local_to_field — inverse parity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("yaw_rad", "local_n", "local_e"),
    [
        # yaw = 0
        (0.0, 10.0, 20.0),
        (0.0, 15.0, 20.0),
        (0.0, 10.0, 25.0),
        # yaw = pi/2
        (math.pi / 2.0, 10.0, 20.0),
        (math.pi / 2.0, 5.0, 20.0),
        (math.pi / 2.0, 10.0, 30.0),
        # yaw = pi
        (math.pi, 10.0, 20.0),
        (math.pi, 10.0, 15.0),
        # yaw = -pi/4
        (-math.pi / 4.0, 12.0, 18.0),
        # yaw = 3*pi/4
        (3.0 * math.pi / 4.0, 8.0, 22.0),
        # yaw = 0.5
        (0.5, 11.0, 19.0),
    ],
)
def test_local_to_field_matches_runtime_context(
    yaw_rad: float,
    local_n: float,
    local_e: float,
) -> None:
    origin_n = 10.0
    origin_e = 20.0

    builder = _make_ready_builder(origin_n, origin_e, yaw_rad)
    expected_fx, expected_fy = builder.local_to_field_xy(local_n, local_e)

    ref = _make_ready_ref(origin_n, origin_e, yaw_rad)
    result = local_ned_to_field(local_n, local_e, z_down_m=-1.0, reference=ref)

    assert result.field_x_m == pytest.approx(expected_fx)
    assert result.field_y_m == pytest.approx(expected_fy)


# ---------------------------------------------------------------------------
# z_down = -altitude_m consistency
# ---------------------------------------------------------------------------

def test_z_down_equals_negative_altitude() -> None:
    """Both old and new conventions: z_down = -altitude_m."""
    ref = _make_ready_ref(10.0, 20.0, 0.0)

    for alt in (0.0, 3.0, 10.0, 0.5):
        result = field_to_local_ned(0.0, 0.0, altitude_m=alt, reference=ref)
        assert result.z_down_m == pytest.approx(-alt)


def test_altitude_roundtrip_preserves_sign() -> None:
    """field→local→field roundtrip must recover original altitude_m."""
    ref = _make_ready_ref(0.0, 0.0, 0.5)
    for alt in (0.0, 1.0, 3.5, 10.0):
        local = field_to_local_ned(0.0, 0.0, altitude_m=alt, reference=ref)
        assert local.z_down_m == pytest.approx(-alt)
        back = local_ned_to_field(local.north_m, local.east_m, local.z_down_m, reference=ref)
        assert back.altitude_m == pytest.approx(alt)


# ---------------------------------------------------------------------------
# unconfirmed rejection — semantic parity
# ---------------------------------------------------------------------------

def test_unconfirmed_rejection_new_module() -> None:
    """New CoordinateTransform raises FieldReferenceError when not ready."""
    ref = FieldReference()  # fresh, unconfirmed
    with pytest.raises(FieldReferenceError, match="not ready"):
        field_to_local_ned(0.0, 0.0, 3.0, ref)


def test_unconfirmed_rejection_old_module() -> None:
    """Old RuntimeContextBuilder returns None when not confirmed."""
    builder = RuntimeContextBuilder()
    # never called confirm_field_heading
    result = builder.field_to_local_xy(1.0, 2.0)
    assert result is None


def test_both_reject_field_waypoint_without_confirmation() -> None:
    """When field_heading/origin are NOT confirmed, both old and new paths
    refuse to produce a LOCAL_NED target."""
    # Old path: RuntimeContextBuilder returns None
    builder = RuntimeContextBuilder()
    assert builder.field_to_local_xy(1.0, 2.0) is None

    # New path: FieldReference raises
    ref = FieldReference()
    with pytest.raises(FieldReferenceError, match="not ready"):
        field_to_local_ned(0.0, 0.0, 3.0, ref)


# ---------------------------------------------------------------------------
# origin offset cross-check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("origin_n", "origin_e"),
    [
        (0.0, 0.0),
        (100.0, -50.0),
        (-10.0, 200.0),
        (1.5, 2.5),
    ],
)
def test_various_origins_match(origin_n: float, origin_e: float) -> None:
    """Non-zero / negative origins must produce identical results."""
    yaw = 0.75
    field_x, field_y = 3.0, 4.0

    builder = _make_ready_builder(origin_n, origin_e, yaw)
    expected_n, expected_e = builder.field_to_local_xy(field_x, field_y)

    ref = _make_ready_ref(origin_n, origin_e, yaw)
    result = field_to_local_ned(field_x, field_y, altitude_m=1.0, reference=ref)

    assert result.north_m == pytest.approx(expected_n)
    assert result.east_m == pytest.approx(expected_e)


# ---------------------------------------------------------------------------
# bidirectional consistency (new module internally consistent)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fx", "fy", "alt", "yaw"),
    [
        (1.0, 2.0, 3.0, 0.0),
        (0.0, 10.0, 5.0, math.pi / 2.0),
        (-3.0, 4.0, 2.0, math.pi),
        (2.0, -1.0, 0.0, -math.pi / 4.0),
    ],
)
def test_new_module_bidirectional_consistency(
    fx: float, fy: float, alt: float, yaw: float,
) -> None:
    """field→local→field roundtrip in the NEW module must be exact."""
    ref = _make_ready_ref(10.0, 20.0, yaw)
    local = field_to_local_ned(fx, fy, alt, ref)
    back = local_ned_to_field(local.north_m, local.east_m, local.z_down_m, ref)
    assert back.field_x_m == pytest.approx(fx)
    assert back.field_y_m == pytest.approx(fy)
    assert back.altitude_m == pytest.approx(alt)


# ---------------------------------------------------------------------------
# old module bidirectional consistency
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fx", "fy", "yaw"),
    [
        (1.0, 2.0, 0.0),
        (0.0, 10.0, math.pi / 2.0),
        (-3.0, 4.0, math.pi),
        (2.0, -1.0, -math.pi / 4.0),
    ],
)
def test_old_module_field_to_local_roundtrip(
    fx: float, fy: float, yaw: float,
) -> None:
    """RuntimeContextBuilder field_to_local → local_to_field roundtrip."""
    builder = _make_ready_builder(10.0, 20.0, yaw)
    ln, le = builder.field_to_local_xy(fx, fy)
    back_fx, back_fy = builder.local_to_field_xy(ln, le)
    assert back_fx == pytest.approx(fx)
    assert back_fy == pytest.approx(fy)


# ---------------------------------------------------------------------------
# z_down is independent of origin z (old code stored it, new doesn't)
# ---------------------------------------------------------------------------

def test_z_down_independent_of_origin_z() -> None:
    """z_down_m derives solely from altitude_m, not from any stored origin_z.
    The old RuntimeContextBuilder stores field_origin_local_z but the new
    FieldReference does not — and that's correct because the XY transform
    does not use z at all."""
    ref = _make_ready_ref(10.0, 20.0, 0.0)
    # Changing altitude_m alone changes z_down_m
    r1 = field_to_local_ned(0.0, 0.0, altitude_m=3.0, reference=ref)
    r2 = field_to_local_ned(0.0, 0.0, altitude_m=5.0, reference=ref)
    assert r1.z_down_m == -3.0
    assert r2.z_down_m == -5.0
    # XY unchanged
    assert r1.north_m == r2.north_m
    assert r1.east_m == r2.east_m
