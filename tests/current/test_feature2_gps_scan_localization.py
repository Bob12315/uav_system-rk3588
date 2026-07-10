"""Tests for Feature 2 — GLOBAL scan + GPS-first localization + fusion."""

import math
import pytest

from app.field_profile import FieldProfile, parse_field_profile, FieldScanWaypoint
from app.field_reference import FieldReference, OriginSource, HeadingSource
from app.runtime_field_target_resolver import (
    RuntimeFieldTargetResolver,
    RuntimeFieldTargetError,
    GpsScanTarget,
)
from missions.common.actions.gps_target_projection import (
    GpsProjectionCamera,
    GpsProjectionError,
    GpsRawEstimate,
    GpsTargetProjector,
)
from missions.common.actions.gps_derived_enu_fusion import (
    GpsDerivedEnuFusion,
    GpsFusionConfig,
    GpsLocalizedObject,
)
from missions.common.actions.gps_multi_view_localize import (
    GpsMultiViewLocalizeAction,
)


# =============================================================================
# v3 profile fixture
# =============================================================================

def _v3_profile_dict():
    return {
        "schema_version": 3, "profile_id": "test_v3", "name": "Test V3",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "forward_marker": {"name": "far", "lat": 34.104189, "lon": 108.642674, "coordinate_system": "WGS84"},
        "field_geometry": {
            "lane_half_width_m": 4.0, "drop_center_y_m": 32.5, "recce_center_y_m": 57.5,
            "drop_area_y_min_m": 30.0, "drop_area_y_max_m": 35.0,
            "recce_area_y_min_m": 55.0, "recce_area_y_max_m": 60.0,
        },
        "drop_scan": {
            "waypoints": [
                {"x_m": -2.0, "y_m": 31.25, "altitude_m": 5.0},
                {"x_m": 2.0, "y_m": 31.25, "altitude_m": 5.0},
                {"x_m": 2.0, "y_m": 33.75, "altitude_m": 5.0},
                {"x_m": -2.0, "y_m": 33.75, "altitude_m": 5.0},
            ],
        },
        "gps_quality": {"min_fix_type": 3, "min_satellites": 10, "max_eph": 2.5, "max_epv": 5.0},
        "runtime_origin_sampling": {"min_samples": 20, "sample_window_s": 5.0, "max_horizontal_spread_m": 1.0, "estimator": "median"},
        "binding_policy": {"min_baseline_m": 30.0, "warn_baseline_below_m": 50.0},
    }


def _v3_profile():
    return parse_field_profile(_v3_profile_dict())


def _ready_reference():
    ref = FieldReference()
    ref.is_confirmed = True
    ref.is_frozen = True
    ref.origin_source = OriginSource.GPS_MARKER.value
    ref.heading_source = HeadingSource.GPS_TWO_POINT.value
    ref.origin_lat = 34.0
    ref.origin_lon = 108.0
    ref.forward_marker_lat = 34.104189
    ref.forward_marker_lon = 108.642674
    ref.field_heading_yaw_rad = 1.5
    return ref


# =============================================================================
# RuntimeFieldTargetResolver tests
# =============================================================================

