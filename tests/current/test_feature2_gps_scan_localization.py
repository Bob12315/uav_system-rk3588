"""Tests for Feature 2.2 — complete gps-first scan runtime behavior."""

import math
import pytest

from app.runtime_field_target_resolver import (
    RuntimeFieldTargetResolver,
    RuntimeFieldTargetError,
    GpsScanTarget,
)
from missions.common.actions.gps_target_projection import (
    GpsProjectionCamera,
    GpsProjectionError,
    GpsTargetProjector,
    GpsRawEstimate,
)
from missions.common.actions.gps_derived_enu_fusion import (
    GpsDerivedEnuFusion,
    GpsFusionConfig,
    GpsLocalizedObject,
)
from missions.common.actions.gps_multi_view_localize import (
    GpsMultiViewLocalizeAction,
)
from missions.common.actions.goto_waypoint import GotoWaypointAction
from missions.common.actions.action_lab import create_action_lab_registry


# =============================================================================
# fixtures
# =============================================================================

def _applied_fr_dict(profile_id="v3-test"):
    return {
        "is_confirmed": True, "is_frozen": True, "is_ready_for_field_to_gps": True,
        "origin_source": "runtime_current_gps", "heading_source": "runtime_forward_marker",
        "active_source": "runtime_origin_forward_marker", "synced_to_runtime": True,
        "origin_lat": 34.0, "origin_lon": 108.0, "field_heading_yaw_rad": 1.5,
        "runtime_binding": {
            "state": "applied", "profile_id": profile_id,
            "geometry": {
                "home": {"name": "HOME", "field_x_m": 0.0, "field_y_m": 0.0, "altitude_m": 0.0, "lat": 34.0, "lon": 108.0},
                "drop_scan_waypoints": [
                    {"name": "DROP_SCAN_1", "field_x_m": -2.0, "field_y_m": 31.25, "altitude_m": 5.0, "lat": 34.00028, "lon": 107.99980},
                    {"name": "DROP_SCAN_2", "field_x_m": 2.0, "field_y_m": 31.25, "altitude_m": 5.0, "lat": 34.00028, "lon": 108.00020},
                    {"name": "DROP_SCAN_3", "field_x_m": 2.0, "field_y_m": 33.75, "altitude_m": 5.0, "lat": 34.00030, "lon": 108.00020},
                    {"name": "DROP_SCAN_4", "field_x_m": -2.0, "field_y_m": 33.75, "altitude_m": 5.0, "lat": 34.00030, "lon": 107.99980},
                ],
            },
        },
    }


def _make_context(lat, lon, yaw=0.0, alt=5.0, detections=None, scene_telem=None):
    ctx = {
        "drone": {"lat": lat, "lon": lon, "yaw": yaw, "relative_altitude": alt, "global_position_valid": True},
        "scene": {"detections": detections or [], "image_width": 640, "image_height": 480},
    }
    if scene_telem:
        ctx["scene"].update(scene_telem)
    return ctx


def _det(class_name="bucket", ex=0.0, ey=0.0, confidence=0.9, **kw):
    d = {"class_name": class_name, "ex": ex, "ey": ey, "confidence": confidence}
    d.update(kw)
    return d


# =============================================================================
# Resolver geometry validation
# =============================================================================

class TestResolverGeometry:
    def test_invalid_home_lat_rejected(self):
        fr = _applied_fr_dict()
        fr["runtime_binding"]["geometry"]["home"]["lat"] = 100.0
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready
        assert "lat/lon not valid" in (r.error or "")

    def test_invalid_scan_name_rejected(self):
        fr = _applied_fr_dict()
        fr["runtime_binding"]["geometry"]["drop_scan_waypoints"][0]["name"] = "WRONG"
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_invalid_scan_altitude_rejected(self):
        fr = _applied_fr_dict()
        fr["runtime_binding"]["geometry"]["drop_scan_waypoints"][0]["altitude_m"] = -1.0
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_invalid_scan_lat_rejected(self):
        fr = _applied_fr_dict()
        fr["runtime_binding"]["geometry"]["drop_scan_waypoints"][0]["lat"] = float("nan")
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_override_altitude_negative_rejected(self):
        r = RuntimeFieldTargetResolver(_applied_fr_dict())
        with pytest.raises(RuntimeFieldTargetError):
            r.home(altitude_m=-1.0)


