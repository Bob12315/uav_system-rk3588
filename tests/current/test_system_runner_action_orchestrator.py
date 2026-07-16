"""Tests for mission preflight gate and TakeoffAction centerline-only behavior."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.app_config import build_arg_parser, load_app_config
from app.field_profile import (
    AnchorPoint,
    BindingPolicy,
    CenterlinePoint,
    FieldGeometry,
    FieldProfile,
    GpsQualityThresholds,
)
from app.field_profile_service import FieldProfileService
from app.mission_orchestrator import MissionActionStep, MissionOrchestratorStatus
from app.system_runner import ACTION_MISSION_RECORDING_MAX_DURATION_S, SystemRunner
from missions.common.actions.takeoff import TakeoffAction


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_runner():
    """Build a minimal SystemRunner with no external services."""
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    return SystemRunner(config)


def _field_steps():
    """Return mission steps that use FIELD coordinates (triggers preflight)."""
    return [
        MissionActionStep(
            name="goto_waypoint",
            params={"waypoint_mode": "field", "x": 1.0, "y": 0.0, "altitude_m": 3.0},
        )
    ]


def _local_steps():
    """Return mission steps that do NOT use FIELD coordinates (no preflight)."""
    return [
        MissionActionStep(
            name="takeoff",
            params={"altitude_m": 3.0},
        )
    ]


def _make_profile():
    """Build a minimal valid centerline profile."""
    cl = [
        CenterlinePoint("CL_1", 34.000075, 108.0),
        CenterlinePoint("CL_2", 34.000150, 108.0),
        CenterlinePoint("CL_3", 34.000225, 108.0),
        CenterlinePoint("CL_4", 34.000300, 108.0),
    ]
    return FieldProfile(
        schema_version=2,
        profile_id="test_preflight",
        name="Test",
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


def _bind_and_sync_no_freeze(runner, profile=None, local_n=10.0, local_e=20.0, local_z=-1.0):
    """Run bind → apply → sync (no freeze)."""
    if profile is None:
        profile = _make_profile()

    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=profile.anchor.lat,
        current_lon=profile.anchor.lon,
        current_local_n_m=local_n,
        current_local_e_m=local_e,
        current_local_z_m=local_z,
        gps_fix_type=3,
        satellites_visible=12,
        gps_eph=1.0,
        gps_epv=1.0,
        timestamp=1000.0,
    )
    assert br.ok, f"bind failed: {br.errors}"

    applied = runner.field_reference_service.apply_profile_binding(
        bind_result=br,
        profile_id=profile.profile_id,
        profile_name=profile.name,
        anchor_lat=profile.anchor.lat,
        anchor_lon=profile.anchor.lon,
        timestamp=1000.0,
    )
    assert applied["ok"], f"apply failed: {applied.get('error')}"

    ref = runner.field_reference_service.reference
    ok = runner.runtime_context_builder.confirm_field_reference(
        field_heading_yaw_rad=ref.field_heading_yaw_rad,
        origin_local_x=ref.origin_local_n_m,
        origin_local_y=ref.origin_local_e_m,
        origin_local_z=ref.origin_local_z_m,
        source=f"field_profile:{profile.profile_id}",
        timestamp=1000.0,
    )
    assert ok, "sync to RuntimeContext failed"


def _bind_centerline_and_sync(runner, profile=None, local_n=10.0, local_e=20.0, local_z=-1.0):
    """Run full bind → apply → sync → freeze on the runner's services."""
    _bind_and_sync_no_freeze(runner, profile=profile, local_n=local_n, local_e=local_e, local_z=local_z)

    frozen = runner.field_reference_service.freeze()
    assert frozen["ok"], f"freeze failed: {frozen.get('error')}"


# ---------------------------------------------------------------------------
# preflight gate — rejection cases
# ---------------------------------------------------------------------------


def test_field_mission_rejects_unconfirmed_reference():
    """Mission with FIELD waypoints rejects start when reference is unconfirmed."""
    runner = _make_runner()
    runner.configure_action_mission(_field_steps())

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["failed"] is True
    assert payload["reason"] == "field_reference_not_confirmed"