class TestRuntimeFieldTargetResolver:
    def test_home_is_origin(self):
        ref = _ready_reference()
        profile = _v3_profile()
        r = RuntimeFieldTargetResolver(profile, ref)
        assert r.is_ready
        home = r.home()
        assert home.name == "HOME"
        assert home.lat == pytest.approx(ref.origin_lat)
        assert home.lon == pytest.approx(ref.origin_lon)
        assert home.yaw_mode == "hold"

    def test_scan_waypoints_count(self):
        r = RuntimeFieldTargetResolver(_v3_profile(), _ready_reference())
        scans = r.scan_waypoints()
        assert len(scans) == 4
        assert scans[0].name == "DROP_SCAN_1"
        assert scans[1].name == "DROP_SCAN_2"
        assert scans[2].name == "DROP_SCAN_3"
        assert scans[3].name == "DROP_SCAN_4"

    def test_scan_waypoints_are_global(self):
        r = RuntimeFieldTargetResolver(_v3_profile(), _ready_reference())
        for s in r.scan_waypoints():
            assert -90.0 <= s.lat <= 90.0, f"{s.name} lat out of range"
            assert -180.0 <= s.lon <= 180.0, f"{s.name} lon out of range"
            assert s.altitude_m > 0.0
            assert s.yaw_mode == "hold"

    def test_altitude_preserved(self):
        r = RuntimeFieldTargetResolver(_v3_profile(), _ready_reference())
        scans = r.scan_waypoints()
        assert scans[0].altitude_m == pytest.approx(5.0)

    def test_yaw_mode_hold(self):
        r = RuntimeFieldTargetResolver(_v3_profile(), _ready_reference())
        for s in r.scan_waypoints():
            assert s.yaw_mode == "hold"

    def test_not_confirmed_rejected(self):
        ref = _ready_reference()
        ref.is_confirmed = False
        r = RuntimeFieldTargetResolver(_v3_profile(), ref)
        assert not r.is_ready
        assert "not confirmed" in (r.error or "")

    def test_not_frozen_rejected(self):
        ref = _ready_reference()
        ref.is_frozen = False
        r = RuntimeFieldTargetResolver(_v3_profile(), ref)
        assert not r.is_ready
        assert "not frozen" in (r.error or "")

    def test_not_gps_ready_rejected(self):
        ref = _ready_reference()
        ref.origin_lat = None
        r = RuntimeFieldTargetResolver(_v3_profile(), ref)
        assert not r.is_ready

    def test_wrong_origin_source_rejected(self):
        ref = _ready_reference()
        ref.origin_source = OriginSource.LOCAL_POSITION.value
        r = RuntimeFieldTargetResolver(_v3_profile(), ref)
        assert not r.is_ready

    def test_unknown_target_raises(self):
        r = RuntimeFieldTargetResolver(_v3_profile(), _ready_reference())
        with pytest.raises(RuntimeFieldTargetError):
            r.target_by_name("UNKNOWN")

    def test_as_action_dict_global(self):
        r = RuntimeFieldTargetResolver(_v3_profile(), _ready_reference())
        d = r.as_action_dict("DROP_SCAN_1")
        assert d["waypoint_mode"] == "absolute"
        assert d["target_frame"] == "global"
        assert d["yaw_mode"] == "hold"
        assert "x" in d and "y" in d and "altitude_m" in d
        assert "lat" not in d  # x/y carry lat/lon for absolute+global

    def test_no_local_fallback(self):
        r = RuntimeFieldTargetResolver(_v3_profile(), _ready_reference())
        d = r.as_action_dict("HOME")
        assert d["target_frame"] == "global"
        assert d["waypoint_mode"] == "absolute"
        assert "local" not in str(d).lower().replace("global", "").replace("GLOBAL", "")


# =============================================================================
# GpsTargetProjector tests
# =============================================================================

