"""Tests for FieldProfile backend — bind, apply, sync, status (centerline-only)."""
from __future__ import annotations

import os

import pytest

from app.field_profile import (
    AnchorPoint,
    BindingPolicy,
    CenterlinePoint,
    FieldGeometry,
    FieldProfile,
    GpsQualityThresholds,
)
from app.field_profile_service import FieldProfileService
from app.field_reference_controller import FieldReferenceController
from app.field_reference_service import FieldReferenceService
from app.runtime_context import RuntimeContextBuilder


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_profile(profile_id="test_backend"):
    """Build a minimal valid centerline profile with 4 north-aligned points."""
    cl = [
        CenterlinePoint("CL_1", 34.000075, 108.0),
        CenterlinePoint("CL_2", 34.000150, 108.0),
        CenterlinePoint("CL_3", 34.000225, 108.0),
        CenterlinePoint("CL_4", 34.000300, 108.0),
    ]
    return FieldProfile(
        schema_version=2,
        profile_id=profile_id,
        name="Test Backend Profile",
        coordinate_convention={
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        },
        anchor=AnchorPoint("a", 34.0, 108.0),
        centerline_points=cl,
        gps_quality=GpsQualityThresholds(),
        field_geometry=FieldGeometry(),
        binding_policy=BindingPolicy(),
    )


def _drone_snapshot(**overrides):
    """Build a drone snapshot dict with sensible defaults for bind-current."""
    data = {
        "global_position_valid": True,
        "lat": 34.0,
        "lon": 108.0,
        "local_position_valid": True,
        "local_x": 10.0,
        "local_y": 20.0,
        "local_z": -1.0,
        "gps_fix_type": 3,
        "satellites_visible": 12,
        "gps_eph": 1.0,
        "gps_epv": 1.0,
        "attitude_valid": True,
        "yaw": 0.3,
    }
    data.update(overrides)
    return data


def _make_services_and_bind(profile=None, drone=None):
    """Create services, bind a centerline profile, apply, and sync.

    Returns (svc, builder, bind_result, controller).
    """
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    if profile is None:
        profile = _make_profile()
    if drone is None:
        drone = _drone_snapshot()

    controller = FieldReferenceController(
        field_reference_service=svc,
        runtime_context_builder=builder,
        get_drone_snapshot=lambda: drone,
    )

    # We bypass the controller's own drone-snapshot logic and test the
    # services directly for the core computation, then use the controller
    # for the sync/status path.
    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        current_yaw_rad=drone.get("yaw"),
        gps_fix_type=drone.get("gps_fix_type", 0),
        satellites_visible=drone.get("satellites_visible", 0),
        gps_eph=drone.get("gps_eph"),
        gps_epv=drone.get("gps_epv"),
        timestamp=1000.0,
    )
    return svc, builder, br, controller


# ---------------------------------------------------------------------------
# profile list / load / validate
# ---------------------------------------------------------------------------


def test_list_profiles_includes_example():
    import os
    profile_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config", "field_profiles")
    profiles = FieldProfileService.list_profiles(profile_dir)
    # example_competition_lane.json should be present
    assert any("example_competition_lane" in p for p in profiles)


def test_load_profile_valid():
    import os
    profile_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config", "field_profiles")
    profile = FieldProfileService.load_profile("example_competition_lane", profile_dir=profile_dir)
    assert profile.profile_id == "example_competition_lane"
    assert profile.schema_version == 2
    assert len(profile.centerline_points) >= 4


def test_load_profile_missing():
    import os
    profile_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config", "field_profiles")
    with pytest.raises(FileNotFoundError):
        FieldProfileService.load_profile("nonexistent_profile_xyz", profile_dir=profile_dir)


def test_load_profile_path_traversal_rejected():
    import os
    profile_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config", "field_profiles")
    with pytest.raises((FileNotFoundError, ValueError)):
        FieldProfileService.load_profile("../etc/passwd", profile_dir=profile_dir)


def test_validate_profile_ok():
    profile = _make_profile()
    diag = FieldProfileService.validate_profile(profile)
    assert diag.ok is True


# ---------------------------------------------------------------------------
# bind-current success
# ---------------------------------------------------------------------------


def test_bind_current_success():
    svc, builder, br, ctrl = _make_services_and_bind()
    assert br.ok, f"bind failed: {br.errors}"
    assert br.origin_local_n_m == pytest.approx(10.0)
    assert br.origin_local_e_m == pytest.approx(20.0)
    assert br.origin_local_z_m == pytest.approx(-1.0)
    assert br.field_heading_yaw_rad is not None
    assert br.current_start_error_m is not None
    assert br.baseline_m is not None