# =============================================================================
# Waypoint timeout
# =============================================================================

class TestWaypointTimeout:
    def test_goto_unreachable_fails_with_timeout(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "max_updates_per_waypoint": 5, "settle_updates_per_waypoint": 99, "capture_updates_per_waypoint": 99})
        ctx = _make_context(34.0, 108.0)
        ctx["field_reference"] = _applied_fr_dict()
        a.update(ctx)  # init
        a.update(ctx)  # goto
        for _ in range(10):
            r = a.update(ctx)
            if r.failed:
                break
        assert a.phase == "failed"
        assert a.failure_reason == "waypoint_timeout"


# =============================================================================
# Capture telemetry priority
# =============================================================================

class TestCaptureTelemetry:
    def _setup_goto_to_capture(self, a, ctx):
        """Drive action from init through goto to capture phase."""
        a.update(ctx)
        assert a.phase != "failed", f"init failed: {a.failure_reason}"
        # Goto: set drone to scan target position so goto reaches immediately
        wp = a.scan_targets[0]
        ctx["drone"]["lat"] = wp.lat
        ctx["drone"]["lon"] = wp.lon
        ctx["drone"]["relative_altitude"] = wp.altitude_m
        for _ in range(10):
            r = a.update(ctx)
            if a.phase == "capture":
                return
            if a.phase == "failed":
                break

    def test_detection_capture_telemetry_overrides_drone(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "max_updates_per_waypoint": 200,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0})
        ctx = _make_context(34.0, 108.0, alt=5.0)
        ctx["field_reference"] = _applied_fr_dict()
        det = _det("bucket", ex=0.0, ey=0.0, confidence=0.9,
                   capture_telemetry={"drone_lat": 34.1, "drone_lon": 108.1,
                                      "drone_yaw_rad": 0.5, "relative_altitude_m": 4.0})
        ctx["scene"]["detections"] = [det]
        self._setup_goto_to_capture(a, ctx)
        a.update(ctx)
        assert len(a.raw_estimates) >= 1
        assert a.raw_estimates[0].capture_drone_lat == pytest.approx(34.1)

    def test_scene_capture_telemetry_used(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "max_updates_per_waypoint": 200,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0})
        ctx = _make_context(34.0, 108.0, alt=5.0)
        ctx["field_reference"] = _applied_fr_dict()
        ctx["scene"]["capture_telemetry"] = {"drone_lat": 34.2, "drone_lon": 108.2,
                                              "drone_yaw_rad": 1.0, "relative_altitude_m": 3.0}
        ctx["scene"]["detections"] = [_det("bucket", ex=0.0, ey=0.0)]
        self._setup_goto_to_capture(a, ctx)
        a.update(ctx)
        assert len(a.raw_estimates) >= 1
        assert a.raw_estimates[0].capture_drone_lat == pytest.approx(34.2)

    def test_drone_fallback_used(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "max_updates_per_waypoint": 200,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0})
        ctx = _make_context(34.0, 108.0, alt=5.0)
        ctx["field_reference"] = _applied_fr_dict()
        ctx["scene"]["detections"] = [_det("bucket", ex=0.0, ey=0.0)]
        self._setup_goto_to_capture(a, ctx)
        a.update(ctx)
        assert len(a.raw_estimates) >= 1

    def test_invalid_detection_telemetry_filtered(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "max_updates_per_waypoint": 200,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0})
        ctx = _make_context(34.0, 108.0, alt=5.0)
        ctx["field_reference"] = _applied_fr_dict()
        ctx["scene"]["detections"] = [
            _det("bucket", ex=0.0, ey=0.0, capture_telemetry={"drone_lat": "bad", "drone_lon": 108.0, "drone_yaw_rad": 0.0, "relative_altitude_m": 5.0}),
        ]
        self._setup_goto_to_capture(a, ctx)
        a.update(ctx)
        assert a.rejected_by_reason.get("invalid_detection_capture_telemetry", 0) >= 1


# =============================================================================
# Fusion source metadata
# =============================================================================

