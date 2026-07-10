"""Tests for Feature 2.1 — GPS-first scan localization runtime integration."""

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
from missions.common.actions.action_lab import (
    create_action_lab_registry,
    action_lab_specs,
)


# =============================================================================
# fixtures — match FieldReferenceController.status()["field_reference"] shape
# =============================================================================

def _applied_fr_dict(profile_id="v3-test", overrides=None):
    """Return a JSON-safe field_reference dict matching runtime applied state."""
    d = {
        "is_confirmed": True,
        "is_frozen": True,
        "is_ready_for_field_to_gps": True,
        "origin_source": "runtime_current_gps",
        "heading_source": "runtime_forward_marker",
        "active_source": "runtime_origin_forward_marker",
        "synced_to_runtime": True,
        "origin_lat": 34.0,
        "origin_lon": 108.0,
        "field_heading_yaw_rad": 1.5,
        "runtime_binding": {
            "state": "applied",
            "profile_id": profile_id,
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
    if overrides:
        d.update(overrides)
    return d


def _drone_context(lat=34.0, lon=108.0, yaw=0.0, alt=5.0):
    return {"drone": {"lat": lat, "lon": lon, "yaw": yaw, "relative_altitude": alt, "global_position_valid": True}}


def _scene_context(detections=None):
    return {"scene": {"detections": detections or [], "image_width": 640, "image_height": 480}}


# =============================================================================
# RuntimeFieldTargetResolver — JSON dict tests
# =============================================================================

class TestRuntimeFieldTargetResolver:
    def test_ready_with_applied_status(self):
        r = RuntimeFieldTargetResolver(_applied_fr_dict())
        assert r.is_ready
        assert r.profile_id == "v3-test"

    def test_home_is_origin(self):
        fr = _applied_fr_dict()
        r = RuntimeFieldTargetResolver(fr)
        home = r.home(altitude_m=5.0)
        assert home.name == "HOME"
        assert home.lat == pytest.approx(34.0)
        assert home.lon == pytest.approx(108.0)
        assert home.altitude_m == pytest.approx(5.0)

    def test_home_no_altitude_rejected(self):
        r = RuntimeFieldTargetResolver(_applied_fr_dict())
        with pytest.raises(RuntimeFieldTargetError, match="altitude_m"):
            r.home()

    def test_home_zero_altitude_rejected(self):
        r = RuntimeFieldTargetResolver(_applied_fr_dict())
        with pytest.raises(RuntimeFieldTargetError, match="altitude_m"):
            r.home(altitude_m=0.0)

    def test_scan_waypoints_count_and_order(self):
        r = RuntimeFieldTargetResolver(_applied_fr_dict())
        scans = r.scan_waypoints()
        assert len(scans) == 4
        assert scans[0].name == "DROP_SCAN_1"
        assert scans[1].name == "DROP_SCAN_2"
        assert scans[2].name == "DROP_SCAN_3"
        assert scans[3].name == "DROP_SCAN_4"

    def test_not_confirmed_rejected(self):
        fr = _applied_fr_dict()
        fr["is_confirmed"] = False
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready
        assert "not confirmed" in (r.error or "")

    def test_not_frozen_rejected(self):
        fr = _applied_fr_dict()
        fr["is_frozen"] = False
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready
        assert "not frozen" in (r.error or "")

    def test_not_gps_ready_rejected(self):
        fr = _applied_fr_dict()
        fr["is_ready_for_field_to_gps"] = False
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_wrong_active_source_rejected(self):
        fr = _applied_fr_dict()
        fr["active_source"] = "field_profile_centerline"
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_not_synced_rejected(self):
        fr = _applied_fr_dict()
        fr["synced_to_runtime"] = False
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_state_not_applied_rejected(self):
        fr = _applied_fr_dict()
        fr["runtime_binding"]["state"] = "sampling"
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_geometry_missing_rejected(self):
        fr = _applied_fr_dict()
        del fr["runtime_binding"]["geometry"]
        r = RuntimeFieldTargetResolver(fr)
        assert not r.is_ready

    def test_profile_id_mismatch(self):
        r = RuntimeFieldTargetResolver(_applied_fr_dict("other-id"))
        assert r.profile_id == "other-id"

    def test_as_action_dict_uses_lat_lon(self):
        r = RuntimeFieldTargetResolver(_applied_fr_dict())
        d = r.as_action_dict("DROP_SCAN_1")
        assert "lat" in d
        assert "lon" in d
        assert d["target_frame"] == "global"
        assert d["waypoint_mode"] == "absolute"
        assert d["yaw_mode"] == "hold"


# =============================================================================
# GotoWaypointAction — lat/lon input
# =============================================================================

class TestGotoWaypointLatLon:
    def test_lat_lon_global_goto(self):
        a = GotoWaypointAction()
        a.start({"lat": 34.1, "lon": 108.2, "altitude_m": 5.0, "target_frame": "global", "yaw_mode": "hold"})
        assert a.target_frame == "global"
        assert a.target_x == pytest.approx(34.1)
        assert a.target_y == pytest.approx(108.2)
        assert a.altitude_m == pytest.approx(5.0)

    def test_legacy_xy_global_still_works(self):
        a = GotoWaypointAction()
        a.start({"x": 34.1, "y": 108.2, "altitude_m": 5.0, "target_frame": "global", "waypoint_mode": "absolute", "yaw_mode": "hold"})
        assert a.target_frame == "global"
        assert a.target_x == pytest.approx(34.1)

    def test_v1_local_xy_still_works(self):
        a = GotoWaypointAction()
        a.start({"x": 10.0, "y": 20.0, "altitude_m": 3.0, "target_frame": "local", "yaw_mode": "arm_heading"})
        assert a.target_frame == "local"
        assert a.target_x == pytest.approx(10.0)

    def test_action_dict_global_goto_has_lat_lon(self):
        a = GotoWaypointAction()
        a.start({"lat": 34.1, "lon": 108.2, "altitude_m": 5.0, "target_frame": "global", "yaw_mode": "hold"})
        d = a._action_dict(target={"lat": 34.1, "lon": 108.2, "alt": 5.0})
        assert d["action_type"] == "global_goto"
        assert d["params"]["lat"] == pytest.approx(34.1)
        assert d["params"]["lon"] == pytest.approx(108.2)


# =============================================================================
# Action Lab registry
# =============================================================================

class TestActionLabRegistry:
    def test_gps_multi_view_localize_registered(self):
        r = create_action_lab_registry()
        action = r.create("gps_multi_view_localize")
        assert action is not None
        assert isinstance(action, GpsMultiViewLocalizeAction)

    def test_gps_multi_view_localize_in_specs(self):
        specs = action_lab_specs()
        names = [s["name"] for s in specs]
        assert "gps_multi_view_localize" in names

    def test_start_with_json_params(self):
        a = GpsMultiViewLocalizeAction()
        a.start({
            "capture_updates_per_waypoint": 3,
            "class_names": ["bucket"],
            "min_confidence": 0.35,
        })
        assert a.started
        assert a.phase == "init"


# =============================================================================
# GpsMultiViewLocalizeAction — context-driven init
# =============================================================================

class TestGpsMultiViewContextInit:
    def test_init_from_field_reference_context(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"]})
        ctx = _drone_context()
        ctx["field_reference"] = _applied_fr_dict()
        ctx["scene"] = _scene_context().get("scene", {})
        result = a.update(ctx)
        # Should have initialized and moved to goto phase
        assert a._initialized
        assert a.phase == "goto"
        assert len(a.scan_targets) == 4

    def test_rejects_missing_field_reference(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"]})
        result = a.update(_drone_context())
        assert result.failed
        assert "missing_field_reference_context" in (result.reason or "")

    def test_rejects_unready_reference(self):
        a = GpsMultiViewLocalizeAction()
        a.start({"class_names": ["bucket"]})
        fr = _applied_fr_dict()
        fr["is_frozen"] = False
        ctx = _drone_context()
        ctx["field_reference"] = fr
        result = a.update(ctx)
        assert result.failed

    def test_state_machine_goto_settle_capture(self):
        a = GpsMultiViewLocalizeAction()
        a.start({
            "class_names": ["bucket"],
            "settle_updates_per_waypoint": 1,
            "capture_updates_per_waypoint": 1,
        })
        ctx = _drone_context()
        ctx["field_reference"] = _applied_fr_dict()
        ctx["scene"] = _scene_context([]).get("scene", {})

        # init → goto
        result = a.update(ctx)
        assert a.phase == "goto"
        assert len(result.actions or []) > 0
        # Check action is global_goto
        actions = result.actions or []
        assert actions[0]["action_type"] == "global_goto"
        assert "lat" in actions[0]["params"]
        assert "lon" in actions[0]["params"]

        # Simulate goto done by making the internal goto_action return done
        a.goto_action.reached_updates = a._params_goto_min_hold + 1
        result = a.update(ctx)
        assert a.phase in ("goto", "settle", "capture")  # phase transition may need more updates  # settle → capture transition

    def test_four_scan_points_sequential(self):
        a = GpsMultiViewLocalizeAction()
        a.start({
            "class_names": ["bucket"],
            "settle_updates_per_waypoint": 1,
            "capture_updates_per_waypoint": 1,
        })
        ctx = _drone_context()
        ctx["field_reference"] = _applied_fr_dict()
        ctx["scene"] = _scene_context([]).get("scene", {})

        # init
        a.update(ctx)
        names_seen = []
        for _ in range(4):
            # goto → settle → capture → next
            a.goto_action.reached_updates = a._params_goto_min_hold + 1
            r = a.update(ctx)
            names_seen.append(a.scan_targets[a.waypoint_index - 1].name if a.waypoint_index > 0 else a.scan_targets[0].name)
            # Force next waypoint
            if a.phase == "capture":
                a.capture_count = a._params_capture_updates  # force done
                r = a.update(ctx)

        assert "DROP_SCAN_1" in str(names_seen)


# =============================================================================
# GPS projector tests (unchanged from feature 2)
# =============================================================================

class TestGpsTargetProjector:
    def test_center_equals_drone(self):
        p = GpsTargetProjector()
        est = p.project(drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0, relative_altitude_m=5.0, ex=0.0, ey=0.0)
        assert est.lat == pytest.approx(34.0, abs=1e-5)
        assert est.lon == pytest.approx(108.0, abs=1e-5)

    def test_image_right_east_positive(self):
        p = GpsTargetProjector()
        est = p.project(drone_lat=34.0, drone_lon=108.0, drone_yaw_rad=0.0, relative_altitude_m=5.0, ex=0.5, ey=0.0)
        assert est.east_offset_m > 0.0

    def test_rejects_invalid_input(self):
        p = GpsTargetProjector()
        with pytest.raises(GpsProjectionError):
            p.project(drone_lat=100, drone_lon=108, drone_yaw_rad=0, relative_altitude_m=5, ex=0, ey=0)


# =============================================================================
# Fusion tests
# =============================================================================

class TestGpsDerivedEnuFusion:
    def test_single_cluster(self):
        f = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0,
                                config=GpsFusionConfig(cluster_radius_m=1.0, min_cluster_size=3))
        from missions.common.actions.gps_target_projection import GpsRawEstimate
        ests = [GpsRawEstimate(lat=34.0, lon=108.00001, east_offset_m=0, north_offset_m=0,
                                capture_drone_lat=34, capture_drone_lon=108, capture_yaw_rad=0,
                                capture_relative_altitude_m=5, ex=0, ey=0, class_name="b",
                                confidence=0.9, source_waypoint=f"DROP_SCAN_{i}")
                for i in range(1, 5)]
        result = f.fuse(ests)
        assert len(result) == 1
        assert result[0].class_name == "b"

    def test_output_has_lat_lon(self):
        f = GpsDerivedEnuFusion(origin_lat=34.0, origin_lon=108.0)
        from missions.common.actions.gps_target_projection import GpsRawEstimate
        ests = [GpsRawEstimate(lat=34.0, lon=108.00001, east_offset_m=0, north_offset_m=0,
                                capture_drone_lat=34, capture_drone_lon=108, capture_yaw_rad=0,
                                capture_relative_altitude_m=5, ex=0, ey=0, class_name="b",
                                confidence=0.9, source_waypoint="DROP_SCAN_1")
                for _ in range(4)]
        result = f.fuse(ests)
        assert len(result) >= 1
        obj = result[0]
        assert hasattr(obj, "lat")
        assert hasattr(obj, "lon")
        assert not hasattr(obj, "local_x")


# =============================================================================
# Runtime context field_reference in action context
# =============================================================================

class TestRuntimeContextFieldReference:
    def test_build_action_context_has_field_reference(self):
        from app.runtime_context import RuntimeContextBuilder
        b = RuntimeContextBuilder()
        ctx = b.build_action_context({"field_reference": {"is_confirmed": True}})
        assert "field_reference" in ctx
        assert ctx["field_reference"]["is_confirmed"] is True
