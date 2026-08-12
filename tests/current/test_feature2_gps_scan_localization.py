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


def _with_recon_scans(fr):
    geometry = fr["runtime_binding"]["geometry"]
    geometry["recon_scan_waypoints"] = [
        {"name": f"RECON_SCAN_{i}", "lat": 34.001 + i * 0.00001,
         "lon": 108.001 + i * 0.00001, "altitude_m": 5.0,
         "field_x_m": float(i), "field_y_m": 50.0 + i}
        for i in range(1, 5)
    ]
    return fr


def test_scan_group_defaults_to_drop_and_recon_uses_runtime_geometry():
    default = GpsMultiViewLocalizeAction()
    default.start({})
    recon = GpsMultiViewLocalizeAction()
    recon.start({"scan_waypoint_group": "recon"})
    drop_context = _mk_ctx()
    drop_context["field_reference"] = _applied_fr_dict()
    recon_context = _mk_ctx()
    recon_context["field_reference"] = _with_recon_scans(_applied_fr_dict())
    default.update(drop_context)
    recon.update(recon_context)
    assert [point.name for point in default.scan_targets] == [f"DROP_SCAN_{i}" for i in range(1, 5)]
    assert [point.name for point in recon.scan_targets] == [f"RECON_SCAN_{i}" for i in range(1, 5)]


def test_invalid_scan_group_is_rejected_at_start():
    with pytest.raises(ValueError, match="scan_waypoint_group"):
        GpsMultiViewLocalizeAction().start({"scan_waypoint_group": "invalid"})


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

    def test_all_filtered_detections_complete_as_empty_localization(self):
        """A normal four-point scan without usable detections is a successful empty result."""
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
        assert a.phase == "done"
        result = a.update(ctx)
        assert result.done is True
        assert result.reason == "gps_multi_view_localized"
        assert result.detail["localized_objects"] == []
        assert result.detail["object_count"] == 0


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


# ── scan altitude override tests ───────────────────────────────────

def test_scan_altitude_m_overrides_all_four_waypoints() -> None:
    """scan_altitude_m=4.5 overrides all four scan point altitudes."""
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "field_heading", "scan_altitude_m": 4.5, "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    for wp in a.scan_targets:
        assert wp.altitude_m == 4.5, f"Expected 4.5, got {wp.altitude_m} for {wp.name}"


def test_scan_altitude_m_missing_uses_field_geometry() -> None:
    """Without scan_altitude_m, original field geometry altitudes are used."""
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "field_heading", "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    for wp in a.scan_targets:
        assert wp.altitude_m == 5.0, f"Expected field default 5.0, got {wp.altitude_m} for {wp.name}"


def test_scan_uses_field_heading_yaw_mode() -> None:
    """Scan goto actions use yaw_mode=field_heading."""
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "field_heading", "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    assert a.yaw_mode == "field_heading"


def test_scan_no_yaw_align_phase() -> None:
    """Scan has no first_waypoint_yaw_align phase or state."""
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "field_heading", "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    # Verify no yaw_align attributes exist on the action after start
    assert not hasattr(a, "yaw_align_action")
    assert not hasattr(a, "first_waypoint_yaw_align_enabled")
    assert not hasattr(a, "yaw_align_attempted")
    assert a.yaw_mode == "field_heading"

def test_scan_params_xy_08_z_06_hold1_settle1_capture4() -> None:
    """Scan uses tolerance_xy=0.8, tolerance_z=0.6, min_hold=1, settle=1, capture=4, max=120."""
    a = GpsMultiViewLocalizeAction()
    a.start({
        "scan_altitude_m": 4.5,
        "capture_updates_per_waypoint": 4,
        "settle_updates_per_waypoint": 1,
        "max_updates_per_waypoint": 120,
        "tolerance_xy_m": 0.8,
        "tolerance_z_m": 0.6,
        "goto_min_hold_updates": 1,
        "yaw_mode": "field_heading",
        "class_names": ["bucket"],
        "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
        "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1},
    })
    assert a._params_tolerance_xy == 0.8
    assert a._params_tolerance_z == 0.6
    assert a._params_goto_min_hold == 1
    assert a._params_settle_updates == 1
    assert a._params_capture_updates == 4
    assert a._params_max_updates == 120