def test_field_mission_rejects_unsynced_reference():
    """Mission rejects start when reference confirmed but not synced to RuntimeContext."""
    runner = _make_runner()
    runner.configure_action_mission(_field_steps())

    profile = _make_profile()
    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=profile.anchor.lat,
        current_lon=profile.anchor.lon,
        current_local_n_m=10.0,
        current_local_e_m=20.0,
        current_local_z_m=-1.0,
        gps_fix_type=3,
        satellites_visible=12,
        gps_eph=1.0,
        gps_epv=1.0,
        timestamp=1000.0,
    )
    runner.field_reference_service.apply_profile_binding(
        bind_result=br,
        profile_id=profile.profile_id,
        profile_name=profile.name,
        anchor_lat=profile.anchor.lat,
        anchor_lon=profile.anchor.lon,
        timestamp=1000.0,
    )
    # Intentionally do NOT call confirm_field_reference (not synced)

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_not_synced"


def test_field_mission_rejects_not_frozen():
    """Mission rejects when reference is confirmed + synced but not frozen."""
    runner = _make_runner()
    runner.configure_action_mission(_field_steps())
    _bind_and_sync_no_freeze(runner)

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_not_frozen"


def test_field_mission_rejects_mismatched_runtime_context():
    """Mission rejects when RuntimeContext values don't match FieldReference."""
    runner = _make_runner()
    runner.configure_action_mission(_field_steps())
    _bind_centerline_and_sync(runner)

    runner.runtime_context_builder.field_origin_local_x = (
        runner.runtime_context_builder.field_origin_local_x or 0.0
    ) + 0.01

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_not_synced"


# ---------------------------------------------------------------------------
# preflight gate — success case
# ---------------------------------------------------------------------------


def test_field_mission_starts_when_confirmed_synced_frozen():
    """Mission with FIELD waypoints starts successfully when all preflight checks pass."""
    runner = _make_runner()
    runner.configure_action_mission(_field_steps())
    _bind_centerline_and_sync(runner)

    payload = runner.action_mission_start()

    assert payload["running"] is True
    assert runner.field_reference_service.reference.is_frozen is True


# ---------------------------------------------------------------------------
# non-FIELD missions skip preflight
# ---------------------------------------------------------------------------


def test_non_field_mission_starts_without_field_reference():
    """Mission without FIELD waypoints starts even without field reference."""
    runner = _make_runner()
    runner.configure_action_mission(_local_steps())

    payload = runner.action_mission_start()

    assert payload["running"] is True