def test_bind_current_syncs_runtime_context():
    svc, builder, br, ctrl = _make_services_and_bind()
    assert br.ok

    applied = svc.apply_profile_binding(
        bind_result=br,
        profile_id="test_backend",
        profile_name="Test",
        anchor_lat=34.0,
        anchor_lon=108.0,
        timestamp=1000.0,
    )
    assert applied["ok"]

    ref = svc.reference
    ok = builder.confirm_field_reference(
        field_heading_yaw_rad=ref.field_heading_yaw_rad,
        origin_local_x=ref.origin_local_n_m,
        origin_local_y=ref.origin_local_e_m,
        origin_local_z=ref.origin_local_z_m,
        source="test",
        timestamp=1000.0,
    )
    assert ok
    assert builder.field_heading_confirmed is True
    assert builder.field_origin_confirmed is True
    assert FieldReferenceController._is_field_reference_synced(svc.status(), builder) is True


def test_legacy_bind_sync_failure_restores_complete_runtime_gps_snapshot(
    monkeypatch,
):
    profile = _make_profile()
    drone = _drone_snapshot()
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    builder.field_heading_yaw_rad = 0.25
    builder.field_heading_time = 10.0
    builder.field_heading_confirmed = True
    builder.field_heading_source = "runtime_forward_marker"
    builder.field_origin_lat = 34.0
    builder.field_origin_lon = 108.0
    builder.field_origin_time = 10.0
    builder.field_origin_confirmed = False
    builder.field_origin_gps_confirmed = True
    builder.field_reference_mode = "runtime_origin_forward_marker"
    builder.field_forward_marker_lat = 34.001
    builder.field_forward_marker_lon = 108.0
    builder.field_baseline_m = 111.0
    builder.field_gps_sample_count = 20
    builder.field_gps_rejected_sample_count = 2
    builder.field_gps_duplicate_sample_count = 3
    builder.field_gps_sample_duration_s = 5.0
    builder.field_gps_horizontal_spread_m = 0.3
    builder.field_gps_fix_type = 3
    builder.field_gps_satellites = 12
    builder.field_gps_eph = 1.0
    builder.field_gps_epv = 1.5
    builder.field_runtime_profile_id = "runtime-before-legacy"
    before = builder.snapshot_field_reference_state()
    controller = FieldReferenceController(svc, builder, lambda: drone)
    monkeypatch.setattr(
        controller, "_load_profile", lambda profile_id: (profile, [])
    )

    def corrupt_then_fail(**kwargs):
        builder.clear_field_heading()
        return False

    monkeypatch.setattr(builder, "confirm_field_reference", corrupt_then_fail)
    result = controller.bind_profile_current(profile.profile_id)
    assert result["ok"] is False
    assert builder.snapshot_field_reference_state() == before
    assert svc.reference.is_confirmed is False


# ---------------------------------------------------------------------------
# origin_local is independent of current GPS
# ---------------------------------------------------------------------------


def test_origin_local_independent_of_gps():
    profile = _make_profile()
    drone = _drone_snapshot(lat=34.000018, lon=108.0)  # ~2m off anchor
    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok
    # origin_local must equal input LOCAL_NED, not be GPS-derived
    assert br.origin_local_n_m == pytest.approx(10.0)
    assert br.origin_local_e_m == pytest.approx(20.0)
    # start_error should be ~2m
    assert br.current_start_error_m == pytest.approx(2.0, abs=0.3)


# ---------------------------------------------------------------------------
# start_error thresholds
# ---------------------------------------------------------------------------


def test_start_error_warning():
    """start_error between warn and max → warning but ok=True."""
    profile = _make_profile()
    profile.binding_policy = BindingPolicy(warn_start_error_m=1.0, max_start_error_m=3.0)
    drone = _drone_snapshot(lat=34.000018, lon=108.0)  # ~2m off

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is True
    assert len(br.warnings) >= 1
    assert any("start_error" in w.lower() or "GPS" in w for w in br.warnings)


def test_start_error_rejected():
    """start_error > max → ok=False."""
    profile = _make_profile()
    profile.binding_policy = BindingPolicy(max_start_error_m=3.0)
    drone = _drone_snapshot(lat=34.000045, lon=108.0)  # ~5m off

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is False
    assert any("start_error" in e.lower() or "GPS" in e for e in br.errors)


# ---------------------------------------------------------------------------
# centerline residual thresholds
# ---------------------------------------------------------------------------


def test_centerline_residual_rejected():
    """Outlier point exceeding max residual → ok=False."""
    profile = _make_profile()
    profile.binding_policy = BindingPolicy(max_centerline_residual_m=2.5)
    # Add an outlier centerline point 10m off-axis
    profile.centerline_points.append(
        CenterlinePoint("outlier", 34.000150, 108.000100)  # ~10m east off the line
    )

    drone = _drone_snapshot()
    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is False
    assert any("residual" in e.lower() for e in br.errors)


def test_centerline_residual_warning():
    """Residual between warn and max → warning but ok=True."""
    profile = _make_profile()
    profile.binding_policy = BindingPolicy(
        warn_centerline_residual_m=0.5, max_centerline_residual_m=10.0
    )
    # Add a point ~1m off-axis
    profile.centerline_points.append(
        CenterlinePoint("slightly_off", 34.000150, 108.000010)  # ~1m off
    )

    drone = _drone_snapshot()
    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is True
    assert any("residual" in w.lower() for w in br.warnings)


# ---------------------------------------------------------------------------
# yaw doesn't affect heading
# ---------------------------------------------------------------------------


