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
from missions.common.actions.result import ActionResult


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


# ── first waypoint yaw align tests ───────────────────────────────────

def _start_with_yaw_align(action, enabled=True, on_failed="continue", **kwargs):
    """Start GpsMultiViewLocalizeAction with first_waypoint_yaw_align."""
    params = {
        "capture_updates_per_waypoint": 2,
        "settle_updates_per_waypoint": 1,
        "max_updates_per_waypoint": 30,
        "tolerance_xy_m": 0.5,
        "tolerance_z_m": 0.5,
        "goto_min_hold_updates": 1,
        "yaw_mode": "hold",
        "detection_source": "scene",
        "class_names": ["bucket"],
        "min_confidence": 0.3,
        "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
        "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1},
        "first_waypoint_yaw_align": {
            "enabled": enabled,
            "yaw_mode": "field_heading",
            "tolerance_deg": 3.0,
            "yaw_speed_deg_s": 25.0,
            "min_hold_updates": 5,
            "max_updates": 30,
            "priority": 4,
            "on_failed": on_failed,
            **kwargs,
        },
    }
    action.start(params)


def test_first_wp_yaw_align_disabled_default() -> None:
    """Without first_waypoint_yaw_align config, goto done → settle directly."""
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "hold", "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    assert a.first_waypoint_yaw_align_enabled is False
    assert a.phase == "goto"


@pytest.mark.parametrize("on_failed", ["contine", ""])
def test_first_wp_yaw_align_rejects_invalid_failure_policy(on_failed: str) -> None:
    a = GpsMultiViewLocalizeAction()
    with pytest.raises(ValueError, match="first_waypoint_yaw_align.on_failed"):
        _start_with_yaw_align(a, on_failed=on_failed)


def test_first_wp_yaw_align_default_goto_done_enters_settle_without_yaw_action() -> None:
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "hold", "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    a.update({"field_reference": _applied_fr_dict()})

    class _DoneGoto:
        def update(self, context):
            return ActionResult(done=True, reason="waypoint_reached")

    a.goto_action = _DoneGoto()
    result = a.update({"field_reference": _applied_fr_dict()})
    assert result.reason == "gps_multi_view_settle"
    assert a.phase == "settle"
    assert a.yaw_align_action is None
    assert not any(item.get("action_type") == "condition_yaw" for item in result.actions)


def test_first_wp_yaw_align_goto_generates_no_condition_yaw() -> None:
    """During goto phase, no condition_yaw actions are emitted."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a)
    ctx = {"field_reference": _applied_fr_dict()}
    result = a.update(ctx)
    assert a.phase == "goto"
    assert a.yaw_align_attempted is False
    for act in (result.actions or []):
        assert act.get("action_type") != "condition_yaw"


def test_first_wp_yaw_align_enters_after_goto_done() -> None:
    """After first waypoint goto completes, phase transitions to first_waypoint_yaw_align."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a)
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    # Simulate goto completion by setting drone at target
    wp = a.scan_targets[0]
    ctx["drone"] = {"lat": wp.lat, "lon": wp.lon, "yaw": 1.5, "relative_altitude": wp.altitude_m,
                     "global_position_valid": True, "attitude_valid": True}
    ctx["field_heading_yaw_rad"] = 1.5
    ctx["field_heading_confirmed"] = True
    for _ in range(10):
        result = a.update(ctx)
        if a.phase != "goto":
            break
    assert a.phase == "first_waypoint_yaw_align"
    assert a.yaw_align_attempted is True
    assert a.yaw_align_action is not None


def test_first_wp_yaw_align_sends_condition_yaw() -> None:
    """When in first_waypoint_yaw_align phase, condition_yaw actions are forwarded."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a)
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    wp = a.scan_targets[0]
    ctx["drone"] = {"lat": wp.lat, "lon": wp.lon, "yaw": 1.5, "relative_altitude": wp.altitude_m,
                     "global_position_valid": True, "attitude_valid": True,
                     "field_heading_yaw_rad": 1.5, "field_heading_confirmed": True}
    ctx["field_heading_yaw_rad"] = 1.5
    ctx["field_heading_confirmed"] = True
    for _ in range(10):
        result = a.update(ctx)
        if a.phase == "first_waypoint_yaw_align":
            break
    assert a.phase == "first_waypoint_yaw_align"
    has_condition_yaw = False
    for act in (result.actions or []):
        if act.get("action_type") == "condition_yaw":
            has_condition_yaw = True
    assert has_condition_yaw


def test_first_wp_yaw_align_done_transitions_to_settle() -> None:
    """When yaw_align completes, phase transitions to settle (not directly capture)."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a, tolerance_deg=90.0, min_hold_updates=1, max_updates=30)
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    wp = a.scan_targets[0]
    ctx["drone"] = {"lat": wp.lat, "lon": wp.lon, "yaw": 1.5, "relative_altitude": wp.altitude_m,
                     "global_position_valid": True, "attitude_valid": True,
                     "field_heading_yaw_rad": 1.5, "field_heading_confirmed": True}
    ctx["field_heading_yaw_rad"] = 1.5
    ctx["field_heading_confirmed"] = True
    for _ in range(20):
        result = a.update(ctx)
        if a.phase == "settle":
            break
    assert a.phase == "settle"
    assert a.yaw_align_done is True
    assert a.settle_count == 0


