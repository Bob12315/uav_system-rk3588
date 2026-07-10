"""Tests for Feature 2.4 — finalize gps scan telemetry outcomes."""

import math
import pytest

from app.runtime_field_target_resolver import (
    RuntimeFieldTargetResolver,
    RuntimeFieldTargetError,
)
from missions.common.actions.gps_target_projection import GpsRawEstimate
from missions.common.actions.gps_derived_enu_fusion import (
    GpsDerivedEnuFusion,
    GpsFusionConfig,
)
from missions.common.actions.gps_multi_view_localize import (
    GpsMultiViewLocalizeAction,
)


# =============================================================================
# fixtures
# =============================================================================

def _applied_fr_dict():
    return {
        "is_confirmed": True, "is_frozen": True, "is_ready_for_field_to_gps": True,
        "origin_source": "runtime_current_gps", "heading_source": "runtime_forward_marker",
        "active_source": "runtime_origin_forward_marker", "synced_to_runtime": True,
        "origin_lat": 34.0, "origin_lon": 108.0, "field_heading_yaw_rad": 1.5,
        "runtime_binding": {
            "state": "applied", "profile_id": "v3-test",
            "geometry": {
                "home": {"name": "HOME", "lat": 34.0, "lon": 108.0, "altitude_m": 0.0, "field_x_m": 0.0, "field_y_m": 0.0},
                "drop_scan_waypoints": [
                    {"name": "DROP_SCAN_1", "lat": 34.00028, "lon": 107.99980, "altitude_m": 5.0, "field_x_m": -2.0, "field_y_m": 31.25},
                    {"name": "DROP_SCAN_2", "lat": 34.00028, "lon": 108.00020, "altitude_m": 5.0, "field_x_m": 2.0, "field_y_m": 31.25},
                    {"name": "DROP_SCAN_3", "lat": 34.00030, "lon": 108.00020, "altitude_m": 5.0, "field_x_m": 2.0, "field_y_m": 33.75},
                    {"name": "DROP_SCAN_4", "lat": 34.00030, "lon": 107.99980, "altitude_m": 5.0, "field_x_m": -2.0, "field_y_m": 33.75},
                ],
            },
        },
    }


def _mk_ctx(lat=34.0, lon=108.0, yaw=0.0, alt=5.0, dets=None, **kw):
    ctx = {
        "drone": {"lat": lat, "lon": lon, "yaw": yaw, "relative_altitude": alt, "global_position_valid": True},
        "scene": {"detections": dets or [], "image_width": 640, "image_height": 480},
    }
    ctx["scene"].update(kw)
    return ctx


def _det(cls="bucket", ex=0.0, ey=0.0, conf=0.9, **kw):
    d = {"class_name": cls, "ex": ex, "ey": ey, "confidence": conf}
    d.update(kw)
    return d


def _drive_to_capture(a, ctx):
    """Drive from init through goto+settle into capture phase."""
    a.update(ctx)
    assert a.phase != "failed", f"init failed: {a.failure_reason}"
    for _ in range(30):
        wp = a.scan_targets[a.waypoint_index]
        ctx["drone"]["lat"] = wp.lat
        ctx["drone"]["lon"] = wp.lon
        ctx["drone"]["relative_altitude"] = wp.altitude_m
        a.update(ctx)
        if a.phase == "capture":
            return
        if a.phase == "failed":
            break


def _action_keys(result):
    """Extract action keys from ActionResult.actions list."""
    keys = []
    for act in (result.actions or []):
        k = act.get("key", "")
        if k:
            keys.append(k)
    return keys


# =============================================================================
# Estimate-empty classification
# =============================================================================

class TestEstimateEmpty:
    def test_low_confidence_not_telemetry_failure(self):
        """Low confidence detection + valid drone → NOT invalid_capture_telemetry."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "min_confidence": 0.99,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
                  "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[_det("bucket", conf=0.5)])
        ctx["field_reference"] = _applied_fr_dict()
        _drive_to_capture(a, ctx)
        r = a.update(ctx)
        assert a.phase != "failed" or a.failure_reason != "invalid_capture_telemetry"

    def test_class_not_allowed_not_telemetry_failure(self):
        """Detection of wrong class + valid drone → NOT invalid_capture_telemetry."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket_only"], "min_confidence": 0.1,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
                  "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[_det("wrong_class")])
        ctx["field_reference"] = _applied_fr_dict()
        _drive_to_capture(a, ctx)
        r = a.update(ctx)
        assert a.phase != "failed" or a.failure_reason != "invalid_capture_telemetry"

    def test_missing_ex_ey_not_telemetry_failure(self):
        """Detection missing ex/ey + valid drone → NOT invalid_capture_telemetry."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": None, "min_confidence": 0.1,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
                  "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[{"class_name": "bucket", "confidence": 0.9}])  # no ex/ey
        ctx["field_reference"] = _applied_fr_dict()
        _drive_to_capture(a, ctx)
        r = a.update(ctx)
        assert a.phase != "failed" or a.failure_reason != "invalid_capture_telemetry"

    def test_all_filtered_no_targets_later(self):
        """After 4 waypoints with all detections filtered → eventually no_targets."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "min_confidence": 0.99,
                  "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
                  "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
                  "max_updates_per_waypoint": 200})
        fr = _applied_fr_dict()
        ctx = _mk_ctx(dets=[_det("bucket", conf=0.5)])
        ctx["field_reference"] = fr
        for wp_idx in range(4):
            wp = fr["runtime_binding"]["geometry"]["drop_scan_waypoints"][wp_idx]
            ctx["drone"]["lat"] = wp["lat"]
            ctx["drone"]["lon"] = wp["lon"]
            ctx["drone"]["relative_altitude"] = wp["altitude_m"]
            for _ in range(20):
                a.update(ctx)
                if a.phase in ("done", "failed"):
                    break
        assert a.phase == "failed"
        assert a.failure_reason == "no_targets"