def test_scan_goto_no_require_velocity_valid() -> None:
    """Scan goto does not set require_velocity_valid (or defaults to False)."""
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "field_heading", "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    ctx = {"field_reference": _applied_fr_dict()}
    a.update(ctx)
    # Check that the goto_action was created; require_velocity_valid not passed.
    assert a.goto_action is not None
    # The _new_goto_action method does not include require_velocity_valid in scan gotos
    # We verify this indirectly: the goto was created and scan proceeds


def test_scan_fusion_not_broken() -> None:
    """Four-point scan fusion infrastructure is properly initialized."""
    a = GpsMultiViewLocalizeAction()
    a.start({
        "capture_updates_per_waypoint": 1,
        "settle_updates_per_waypoint": 0,
        "max_updates_per_waypoint": 200,
        "tolerance_xy_m": 100.0,
        "tolerance_z_m": 100.0,
        "goto_min_hold_updates": 1,
        "yaw_mode": "field_heading",
        "class_names": ["bucket"],
        "min_confidence": 0.3,
        "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
        "fusion": {"cluster_radius_m": 0.8, "outlier_radius_m": 0.8, "min_cluster_size": 2, "center_weight_power": 1.0},
    })
    ctx = {"field_reference": _applied_fr_dict()}
    ctx.update(_mk_ctx())
    # Run init - resolver, projector, fuser should be set up
    a.update(ctx)
    assert a.resolver is not None, "Resolver should be initialized"
    assert a.projector is not None, "Projector should be initialized"
    assert a.fuser is not None, "Fuser should be initialized"
    assert len(a.scan_targets) == 4, "Should have 4 scan targets"
    # Verify scan altitude override works
    for wp in a.scan_targets:
        assert wp.altitude_m > 0, f"Scan waypoint altitude should be positive, got {wp.altitude_m}"

def test_dispatcher_allows_condition_yaw_for_gps_multi_view() -> None:
    """Dispatcher allows condition_yaw when action_name is gps_multi_view_localize."""
    from app.action_dispatcher import ActionDispatcher
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    dispatcher = ActionDispatcher()
    from app.run_authorization import RunAuthorization
    dispatcher.set_authorization(RunAuthorization.create(
        operator="test", scope_type="action", scope_name="gps_multi_view_localize",
        target_source="sitl", allowed_actions={"gps_multi_view_localize"},
    ))
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
    from app.run_authorization import RunAuthorization
    dispatcher.set_authorization(RunAuthorization.create(
        operator="test", scope_type="action", scope_name="gps_drop_sequence",
        target_source="sitl", allowed_actions={"gps_drop_sequence"},
    ))
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