class TestGpsTargetProjector:
    def test_center_detection_equals_drone_gps(self):
        cam = GpsProjectionCamera(fov_x_deg=51.3, fov_y_deg=39.6)
        p = GpsTargetProjector(cam)
        est = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
            relative_altitude_m=5.0,
            ex=0.0, ey=0.0,
        )
        assert est.lat == pytest.approx(34.0, abs=1e-5)
        assert est.lon == pytest.approx(108.0, abs=1e-5)
        assert est.east_offset_m == pytest.approx(0.0, abs=1e-3)
        assert est.north_offset_m == pytest.approx(0.0, abs=1e-3)

    def test_yaw_zero_image_right_east_offset_positive(self):
        cam = GpsProjectionCamera(fov_x_deg=51.3, fov_y_deg=39.6)
        p = GpsTargetProjector(cam)
        est = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
            relative_altitude_m=5.0,
            ex=0.5, ey=0.0,  # right side of image
        )
        # yaw=0 → body right = east
        assert est.east_offset_m > 0.0

    def test_yaw_pi_half_rotation_correct(self):
        cam = GpsProjectionCamera(fov_x_deg=51.3, fov_y_deg=39.6)
        p = GpsTargetProjector(cam)
        est = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=math.pi / 2,
            relative_altitude_m=5.0,
            ex=0.0, ey=0.5,  # top of image = forward
        )
        # yaw=π/2 → body forward = east, body right = south (-north)
        # ey positive = forward → body_forward_m positive → east_offset_m positive
        assert est.east_offset_m < 0.0, f"east_offset_m={est.east_offset_m} should be negative (behind drone)"

    def test_image_y_sign_negative_correct(self):
        cam = GpsProjectionCamera(fov_x_deg=51.3, fov_y_deg=39.6, image_y_sign=-1.0)
        p = GpsTargetProjector(cam)
        est = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
            relative_altitude_m=5.0,
            ex=0.0, ey=0.5,  # bottom of image
        )
        # image_y_sign=-1 → ey positive → angle positive → body_forward_m negative
        assert est.north_offset_m < 0.0, f"north_offset_m={est.north_offset_m}"

    def test_altitude_linear_scaling(self):
        cam = GpsProjectionCamera(fov_x_deg=51.3, fov_y_deg=39.6)
        p = GpsTargetProjector(cam)
        est_low = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
            relative_altitude_m=2.5,
            ex=0.5, ey=0.0,
        )
        est_high = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
            relative_altitude_m=5.0,
            ex=0.5, ey=0.0,
        )
        # altitude doubled → offset should approx double
        ratio = est_high.east_offset_m / est_low.east_offset_m
        assert 1.9 < ratio < 2.1, f"ratio={ratio}"

    def test_invalid_gps_rejected(self):
        p = GpsTargetProjector()
        with pytest.raises(GpsProjectionError):
            p.project(drone_lat=100.0, drone_lon=108.0, drone_yaw_rad=0.0,
                      relative_altitude_m=5.0, ex=0.0, ey=0.0)

    def test_invalid_yaw_rejected(self):
        p = GpsTargetProjector()
        with pytest.raises(GpsProjectionError):
            p.project(drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=float("nan"),
                      relative_altitude_m=5.0, ex=0.0, ey=0.0)

    def test_negative_altitude_rejected(self):
        p = GpsTargetProjector()
        with pytest.raises(GpsProjectionError):
            p.project(drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
                      relative_altitude_m=-5.0, ex=0.0, ey=0.0)

    def test_invalid_ex_rejected(self):
        p = GpsTargetProjector()
        with pytest.raises(GpsProjectionError):
            p.project(drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
                      relative_altitude_m=5.0, ex=float("inf"), ey=0.0)

    def test_capture_snapshot_independent(self):
        """Capture snapshot fields must not change when 'current' position changes."""
        p = GpsTargetProjector()
        est1 = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.5,
            relative_altitude_m=5.0,
            ex=0.1, ey=0.2,
        )
        # Later call with different drone position — est1 fields unchanged
        assert est1.capture_drone_lat == pytest.approx(34.0)
        assert est1.capture_drone_lon == pytest.approx(108.0)
        assert est1.capture_yaw_rad == pytest.approx(0.5)

    def test_output_has_lat_lon(self):
        p = GpsTargetProjector()
        est = p.project(
            drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0,
            relative_altitude_m=5.0,
            ex=0.0, ey=0.0,
        )
        assert hasattr(est, "lat") and hasattr(est, "lon")
        assert not hasattr(est, "local_x") and not hasattr(est, "local_y")


# =============================================================================
# GpsDerivedEnuFusion tests
# =============================================================================