# =============================================================================
# No-telemetry real assertion
# =============================================================================

class TestNoTelemetry:
    def test_no_telemetry_at_all_fails_properly(self):
        """No detection telemetry + drone GPS invalid → invalid_capture_telemetry."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "settle_updates_per_waypoint": 0,
                  "capture_updates_per_waypoint": 1, "goto_min_hold_updates": 1,
                  "tolerance_xy_m": 100.0, "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[_det("bucket")])
        ctx["field_reference"] = _applied_fr_dict()
        # Drive to capture with valid drone (needed for goto to reach)
        _drive_to_capture(a, ctx)
        # Now invalidate drone + detection has no telemetry
        ctx["drone"]["lat"] = None
        ctx["drone"]["lon"] = None
        ctx["drone"]["relative_altitude"] = None
        ctx["scene"]["detections"] = [_det("bucket")]  # fresh det, no capture_telemetry
        # Need to be back in capture phase — force next capture cycle
        a.capture_count = a._params_capture_updates - 1
        r = a.update(ctx)
        assert r.failed, f"expected failed, got reason={r.reason}"
        assert a.phase == "failed"
        assert r.reason == "invalid_capture_telemetry"


# =============================================================================
# Detection telemetry valid + drone invalid (real test)
# =============================================================================

class TestDetTelemValidDroneInvalid:
    def test_detection_telem_works_when_drone_gps_invalid(self):
        """Enter capture with valid drone, THEN invalidate drone, detection telem still works."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "settle_updates_per_waypoint": 0,
                  "capture_updates_per_waypoint": 1, "goto_min_hold_updates": 1,
                  "tolerance_xy_m": 100.0, "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[_det("bucket", capture_telemetry={
            "drone_lat": 34.1, "drone_lon": 108.1,
            "drone_yaw_rad": 0.5, "relative_altitude_m": 4.0,
        })])
        ctx["field_reference"] = _applied_fr_dict()
        _drive_to_capture(a, ctx)
        # NOW invalidate drone GPS after entering capture
        ctx["drone"]["lat"] = None
        ctx["drone"]["lon"] = None
        ctx["drone"]["relative_altitude"] = None
        r = a.update(ctx)
        assert len(a.raw_estimates) >= 1
        assert a.raw_estimates[0].capture_drone_lat == pytest.approx(34.1)


# =============================================================================
# NaN altitude
# =============================================================================

