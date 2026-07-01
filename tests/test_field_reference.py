from __future__ import annotations

import math

import pytest

from app.field_reference import (
    EARTH_RADIUS_M,
    MIN_GPS_BASELINE_M,
    RECOMMENDED_GPS_BASELINE_M,
    FieldReference,
    FieldReferenceError,
    GpsMarker,
    HeadingSource,
    OriginSource,
)
from app.field_reference_service import FieldReferenceService


# ---------------------------------------------------------------------------
# enum values
# ---------------------------------------------------------------------------

def test_origin_source_values() -> None:
    assert OriginSource.LOCAL_POSITION.value == "local_position"
    assert OriginSource.GPS_MARKER.value == "gps_marker"
    assert OriginSource.MANUAL_GPS_INPUT.value == "manual_gps_input"


def test_heading_source_values() -> None:
    assert HeadingSource.COMPASS_YAW.value == "compass_yaw"
    assert HeadingSource.GPS_TWO_POINT.value == "gps_two_point"
    assert HeadingSource.MANUAL_ANGLE.value == "manual_angle"


# ---------------------------------------------------------------------------
# GpsMarker
# ---------------------------------------------------------------------------

def test_gps_marker_dataclass() -> None:
    m = GpsMarker(lat=30.0, lon=120.0)
    assert m.lat == 30.0
    assert m.lon == 120.0


# ---------------------------------------------------------------------------
# FieldReference — defaults
# ---------------------------------------------------------------------------

def test_default_not_confirmed_not_ready() -> None:
    ref = FieldReference()
    assert ref.is_confirmed is False
    assert ref.is_frozen is False
    assert ref.is_ready() is False


# ---------------------------------------------------------------------------
# readiness: missing pieces
# ---------------------------------------------------------------------------

def test_missing_origin_not_ready() -> None:
    """Confirmed GPS origin without LOCAL_NED origin is not ready."""
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    # GPS origin confirmed but no LOCAL_NED origin → not ready for transform
    assert ref.is_confirmed is True
    assert ref.is_ready() is False


def test_missing_heading_not_ready() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(10.0, 20.0)
    # no heading set → confirm should fail
    with pytest.raises(FieldReferenceError, match="heading_source"):
        ref.confirm()


def test_ready_requires_both_origin_and_heading() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    ref.set_manual_heading(0.5)
    ref.confirm()
    assert ref.is_ready() is True


# ---------------------------------------------------------------------------
# freeze / reset
# ---------------------------------------------------------------------------

def test_freeze_prevents_set_origin() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    ref.freeze()
    assert ref.is_frozen is True

    with pytest.raises(FieldReferenceError, match="frozen"):
        ref.set_origin_local_position(1.0, 2.0)


def test_freeze_prevents_set_heading() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    ref.freeze()

    with pytest.raises(FieldReferenceError, match="frozen"):
        ref.set_manual_heading(1.0)


def test_freeze_requires_confirmed() -> None:
    ref = FieldReference()
    with pytest.raises(FieldReferenceError, match="not confirmed"):
        ref.freeze()


def test_reset_clears_everything() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(10.0, 20.0)
    ref.set_manual_heading(0.5)
    ref.confirm()
    ref.freeze()

    ref.reset()

    assert ref.is_confirmed is False
    assert ref.is_frozen is False
    assert ref.origin_source is None
    assert ref.heading_source is None
    assert ref.origin_local_n_m is None
    assert ref.origin_local_e_m is None
    assert ref.field_heading_yaw_rad is None
    assert ref.confirmed_at_s is None


def test_after_reset_can_set_again() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(1.0, 2.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    ref.freeze()
    ref.reset()

    # should succeed now
    ref.set_origin_local_position(3.0, 4.0)
    ref.set_manual_heading(1.0)
    ref.confirm()
    assert ref.is_ready() is True


# ---------------------------------------------------------------------------
# yaw normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, 0.0),
        (math.pi, math.pi),
        (-math.pi, math.pi),          # -pi normalizes to pi
        (3 * math.pi, math.pi),       # 3pi → pi
        (-3 * math.pi, math.pi),      # -3pi → pi
        (math.pi + 0.1, -math.pi + 0.1),
        (-math.pi - 0.1, math.pi - 0.1),
        (2 * math.pi, 0.0),
        (-2 * math.pi, 0.0),
        (1.5 * math.pi, -0.5 * math.pi),
    ],
)
def test_yaw_normalized_on_set_manual_heading(raw: float, expected: float) -> None:
    ref = FieldReference()
    ref.set_manual_heading(raw)
    assert ref.field_heading_yaw_rad == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, 0.0),
        (math.pi + 0.5, -math.pi + 0.5),
    ],
)
def test_yaw_normalized_on_set_compass_heading(raw: float, expected: float) -> None:
    ref = FieldReference()
    ref.set_compass_heading(raw)
    assert ref.field_heading_yaw_rad == pytest.approx(expected)