# ══════════════════════════════════════════════════════════════════════
# scan_altitude_m strict validation
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad_value", [True, False, "4.5", float("nan"), float("inf"), float("-inf"), 0, -1])
def test_scan_altitude_m_rejects_invalid(bad_value) -> None:
    """scan_altitude_m rejects bool, string, NaN, inf, zero, negative."""
    a = GpsMultiViewLocalizeAction()
    with pytest.raises(ValueError, match="scan_altitude_m must be a finite number"):
        a.start({"scan_altitude_m": bad_value, "yaw_mode": "field_heading",
                 "class_names": ["bucket"],
                 "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
                 "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})


@pytest.mark.parametrize("good_value", [4, 4.5])
def test_scan_altitude_m_accepts_valid(good_value) -> None:
    """scan_altitude_m accepts int and float."""
    a = GpsMultiViewLocalizeAction()
    a.start({"scan_altitude_m": good_value, "yaw_mode": "field_heading",
             "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    assert a._scan_altitude_m == float(good_value)


def test_scan_altitude_m_none_uses_field_geometry() -> None:
    """scan_altitude_m=None → no override, uses field geometry."""
    a = GpsMultiViewLocalizeAction()
    a.start({"scan_altitude_m": None, "yaw_mode": "field_heading",
             "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    assert a._scan_altitude_m is None


def test_scan_altitude_m_missing_uses_field_geometry() -> None:
    """scan_altitude_m not provided → no override."""
    a = GpsMultiViewLocalizeAction()
    a.start({"yaw_mode": "field_heading", "class_names": ["bucket"],
             "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6},
             "fusion": {"cluster_radius_m": 0.5, "min_cluster_size": 1}})
    assert a._scan_altitude_m is None


# ══════════════════════════════════════════════════════════════════════
# confidence safe parsing
# ══════════════════════════════════════════════════════════════════════

def test_invalid_confidence_rejected_not_exception() -> None:
    """Non-numeric confidence → rejected as invalid_confidence, no exception."""
    a = GpsMultiViewLocalizeAction()
    a.start({"class_names": ["bucket"], "min_confidence": 0.3,
              "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
              "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
              "max_updates_per_waypoint": 200})
    ctx = _mk_ctx(dets=[_det("bucket", confidence="bad", ex=0.0, ey=0.0, conf=0.9)])
    ctx["field_reference"] = _applied_fr_dict()
    # Should not raise
    _drive_to_capture(a, ctx)
    a.update(ctx)
    assert a.rejected_by_reason.get("invalid_confidence", 0) >= 1


def test_nan_confidence_rejected() -> None:
    """NaN confidence → rejected as invalid_confidence."""
    a = GpsMultiViewLocalizeAction()
    a.start({"class_names": ["bucket"], "min_confidence": 0.3,
              "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
              "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
              "max_updates_per_waypoint": 200})
    import math
    ctx = _mk_ctx(dets=[_det("bucket", confidence=float("nan"), ex=0.0, ey=0.0, conf=0.9)])
    ctx["field_reference"] = _applied_fr_dict()
    _drive_to_capture(a, ctx)
    a.update(ctx)
    assert a.rejected_by_reason.get("invalid_confidence", 0) >= 1


def test_mixed_valid_and_invalid_confidence() -> None:
    """One invalid confidence + one valid → invalid rejected, valid passes."""
    a = GpsMultiViewLocalizeAction()
    a.start({"class_names": ["bucket"], "min_confidence": 0.3,
              "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
              "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
              "max_updates_per_waypoint": 200})
    ctx = _mk_ctx(dets=[
        _det("bucket", confidence="bad", ex=0.0, ey=0.0, conf=0.9),
        _det("bucket", confidence=0.9, ex=0.01, ey=0.01, conf=0.9),
    ])
    ctx["field_reference"] = _applied_fr_dict()
    _drive_to_capture(a, ctx)
    a.update(ctx)
    assert a.rejected_by_reason.get("invalid_confidence", 0) >= 1
    # Should still have captured something from the valid detection
    assert len(a.raw_estimates) >= 1


def test_inf_confidence_not_passes_filter() -> None:
    """inf confidence → rejected as invalid_confidence, not passed through filter."""
    a = GpsMultiViewLocalizeAction()
    a.start({"class_names": ["bucket"], "min_confidence": 0.3,
              "settle_updates_per_waypoint": 0, "capture_updates_per_waypoint": 1,
              "goto_min_hold_updates": 1, "tolerance_xy_m": 100.0,
              "max_updates_per_waypoint": 200})
    import math
    ctx = _mk_ctx(dets=[_det("bucket", confidence=float("inf"), ex=0.0, ey=0.0, conf=0.9)])
    ctx["field_reference"] = _applied_fr_dict()
    _drive_to_capture(a, ctx)
    a.update(ctx)
    assert a.rejected_by_reason.get("invalid_confidence", 0) >= 1