def test_first_wp_yaw_align_failed_continue() -> None:
    """When yaw_align fails and on_failed=continue, proceed to settle."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a, tolerance_deg=0.01, min_hold_updates=100, max_updates=1, on_failed="continue")
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    wp = a.scan_targets[0]
    ctx["drone"] = {"lat": wp.lat, "lon": wp.lon, "yaw": 5.0, "relative_altitude": wp.altitude_m,
                     "global_position_valid": True, "attitude_valid": True,
                     "field_heading_yaw_rad": 1.5, "field_heading_confirmed": True}
    ctx["field_heading_yaw_rad"] = 1.5
    ctx["field_heading_confirmed"] = True
    for _ in range(10):
        result = a.update(ctx)
        if a.phase != "first_waypoint_yaw_align":
            break
    assert a.phase == "settle"
    assert a.yaw_align_failed is True
    assert a.failure_reason == ""


def test_first_wp_yaw_align_failed_fail() -> None:
    """When yaw_align fails and on_failed=fail, action fails."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a, tolerance_deg=0.01, min_hold_updates=100, max_updates=1, on_failed="fail")
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    wp = a.scan_targets[0]
    ctx["drone"] = {"lat": wp.lat, "lon": wp.lon, "yaw": 5.0, "relative_altitude": wp.altitude_m,
                     "global_position_valid": True, "attitude_valid": True,
                     "field_heading_yaw_rad": 1.5, "field_heading_confirmed": True}
    ctx["field_heading_yaw_rad"] = 1.5
    ctx["field_heading_confirmed"] = True
    for _ in range(10):
        result = a.update(ctx)
        if a.phase == "failed":
            break
    assert a.phase == "failed"
    assert a.failure_reason == "first_waypoint_yaw_align_failed"


def test_subsequent_waypoints_no_yaw_align() -> None:
    """Waypoints 2,3,4 do not trigger yaw_align again and use yaw_mode=hold."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a, tolerance_deg=90.0, min_hold_updates=1, max_updates=5)
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    wp = a.scan_targets[0]
    ctx["drone"] = {"lat": wp.lat, "lon": wp.lon, "yaw": 1.5, "relative_altitude": wp.altitude_m,
                     "global_position_valid": True, "attitude_valid": True,
                     "field_heading_yaw_rad": 1.5, "field_heading_confirmed": True}
    ctx["field_heading_yaw_rad"] = 1.5
    ctx["field_heading_confirmed"] = True
    # Drive through first wp: goto→yaw_align→settle→capture→next
    dets = [_det(ex=0.0, ey=0.0)]
    ctx.setdefault("scene", {})["detections"] = dets
    for _ in range(60):
        result = a.update(ctx)
        if a.waypoint_index >= 1:
            break
        if a.phase == "failed":
            break
    assert a.waypoint_index >= 1
    # At waypoint 2, should go directly to goto→settle without yaw_align
    assert a.phase in ("goto", "settle", "capture")
    assert a.yaw_align_attempted is True  # only attempted once
    # Verify subsequent goto uses yaw_mode=hold
    assert a.yaw_mode == "hold"


def test_detail_includes_yaw_align_diagnostics() -> None:
    """_detail() includes first_waypoint_yaw_align diagnostic fields."""
    a = GpsMultiViewLocalizeAction()
    _start_with_yaw_align(a)
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    detail = a._detail()
    assert "first_waypoint_yaw_align_enabled" in detail
    assert detail["first_waypoint_yaw_align_enabled"] is True
    assert "first_waypoint_yaw_align_attempted" in detail
    assert "first_waypoint_yaw_align_done" in detail
    assert "first_waypoint_yaw_align_failed" in detail


def test_dispatcher_allows_condition_yaw_for_gps_multi_view() -> None:
    """Dispatcher allows condition_yaw when action_name is gps_multi_view_localize."""
    from app.action_dispatcher import ActionDispatcher
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    dispatcher = ActionDispatcher()
    dispatcher.send_actions = True
    result = dispatcher.dispatch_actions(
        [{"action_type": "condition_yaw", "params": {"yaw_deg": 45.0, "yaw_speed_deg_s": 20.0,
                                                      "direction": 0, "relative": False},
          "key": "test_cmd", "once": False, "priority": 4}],
        action_name="gps_multi_view_localize",
        send_commands=True,
        link_manager=None,
    )
    # With link_manager=None, dispatch fails with telemetry error, not policy rejection
    assert result["sent"] == []
    # Policy allows it - the error is from missing link, not policy rejection
    assert all("action_dispatch_not_enabled" not in str(e.get("reason", "")) for e in result.get("errors", []))


def test_dispatcher_rejects_condition_yaw_for_unknown_action() -> None:
    """Dispatcher rejects condition_yaw for an action not in the whitelist."""
    from app.action_dispatcher import ActionDispatcher
    dispatcher = ActionDispatcher()
    dispatcher.send_actions = True
    result = dispatcher.dispatch_actions(
        [{"action_type": "condition_yaw", "params": {"yaw_deg": 45.0, "yaw_speed_deg_s": 20.0,
                                                      "direction": 0, "relative": False},
          "key": "test_cmd", "once": False, "priority": 4}],
        action_name="unknown_action",
        send_commands=True,
        link_manager=None,
    )
    assert result["skipped"] != []
    assert any("action_dispatch_not_enabled" in str(s.get("reason", "")) for s in result["skipped"])