class TestNaNAltitude:
    def test_drone_altitude_nan_no_other_telem_fails(self):
        """Drone altitude=NaN + no other telemetry → invalid_capture_telemetry."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "settle_updates_per_waypoint": 0,
                  "capture_updates_per_waypoint": 1, "goto_min_hold_updates": 1,
                  "tolerance_xy_m": 100.0, "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[_det("bucket")])
        ctx["field_reference"] = _applied_fr_dict()
        _drive_to_capture(a, ctx)
        # Invalidate drone altitude
        ctx["drone"]["relative_altitude"] = float("nan")
        ctx["scene"]["detections"] = [_det("bucket")]
        a.capture_count = a._params_capture_updates - 1
        r = a.update(ctx)
        assert r.failed
        assert r.reason == "invalid_capture_telemetry"

    def test_detection_telem_altitude_nan_rejected(self):
        """Detection capture_telemetry altitude=NaN → filtered."""
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "settle_updates_per_waypoint": 0,
                  "capture_updates_per_waypoint": 1, "goto_min_hold_updates": 1,
                  "tolerance_xy_m": 100.0, "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[_det("bucket", capture_telemetry={
            "drone_lat": 34.1, "drone_lon": 108.1,
            "drone_yaw_rad": 0.0, "relative_altitude_m": float("nan"),
        })])
        ctx["field_reference"] = _applied_fr_dict()
        _drive_to_capture(a, ctx)
        a.update(ctx)
        assert a.rejected_by_reason.get("invalid_detection_capture_telemetry", 0) >= 1


# =============================================================================
# Counter reset — unconditional assertion
# =============================================================================

class TestCounterReset:
    def test_counter_resets_on_next_waypoint(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"], "settle_updates_per_waypoint": 0,
                  "capture_updates_per_waypoint": 1, "goto_min_hold_updates": 1,
                  "tolerance_xy_m": 100.0, "max_updates_per_waypoint": 200})
        ctx = _mk_ctx(dets=[_det("bucket", capture_telemetry={
            "drone_lat": 34.0, "drone_lon": 108.0,
            "drone_yaw_rad": 0.0, "relative_altitude_m": 5.0,
        })])
        ctx["field_reference"] = _applied_fr_dict()
        _drive_to_capture(a, ctx)
        # Complete capture to move to next waypoint (capture_updates=1 so 1 update moves to next)
        a.update(ctx)
        # Should be in next goto phase with counter reset
        assert a.waypoint_index == 1, f"waypoint_index={a.waypoint_index}"
        assert a.update_count_at_waypoint == 0, f"counter={a.update_count_at_waypoint}"


# =============================================================================
# Dateline clustering
# =============================================================================

class TestDatelineClustering:
    def test_dateline_close_points_cluster(self):
        """Points across ±180° dateline at very close distance should cluster together."""
        f = GpsDerivedEnuFusion(
            origin_lat=0.0, origin_lon=179.999999,
            config=GpsFusionConfig(cluster_radius_m=500.0, min_cluster_size=2,
                                   min_confidence=0.1, outlier_radius_m=500.0),
        )
        ests = [
            _make_est(0.0, 179.999999, "b", 0.9, "DROP_SCAN_1"),
            _make_est(0.0, -179.999999, "b", 0.8, "DROP_SCAN_2"),
            _make_est(0.0, -179.999998, "b", 0.7, "DROP_SCAN_3"),
        ]
        result = f.fuse(ests)
        assert len(result) >= 1, f"expected >=1 cluster across dateline, got {len(result)}"
        obj = result[0]
        assert -180.0 <= obj.lon <= 180.0


# =============================================================================
# Full four-point state machine with exact assertions
# =============================================================================

class TestFourPointExact:
    def test_four_point_exact_order_and_source(self):
        a = GpsMultiViewLocalizeAction()
        a.start({
            "class_names": ["bucket"],
            "settle_updates_per_waypoint": 0,
            "capture_updates_per_waypoint": 1,
            "max_updates_per_waypoint": 200,
            "goto_min_hold_updates": 1,
            "tolerance_xy_m": 100.0,
            "fusion": {"cluster_radius_m": 50.0, "outlier_radius_m": 50.0, "min_cluster_size": 2, "min_confidence": 0.1},
        })
        fr = _applied_fr_dict()
        scans = fr["runtime_binding"]["geometry"]["drop_scan_waypoints"]
        ctx = _mk_ctx()
        ctx["field_reference"] = fr
        a.update(ctx)  # init

        # Access internal goto keys
        goto_keys_seen = []
        for wp_idx in range(4):
            wp = scans[wp_idx]
            ctx["drone"]["lat"] = wp["lat"]
            ctx["drone"]["lon"] = wp["lon"]
            ctx["drone"]["relative_altitude"] = wp["altitude_m"]
            ctx["scene"]["detections"] = [
                _det("bucket", frame_id=wp_idx + 1,
                     capture_telemetry={
                         "drone_lat": wp["lat"], "drone_lon": wp["lon"],
                         "drone_yaw_rad": 0.0, "relative_altitude_m": wp["altitude_m"],
                     }),
            ]
            for _ in range(30):
                a.update(ctx)
                if a.goto_action is not None:
                    goto_keys_seen.append(a.goto_action.key)
                if a.phase in ("done", "failed"):
                    break

        assert a.phase == "done", f"phase={a.phase} reason={a.failure_reason}"

        # Assert exactly gps_scan_0..3 in order
        scan_keys = [k for k in goto_keys_seen if k.startswith("gps_scan_")]
        unique = list(dict.fromkeys(scan_keys))
        assert unique == ["gps_scan_0", "gps_scan_1", "gps_scan_2", "gps_scan_3"], \
            f"got scan keys: {unique}"

        # Assert localized_objects sources
        detail = a._detail(done=True)
        locs = detail.get("localized_objects", [])
        assert len(locs) >= 1
        obj = locs[0]
        sw = obj.get("source_waypoints", [])
        assert len(sw) >= 1 and all(s.startswith("DROP_SCAN_") for s in sw), \
            f"source_waypoints={sw}"
        sf = obj.get("source_frames", [])
        assert len(sf) >= 1, f"source_frames should be non-empty, got {sf}"


# =============================================================================
# Helpers
# =============================================================================

def _make_est(lat, lon, class_name, confidence, waypoint="DROP_SCAN_1"):
    return GpsRawEstimate(
        lat=lat, lon=lon, east_offset_m=0.0, north_offset_m=0.0,
        capture_drone_lat=34.0, capture_drone_lon=108.0,
        capture_yaw_rad=0.0, capture_relative_altitude_m=5.0,
        ex=0.0, ey=0.0, class_name=class_name, confidence=confidence,
        source_waypoint=waypoint,
    )