def test_yaw_does_not_affect_heading():
    profile = _make_profile()
    drone1 = _drone_snapshot(yaw=0.0)
    drone2 = _drone_snapshot(yaw=3.0)

    br1 = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone1["lat"],
        current_lon=drone1["lon"],
        current_local_n_m=drone1["local_x"],
        current_local_e_m=drone1["local_y"],
        current_local_z_m=drone1["local_z"],
        current_yaw_rad=drone1["yaw"],
        gps_fix_type=drone1["gps_fix_type"],
        satellites_visible=drone1["satellites_visible"],
        gps_eph=drone1["gps_eph"],
        gps_epv=drone1["gps_epv"],
        timestamp=1000.0,
    )
    br2 = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone2["lat"],
        current_lon=drone2["lon"],
        current_local_n_m=drone2["local_x"],
        current_local_e_m=drone2["local_y"],
        current_local_z_m=drone2["local_z"],
        current_yaw_rad=drone2["yaw"],
        gps_fix_type=drone2["gps_fix_type"],
        satellites_visible=drone2["satellites_visible"],
        gps_eph=drone2["gps_eph"],
        gps_epv=drone2["gps_epv"],
        timestamp=1000.0,
    )

    # heading must be identical (centerline-derived)
    assert br1.field_heading_yaw_rad == pytest.approx(br2.field_heading_yaw_rad)
    # yaw_error must differ significantly
    assert br1.yaw_error_deg is not None
    assert br2.yaw_error_deg is not None
    assert abs(br1.yaw_error_deg - br2.yaw_error_deg) > 1.0


# ---------------------------------------------------------------------------
# GPS quality failures
# ---------------------------------------------------------------------------


def test_bind_fails_low_fix_type():
    profile = _make_profile()
    profile.gps_quality = GpsQualityThresholds(min_fix_type=3)
    drone = _drone_snapshot(gps_fix_type=2)

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is False
    assert any("fix_type" in e.lower() for e in br.errors)


def test_bind_fails_low_satellites():
    profile = _make_profile()
    profile.gps_quality = GpsQualityThresholds(min_satellites=10)
    drone = _drone_snapshot(satellites_visible=5)

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is False
    assert any("satellites" in e.lower() for e in br.errors)


def test_bind_fails_bad_eph():
    profile = _make_profile()
    profile.gps_quality = GpsQualityThresholds(max_eph=2.0)
    drone = _drone_snapshot(gps_eph=5.0)

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is False
    assert any("eph" in e.lower() for e in br.errors)


# ---------------------------------------------------------------------------
# missing telemetry
# ---------------------------------------------------------------------------


def test_bind_fails_no_gps():
    profile = _make_profile()
    drone = _drone_snapshot(global_position_valid=False, lat=0, lon=0)

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=None,
        current_lon=None,
        current_local_n_m=drone["local_x"],
        current_local_e_m=drone["local_y"],
        current_local_z_m=drone["local_z"],
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is False
    assert any("current_lat" in e.lower() for e in br.errors)


def test_bind_fails_no_local_position():
    profile = _make_profile()
    drone = _drone_snapshot(local_x=None, local_y=None, local_z=None)

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=drone["lat"],
        current_lon=drone["lon"],
        current_local_n_m=None,
        current_local_e_m=None,
        current_local_z_m=None,
        gps_fix_type=drone["gps_fix_type"],
        satellites_visible=drone["satellites_visible"],
        gps_eph=drone["gps_eph"],
        gps_epv=drone["gps_epv"],
        timestamp=1000.0,
    )
    assert br.ok is False
    assert any("current_local_n_m" in e.lower() for e in br.errors)


# ---------------------------------------------------------------------------
# frozen guard
# ---------------------------------------------------------------------------


def test_apply_frozen_rejects():
    svc, builder, br, ctrl = _make_services_and_bind()
    assert br.ok

    svc.apply_profile_binding(
        bind_result=br,
        profile_id="test_backend",
        profile_name="Test",
        anchor_lat=34.0,
        anchor_lon=108.0,
        timestamp=1000.0,
    )
    svc.freeze()

    # Second apply should be rejected
    result = svc.apply_profile_binding(
        bind_result=br,
        profile_id="test_backend2",
        profile_name="Test2",
        anchor_lat=34.0,
        anchor_lon=108.0,
        timestamp=2000.0,
    )
    assert result["ok"] is False
    assert "frozen" in str(result.get("error", "")).lower()


# ---------------------------------------------------------------------------
# status includes profile info
# ---------------------------------------------------------------------------


def test_status_includes_profile_after_apply():
    svc, builder, br, ctrl = _make_services_and_bind()
    assert br.ok

    svc.apply_profile_binding(
        bind_result=br,
        profile_id="test_backend",
        profile_name="Test Backend",
        anchor_lat=34.0,
        anchor_lon=108.0,
        timestamp=1000.0,
    )

    status = svc.status()
    assert status["is_confirmed"] is True
    assert status["profile_id"] == "test_backend"
    assert status["profile_name"] == "Test Backend"