def test_yaw_normalized_during_confirm() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    ref.set_manual_heading(3 * math.pi)  # raw = 3pi
    ref.confirm()
    assert ref.field_heading_yaw_rad == pytest.approx(math.pi)


# ---------------------------------------------------------------------------
# GPS A/B — normal distance (≥ recommended)
# ---------------------------------------------------------------------------

def test_gps_two_point_normal_distance_confirms() -> None:
    """A/B at ~10 m apart should confirm and compute heading."""
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)  # A
    # B ≈ 10 m north of A
    d_lat = 10.0 / EARTH_RADIUS_M  # radians north
    lat_b = 30.0 + math.degrees(d_lat)
    ref.set_forward_marker(lat_b, 120.0)
    ref.set_gps_two_point_heading()

    ref.confirm()
    assert ref.is_confirmed is True
    # bearing from A to B should be north ≈ 0
    assert ref.field_heading_yaw_rad == pytest.approx(0.0, abs=1e-9)


def test_gps_two_point_east_heading() -> None:
    """A→B due east should give heading ≈ pi/2."""
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    # B ≈ 10 m east of A
    d_lon = 10.0 / (EARTH_RADIUS_M * math.cos(math.radians(30.0)))
    lon_b = 120.0 + math.degrees(d_lon)
    ref.set_forward_marker(30.0, lon_b)
    ref.set_gps_two_point_heading()

    ref.confirm()
    assert ref.is_confirmed is True
    assert ref.field_heading_yaw_rad == pytest.approx(math.pi / 2.0, abs=1e-6)


# ---------------------------------------------------------------------------
# GPS A/B — distance < minimum (5 m)
# ---------------------------------------------------------------------------

def test_gps_two_point_too_close_rejects() -> None:
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    # B only ~2 m north → < 5 m minimum
    d_lat = 2.0 / EARTH_RADIUS_M
    lat_b = 30.0 + math.degrees(d_lat)
    ref.set_forward_marker(lat_b, 120.0)
    ref.set_gps_two_point_heading()

    with pytest.raises(FieldReferenceError, match="GPS A/B distance"):
        ref.confirm()


# ---------------------------------------------------------------------------
# GPS A/B — distance between 5 m and 10 m (warning, not hard failure)
# ---------------------------------------------------------------------------

def test_gps_two_point_between_min_and_recommended_warns() -> None:
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    # B ≈ 7 m north → between 5 and 10 m
    d_lat = 7.0 / EARTH_RADIUS_M
    lat_b = 30.0 + math.degrees(d_lat)
    ref.set_forward_marker(lat_b, 120.0)
    ref.set_gps_two_point_heading()

    ok, warnings = ref.confirm_with_warnings()
    assert ok is True
    assert ref.is_confirmed is True
    assert len(warnings) == 1
    assert "recommended" in warnings[0].lower()


# ---------------------------------------------------------------------------
# GPS — single point cannot define heading
# ---------------------------------------------------------------------------

def test_single_gps_point_no_heading() -> None:
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    ref.set_gps_two_point_heading()
    # no forward_marker set → confirm must fail
    with pytest.raises(FieldReferenceError, match="forward_marker"):
        ref.confirm()


# ---------------------------------------------------------------------------
# confirm — missing origin source
# ---------------------------------------------------------------------------

def test_confirm_requires_origin_source() -> None:
    ref = FieldReference()
    ref.set_manual_heading(0.0)
    with pytest.raises(FieldReferenceError, match="origin_source"):
        ref.confirm()


def test_confirm_requires_heading_source() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    with pytest.raises(FieldReferenceError, match="heading_source"):
        ref.confirm()


# ---------------------------------------------------------------------------
# confirm_with_warnings — hard failure
# ---------------------------------------------------------------------------

def test_confirm_with_warnings_returns_false_on_error() -> None:
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    ref.set_gps_two_point_heading()  # heading source set, but no forward marker
    ok, warnings = ref.confirm_with_warnings()
    assert ok is False
    assert len(warnings) == 1
    assert "forward_marker" in warnings[0]


# ---------------------------------------------------------------------------
# FieldReferenceService integration
# ---------------------------------------------------------------------------

def test_service_mark_local_origin_and_confirm() -> None:
    svc = FieldReferenceService()
    assert svc.mark_local_origin(10.0, 20.0)["ok"] is True
    assert svc.set_manual_heading(0.5)["ok"] is True
    result = svc.confirm()
    assert result["ok"] is True

    status = svc.status()
    assert status["is_confirmed"] is True
    assert status["is_ready"] is True
    assert status["origin_source"] == "local_position"
    assert status["heading_source"] == "manual_angle"