def test_mission_start_and_stop_control_camera_recording(monkeypatch):
    runner = _make_runner()
    runner.configure_action_mission(_local_steps())
    starts = []
    stops = []
    monkeypatch.setattr(
        runner.command_pipeline,
        "camera_recording_start",
        lambda *, trigger: starts.append(trigger) or SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(
        runner.command_pipeline,
        "camera_recording_stop",
        lambda *, trigger: stops.append(trigger) or SimpleNamespace(ok=True),
    )

    payload = runner.action_mission_start()
    assert payload["running"] is True
    assert starts == ["action_mission_start"]
    assert runner._action_mission_recording_requested is True
    assert runner._action_mission_recording_deadline_monotonic is not None

    runner.action_mission_stop()
    assert stops == ["action_mission_stop"]
    assert runner._action_mission_recording_requested is False
    assert runner._action_mission_recording_deadline_monotonic is None


@pytest.mark.parametrize(
    ("done", "failed", "reason"),
    [(True, False, "mission_done"), (False, True, "action_failed")],
)
def test_mission_completion_or_failure_stops_camera_recording(
    monkeypatch, done, failed, reason,
):
    runner = _make_runner()
    runner.configure_action_mission(_local_steps())
    stops = []
    monkeypatch.setattr(
        runner.command_pipeline,
        "camera_recording_start",
        lambda *, trigger: SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(
        runner.command_pipeline,
        "camera_recording_stop",
        lambda *, trigger: stops.append(trigger) or SimpleNamespace(ok=True),
    )
    runner.action_mission_start()
    orchestrator = runner.action_mission_orchestrator
    assert orchestrator is not None

    def terminal_tick(*args, **kwargs):
        orchestrator.running = False
        orchestrator.done = done
        orchestrator.failed = failed
        orchestrator.reason = reason
        return MissionOrchestratorStatus(
            running=False,
            done=done,
            failed=failed,
            current_index=0,
            current_action="takeoff",
            reason=reason,
            detail={},
        )

    monkeypatch.setattr(orchestrator, "tick", terminal_tick)
    runner.action_mission_tick()

    assert stops == [f"action_mission_{reason}"]
    assert runner._action_mission_recording_requested is False


def test_mission_recording_timeout_stops_after_600_seconds(monkeypatch):
    runner = _make_runner()
    stops = []
    monkeypatch.setattr(
        runner.command_pipeline,
        "camera_recording_stop",
        lambda *, trigger: stops.append(trigger) or SimpleNamespace(ok=True),
    )
    runner._action_mission_recording_requested = True
    runner._action_mission_recording_deadline_monotonic = 1000.0

    assert runner._enforce_action_mission_recording_timeout(now_monotonic=999.9) is False
    assert stops == []
    assert runner._enforce_action_mission_recording_timeout(now_monotonic=1000.0) is True
    assert stops == ["action_mission_10m_timeout"]
    assert ACTION_MISSION_RECORDING_MAX_DURATION_S == 600.0


# ---------------------------------------------------------------------------
# TakeoffAction — no auto-confirm
# ---------------------------------------------------------------------------


def test_takeoff_does_not_emit_confirm_field_heading():
    """TakeoffAction must not have a confirm_field_heading phase."""
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    assert action.phase == "set_mode"

    assert not hasattr(action, "auto_confirm_field_heading"), (
        "TakeoffAction must not have auto_confirm_field_heading parameter"
    )


def test_takeoff_set_mode_is_first_action():
    """First emitted action must be set_mode, not confirm_field_heading."""
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    result = action.update({})

    assert result.reason == "set_mode_sent"
    assert len(result.actions) == 1
    assert result.actions[0]["action_type"] == "set_mode"
    assert result.actions[0]["action_type"] != "confirm_field_heading"


def _live_ranking(confidence_sum: float = 0.0) -> list[dict[str, object]]:
    names = ["baozha", "shenghua", "yiran", "fangshe", "buran", "fushi", "youdu", "yushi", "ziran", "ciji"]
    return [
        {"rank": index + 1, "class_name": name, "seen_frames": 0,
         "confidence_sum": confidence_sum if index == 0 else 0.0,
         "confidence_mean": 0.0, "confidence_max": 0.0, "hit_ratio": 0.0}
        for index, name in enumerate(names)
    ]


def test_action_lab_live_recon_ranking_publishes_before_action_done():
    runner = _make_runner()
    runner.action_runtime.runner.action_name = "gps_recon_area_scan"
    runner.action_runtime.last_result = {
        "done": False, "detail": {"ranking_mode": True, "ranking": _live_ranking(), "scan_summary": {"scored_unique_frame_count": 0}},
    }

    runner.action_lab_tick()

    published = runner.latest_recon_inspection_result
    assert published["ranking_mode"] is True
    assert len(published["ranking"]) == 10
    assert published["scan_summary"]["scored_unique_frame_count"] == 0


def test_mission_recon_completion_keeps_ranking_after_next_action_switch():
    runner = _make_runner()
    result = {"done": True, "detail": {"ranking_mode": True, "ranking": _live_ranking(1.2), "scan_summary": {"scored_unique_frame_count": 2}}}

    assert runner._publish_recon_ranking_from_action_result(result, action_name="gps_recon_area_scan")
    # Simulate MissionOrchestrator immediately moving on to return_home_gps.
    assert not runner._publish_recon_ranking_from_action_result(result, action_name="goto_waypoint")
    published = runner.latest_recon_inspection_result
    assert published["ranking"][0]["confidence_sum"] == 1.2
    assert published["source"] == "gps_recon_area_scan"


def test_mission_start_and_reset_clear_live_recon_ranking():
    runner = _make_runner()
    runner.latest_recon_inspection_result = {"ranking_mode": True, "ranking": _live_ranking()}
    runner.configure_action_mission(_local_steps())
    runner.action_mission_start()
    assert runner.latest_recon_inspection_result == {}
    runner.latest_recon_inspection_result = {"ranking_mode": True, "ranking": _live_ranking()}
    runner.action_mission_reset()
    assert runner.latest_recon_inspection_result == {}