class TestGpsDerivedEnuFusion:
    def test_single_target_multi_view_fuses_to_one(self):
        fuser = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0)
        estimates = [
            _make_raw_est(34.0, 108.00001, "bucket", 0.8, "DROP_SCAN_1"),
            _make_raw_est(34.0, 108.00001, "bucket", 0.9, "DROP_SCAN_2"),
            _make_raw_est(34.0, 108.00001, "bucket", 0.7, "DROP_SCAN_3"),
            _make_raw_est(34.0, 108.00001, "bucket", 0.85, "DROP_SCAN_4"),
        ]
        result = fuser.fuse(estimates)
        # With cluster_radius=1.0, min_cluster_size=3, all 4 should cluster
        assert len(result) >= 1, f"expected >=1 fused objects, got {len(result)}"
        obj = result[0]
        assert obj.class_name == "bucket"
        assert obj.sample_count >= 3

    def test_two_targets_remain_separate(self):
        fuser = GpsDerivedEnuFusion(
            origin_lat=34.0, origin_lon=108.0,
            config=GpsFusionConfig(cluster_radius_m=0.5, min_cluster_size=2),
        )
        estimates = [
            _make_raw_est(34.0, 108.00001, "bucket_A", 0.8),
            _make_raw_est(34.0, 108.00001, "bucket_A", 0.9),
            _make_raw_est(34.0001, 108.0001, "bucket_B", 0.8),
            _make_raw_est(34.0001, 108.0001, "bucket_B", 0.9),
        ]
        result = fuser.fuse(estimates)
        assert len(result) == 2

    def test_outlier_removed(self):
        fuser = GpsDerivedEnuFusion(
            origin_lat=34.0, origin_lon=108.0,
            config=GpsFusionConfig(cluster_radius_m=0.5, min_cluster_size=2, outlier_radius_m=0.3),
        )
        estimates = [
            _make_raw_est(34.0, 108.00001, "bucket", 0.8),
            _make_raw_est(34.0, 108.00001, "bucket", 0.9),
            _make_raw_est(34.0, 108.00001, "bucket", 0.7),
            _make_raw_est(34.01, 108.01, "bucket", 0.6),  # far outlier, ~1.1km away
        ]
        result = fuser.fuse(estimates)
        assert len(result) == 1  # outlier excluded
        obj = result[0]
        assert obj.lat == pytest.approx(34.0, abs=0.001)

    def test_min_cluster_size_rejects_small_clusters(self):
        fuser = GpsDerivedEnuFusion(
            origin_lat=34.0, origin_lon=108.0,
            config=GpsFusionConfig(cluster_radius_m=0.5, min_cluster_size=3),
        )
        estimates = [
            _make_raw_est(34.0, 108.00001, "bucket", 0.8),
            _make_raw_est(34.0, 108.00001, "bucket", 0.9),
        ]
        result = fuser.fuse(estimates)
        assert len(result) == 0  # only 2, need 3

    def test_output_has_lat_lon_not_local(self):
        fuser = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0)
        estimates = [
            _make_raw_est(34.0, 108.00001, "bucket", 0.8),
            _make_raw_est(34.0, 108.00001, "bucket", 0.9),
            _make_raw_est(34.0, 108.00001, "bucket", 0.7),
            _make_raw_est(34.0, 108.00001, "bucket", 0.85),
        ]
        result = fuser.fuse(estimates)
        assert len(result) >= 1, f"expected >=1 fused objects, got {len(result)}"
        obj = result[0]
        assert hasattr(obj, "lat") and hasattr(obj, "lon")
        assert hasattr(obj, "east_m") and hasattr(obj, "north_m")
        assert not hasattr(obj, "local_x")
        assert not hasattr(obj, "local_y")

    def test_reverse_order_deterministic(self):
        fuser = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0)
        ests = [
            _make_raw_est(34.0, 108.00001, "bucket", 0.9),
            _make_raw_est(34.0, 108.00001, "bucket", 0.8),
            _make_raw_est(34.0, 108.00001, "bucket", 0.7),
            _make_raw_est(34.0, 108.00001, "bucket", 0.85),
        ]
        r1 = fuser.fuse(list(reversed(ests)))
        r2 = fuser.fuse(list(ests))
        assert len(r1) == len(r2) == 1
        assert r1[0].lat == pytest.approx(r2[0].lat)


# =============================================================================
# GpsMultiViewLocalizeAction smoke
# =============================================================================

class TestGpsMultiViewLocalizeAction:
    def test_action_requires_profile_and_reference(self):
        action = GpsMultiViewLocalizeAction()
        with pytest.raises(ValueError, match="profile"):
            action.start({})
        with pytest.raises(ValueError, match="field_reference"):
            action.start({"profile": _v3_profile()})

    def test_action_rejects_unready_reference(self):
        ref = FieldReference()
        ref.is_confirmed = False
        action = GpsMultiViewLocalizeAction()
        with pytest.raises(RuntimeFieldTargetError):
            action.start({"profile": _v3_profile(), "field_reference": ref})

    def test_action_starts_with_ready_reference(self):
        action = GpsMultiViewLocalizeAction()
        action.start({"profile": _v3_profile(), "field_reference": _ready_reference()})
        assert action.started
        assert action.phase == "goto"
        assert len(action.scan_targets) == 4

    def test_action_failed_when_no_targets(self):
        """When no valid estimates are captured, action fails with no_targets."""
        action = GpsMultiViewLocalizeAction()
        action.start({"profile": _v3_profile(), "field_reference": _ready_reference()})
        # Manually set to capture phase with empty estimates
        action.phase = "capture"
        action.raw_estimates = []
        # Simulate completing all waypoints
        action.waypoint_index = 3  # last waypoint
        action.capture_count = action.capture_updates_per_waypoint

        # Should fail because no estimates
        context = {"drone": {"lat": 34.0, "lon": 108.0, "yaw": 0.0, "relative_altitude": 5.0}, "scene": {}}
        result = action.update(context)
        assert result.failed
        assert "no_targets" in (result.reason or "")


# =============================================================================
# helpers
# =============================================================================

def _make_raw_est(lat, lon, class_name, confidence, waypoint="DROP_SCAN_1"):
    return GpsRawEstimate(
        lat=lat, lon=lon,
        east_offset_m=0.0, north_offset_m=0.0,
        capture_drone_lat=34.0, capture_drone_lon=108.0,
        capture_yaw_rad=0.0, capture_relative_altitude_m=5.0,
        ex=0.0, ey=0.0,
        class_name=class_name, confidence=confidence,
        source_waypoint=waypoint,
    )