def test_service_freeze_and_reset() -> None:
    svc = FieldReferenceService()
    svc.mark_local_origin(0.0, 0.0)
    svc.set_manual_heading(0.0)
    svc.confirm()
    svc.freeze()

    # frozen → set should fail
    result = svc.set_manual_heading(1.0)
    assert result["ok"] is False
    assert "frozen" in result["error"]

    svc.reset()
    # after reset → set succeeds
    assert svc.set_manual_heading(1.0)["ok"] is True


def test_service_gps_flow_with_warnings() -> None:
    svc = FieldReferenceService()
    assert svc.mark_gps_origin(30.0, 120.0)["ok"] is True
    # B ≈ 7 m north → warning expected
    d_lat = 7.0 / EARTH_RADIUS_M
    lat_b = 30.0 + math.degrees(d_lat)
    assert svc.mark_gps_forward(lat_b, 120.0)["ok"] is True

    result = svc.confirm()
    assert result["ok"] is True
    assert len(result["warnings"]) == 1


def test_service_status_reflects_fields() -> None:
    svc = FieldReferenceService()
    svc.mark_local_origin(5.0, 6.0)
    svc.set_compass_heading(1.2)
    svc.confirm()

    s = svc.status()
    assert s["origin_local_n_m"] == 5.0
    assert s["origin_local_e_m"] == 6.0
    assert s["field_heading_yaw_rad"] == pytest.approx(1.2)
    assert s["confirmed_at_s"] is not None


# ---------------------------------------------------------------------------
# frozen guard on GPS setters and confirm (service layer)
# ---------------------------------------------------------------------------

def test_frozen_prevents_mark_gps_origin() -> None:
    svc = FieldReferenceService()
    svc.mark_local_origin(0.0, 0.0)
    svc.set_manual_heading(0.0)
    svc.confirm()
    svc.freeze()

    result = svc.mark_gps_origin(30.0, 120.0)
    assert result["ok"] is False
    assert "frozen" in result["error"]


def test_frozen_prevents_mark_gps_forward() -> None:
    svc = FieldReferenceService()
    svc.mark_local_origin(0.0, 0.0)
    svc.set_manual_heading(0.0)
    svc.confirm()
    svc.freeze()

    result = svc.mark_gps_forward(30.001, 120.0)
    assert result["ok"] is False
    assert "frozen" in result["error"]


def test_frozen_prevents_set_compass_heading_via_service() -> None:
    svc = FieldReferenceService()
    svc.mark_local_origin(0.0, 0.0)
    svc.set_manual_heading(0.0)
    svc.confirm()
    svc.freeze()

    result = svc.set_compass_heading(1.0)
    assert result["ok"] is False
    assert "frozen" in result["error"]


def test_frozen_prevents_set_manual_heading_via_service() -> None:
    svc = FieldReferenceService()
    svc.mark_local_origin(0.0, 0.0)
    svc.set_manual_heading(0.0)
    svc.confirm()
    svc.freeze()

    result = svc.set_manual_heading(1.5)
    assert result["ok"] is False
    assert "frozen" in result["error"]


def test_frozen_prevents_confirm() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    ref.freeze()

    # confirm is guarded by _guard_not_frozen
    with pytest.raises(FieldReferenceError, match="frozen"):
        ref.confirm()


# ---------------------------------------------------------------------------
# reset clears GPS fields
# ---------------------------------------------------------------------------

def test_reset_clears_gps_origin_fields() -> None:
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    ref.set_manual_heading(0.0)
    ref.confirm()

    assert ref.origin_lat == 30.0
    assert ref.origin_lon == 120.0

    ref.reset()
    assert ref.origin_lat is None
    assert ref.origin_lon is None


def test_reset_clears_gps_forward_fields() -> None:
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    ref.set_forward_marker(30.001, 120.0)
    ref.set_gps_two_point_heading()
    ref.confirm()

    assert ref.forward_marker_lat is not None
    assert ref.forward_marker_lon is not None

    ref.reset()
    assert ref.forward_marker_lat is None
    assert ref.forward_marker_lon is None


def test_reset_clears_frozen_flag() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    ref.freeze()
    assert ref.is_frozen is True

    ref.reset()
    assert ref.is_frozen is False