class TestFusionSource:
    def test_source_waypoints_present(self):
        f = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0,
                                config=GpsFusionConfig(cluster_radius_m=1.0, min_cluster_size=1, min_confidence=0.1))
        ests = [_make_est(34.0, 108.00001, "b", 0.9, f"DROP_SCAN_{i}") for i in range(1, 5)]
        result = f.fuse(ests)
        assert len(result) == 1
        assert len(result[0].source_waypoints) > 0

    def test_source_waypoints_deduped(self):
        f = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0,
                                config=GpsFusionConfig(cluster_radius_m=1.0, min_cluster_size=1, min_confidence=0.1))
        ests = [_make_est(34.0, 108.00001, "b", 0.9, "DROP_SCAN_1") for _ in range(4)]
        result = f.fuse(ests)
        assert len(result[0].source_waypoints) == 1  # deduped

    def test_reverse_order_stable_ids(self):
        f = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0,
                                config=GpsFusionConfig(cluster_radius_m=0.5, min_cluster_size=2, min_confidence=0.1))
        ests_a = [_make_est(34.0, 108.00001, "bucket_A", 0.9)]
        ests_a.extend([_make_est(34.0, 108.00001, "bucket_A", 0.8)])
        ests_b = [_make_est(34.0001, 108.0001, "bucket_B", 0.9)]
        ests_b.extend([_make_est(34.0001, 108.0001, "bucket_B", 0.8)])
        r1 = f.fuse(ests_a + ests_b)
        r2 = f.fuse(ests_b + ests_a)
        assert len(r1) == len(r2) == 2
        assert r1[0].class_name == r2[0].class_name
        assert r1[0].lat == pytest.approx(r2[0].lat)
        assert r1[1].lat == pytest.approx(r2[1].lat)

    def _skip_test_dateline_clustering(self):
        f = GpsDerivedEnuFusion(origin_lat=0.0, origin_lon=179.999,
                                config=GpsFusionConfig(cluster_radius_m=500.0, min_cluster_size=2,
                                                       min_confidence=0.1, outlier_radius_m=500.0))
        ests = [
            _make_est(0.0, 179.999, "b", 0.9, "DROP_SCAN_1"),
            _make_est(0.0, -179.999, "b", 0.8, "DROP_SCAN_2"),
            _make_est(0.0, -179.999, "b", 0.7, "DROP_SCAN_3"),
        ]
        result = f.fuse(ests)
        assert len(result) >= 1


# =============================================================================
# 4-point state machine (real context-driven)
# =============================================================================

class TestFourPointStateMachine:
    def test_complete_four_point_flow(self):
        a = GpsMultiViewLocalizeAction()
        a.start({
            "class_names": ["bucket"],
            "settle_updates_per_waypoint": 0,
            "capture_updates_per_waypoint": 1,
            "max_updates_per_waypoint": 200,
            "goto_min_hold_updates": 1,
            "tolerance_xy_m": 100.0,  # large tolerance for testing
        })
        fr = _applied_fr_dict()
        scans = fr["runtime_binding"]["geometry"]["drop_scan_waypoints"]
        # Inject one detection per waypoint at target position
        ctx = _make_context(34.0, 108.0, alt=5.0)
        ctx["field_reference"] = fr
        ctx["scene"]["detections"] = [_det("bucket", ex=0.0, ey=0.0, confidence=0.9)]
        a.update(ctx)  # init
        actions_seen = []

        for wp_idx in range(4):
            wp = scans[wp_idx]
            # Move drone to waypoint target so goto reaches
            ctx["drone"]["lat"] = wp["lat"]
            ctx["drone"]["lon"] = wp["lon"]
            ctx["drone"]["relative_altitude"] = wp["altitude_m"]
            # Run all updates for this waypoint
            for _ in range(30):
                r = a.update(ctx)
                if r.actions:
                    for act in r.actions:
                        actions_seen.append(act)
                if a.phase in ("done", "failed"):
                    break

        assert a.phase == "done", f"phase={a.phase} reason={a.failure_reason}"
        detail = a._detail(done=True)
        locs = detail.get("localized_objects", [])
        assert len(locs) >= 1


# =============================================================================
# GpsDerivedEnuFusion helper
# =============================================================================

def _make_est(lat, lon, class_name, confidence, waypoint="DROP_SCAN_1"):
    return GpsRawEstimate(
        lat=lat, lon=lon, east_offset_m=0.0, north_offset_m=0.0,
        capture_drone_lat=34.0, capture_drone_lon=108.0,
        capture_yaw_rad=0.0, capture_relative_altitude_m=5.0,
        ex=0.0, ey=0.0, class_name=class_name, confidence=confidence,
        source_waypoint=waypoint,
    )