def test_reset_then_reconfirm_new_gps_ab() -> None:
    """After reset, a completely new GPS A/B pair can be set and confirmed."""
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    ref.set_forward_marker(30.001, 120.0)
    ref.set_gps_two_point_heading()
    ref.confirm()
    ref.reset()

    # new GPS origin + forward marker
    ref.set_origin_gps(31.0, 121.0)
    d_lat = 15.0 / EARTH_RADIUS_M
    lat_b = 31.0 + math.degrees(d_lat)
    ref.set_forward_marker(lat_b, 121.0)
    ref.set_gps_two_point_heading()
    ref.confirm()

    assert ref.is_confirmed is True
    assert ref.origin_lat == 31.0
    assert ref.origin_lon == 121.0
    assert ref.field_heading_yaw_rad == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# GPS origin + LOCAL_NED snapshot readiness
# ---------------------------------------------------------------------------

def test_gps_origin_with_local_snapshot_is_ready() -> None:
    """GPS origin with a LOCAL_NED snapshot should be ready for transforms."""
    ref = FieldReference()
    ref.set_origin_gps_with_local_snapshot(30.0, 120.0, 10.0, 20.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    assert ref.is_ready() is True


def test_gps_origin_without_local_snapshot_not_ready() -> None:
    """GPS origin without LOCAL_NED snapshot should NOT be ready."""
    ref = FieldReference()
    ref.set_origin_gps(30.0, 120.0)
    ref.set_manual_heading(0.0)
    ref.confirm()
    assert ref.is_confirmed is True
    assert ref.is_ready() is False


def test_service_gps_origin_with_local_snapshot_is_ready() -> None:
    """mark_gps_origin with local_n_m/local_e_m should produce a ready ref."""
    svc = FieldReferenceService()
    assert svc.mark_gps_origin(30.0, 120.0, local_n_m=10.0, local_e_m=20.0)["ok"] is True
    assert svc.set_manual_heading(0.0)["ok"] is True
    result = svc.confirm()
    assert result["ok"] is True

    s = svc.status()
    assert s["is_ready"] is True
    assert s["origin_source"] == "gps_marker"
    assert s["origin_lat"] == 30.0
    assert s["origin_local_n_m"] == 10.0
    assert s["origin_local_e_m"] == 20.0


# ---------------------------------------------------------------------------
# confirm → freeze → reset lifecycle (end-to-end)
# ---------------------------------------------------------------------------

def test_lifecycle_confirm_freeze_reset() -> None:
    ref = FieldReference()
    ref.set_origin_local_position(0.0, 0.0)
    ref.set_manual_heading(0.0)

    ref.confirm()
    assert ref.is_confirmed is True
    assert ref.confirmed_at_s is not None

    ref.freeze()
    assert ref.is_frozen is True

    ref.reset()
    assert ref.is_confirmed is False
    assert ref.is_frozen is False
    assert ref.origin_source is None


# ---------------------------------------------------------------------------
# Phase 4C-1: service handler parity tests
# ---------------------------------------------------------------------------

def test_service_mark_gps_origin_without_snapshot_not_ready() -> None:
    """mark_gps_origin without local_n_m/local_e_m leaves is_ready() False."""
    svc = FieldReferenceService()
    assert svc.mark_gps_origin(30.0, 120.0)["ok"] is True
    assert svc.set_manual_heading(0.0)["ok"] is True
    assert svc.confirm()["ok"] is True
    s = svc.status()
    assert s["is_ready"] is False
    assert s["origin_lat"] == 30.0
    assert s["origin_local_n_m"] is None


def test_service_set_manual_heading_degrees() -> None:
    """set_manual_heading accepts radians; confirm it handles 90° correctly."""
    svc = FieldReferenceService()
    svc.mark_local_origin(0.0, 0.0)
    svc.set_manual_heading(math.radians(90.0))
    assert svc.confirm()["ok"] is True
    s = svc.status()
    assert s["field_heading_yaw_rad"] == pytest.approx(math.pi / 2.0)


def test_service_freeze_unconfirmed_fails() -> None:
    """freeze before confirm returns error."""
    svc = FieldReferenceService()
    svc.mark_local_origin(0.0, 0.0)
    svc.set_manual_heading(0.0)
    result = svc.freeze()
    assert result["ok"] is False
    assert "not confirmed" in result.get("error", "")


def test_old_field_heading_api_still_works() -> None:
    """Existing RuntimeContextBuilder.confirm_field_heading() is unchanged."""
    from app.runtime_context import RuntimeContextBuilder
    builder = RuntimeContextBuilder()
    drone = {
        "local_position_valid": True,
        "local_x": 10.0, "local_y": 20.0, "local_z": -1.0,
    }
    ok = builder.confirm_field_heading(yaw_rad=0.5, drone=drone, source="manual")
    assert ok is True
    assert builder.field_heading_confirmed is True
    assert builder.field_origin_confirmed is True
