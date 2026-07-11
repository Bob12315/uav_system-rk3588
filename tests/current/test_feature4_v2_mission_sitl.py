"""Automated GPS-first V2 mission harness; no Gazebo/SITL result is claimed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.app_config import build_arg_parser, load_app_config
from app.mission_orchestrator import MissionActionStep, MissionBlackboard, MissionOrchestrator
from app.system_runner import SystemRunner
from missions.common.actions import gps_drop_sequence as sequence_module
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.select_drop_targets import SelectDropTargetsAction
from tests.current import test_feature3_gps_drop_control as feature3


ROOT = Path(__file__).resolve().parents[2]
V2_PATH = ROOT / "config/action_missions/drop_two_targets_v2.json"


def _v2_steps() -> list[MissionActionStep]:
    data = json.loads(V2_PATH.read_text(encoding="utf-8"))
    return [
        MissionActionStep(
            name=step["name"],
            params=dict(step.get("params") or {}),
            save_as=step.get("save_as"),
            label=step.get("label"),
            on_failed=step.get("on_failed"),
        )
        for step in data["steps"]
    ]


def _fused_objects(count: int = 2) -> list[dict[str, Any]]:
    objects = [
        {"id": "fused-a", "class_name": "bucket_1", "lat": 34.0001, "lon": 108.0001,
         "east_m": 1.2, "north_m": 2.3, "sample_count": 4, "raw_count": 4},
        {"id": "fused-b", "class_name": "bucket_2", "lat": 34.0003, "lon": 108.0004,
         "east_m": 3.4, "north_m": 4.5, "sample_count": 3, "raw_count": 3},
    ]
    return objects[:count]


def test_blackboard_select_to_gps_drop_sequence_data_flow() -> None:
    blackboard = MissionBlackboard()
    blackboard.set("drop_scan", {"localized_objects": _fused_objects()})
    select_params = blackboard.resolve({
        "objects": "$drop_scan.localized_objects",
        "coordinate_mode": "gps_enu",
        "target_count": 2,
        "min_seen_count": 2,
        "min_raw_count": 2,
    })
    select = SelectDropTargetsAction()
    select.start(select_params)
    selected = select.update({})
    assert selected.done is True
    blackboard.set("drop_targets", selected.detail)
    targets = blackboard.resolve("$drop_targets.target_slots")

    target_ids = [target["target_id"] for target in targets]
    assert target_ids == ["fused-a", "fused-b"]
    assert len(set(target_ids)) == 2
    assert [(item["lat"], item["lon"]) for item in targets] == [(34.0001, 108.0001), (34.0003, 108.0004)]
    assert [(item["east_m"], item["north_m"]) for item in targets] == [(1.2, 2.3), (3.4, 4.5)]
    assert [(item["east_m"], item["north_m"]) for item in selected.detail["selected_targets"]] == [(1.2, 2.3), (3.4, 4.5)]

    sequence = GpsDropSequenceAction()
    sequence.start({
        "targets": targets,
        "payloads": feature3.PAYLOADS,
    })
    assert [target["target_id"] for target in sequence.targets] == target_ids


def _make_runner() -> SystemRunner:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    return SystemRunner(load_app_config(args))


def _set_gps_reference(
    runner: SystemRunner,
    *,
    confirmed: bool = True,
    frozen: bool = True,
    ready: bool = True,
    synced: bool = True,
) -> None:
    reference = runner.field_reference_service.reference
    reference.is_confirmed = confirmed
    reference.is_frozen = frozen
    reference.origin_lat = 34.0 if ready else None
    reference.origin_lon = 108.0 if ready else None
    reference.field_heading_yaw_rad = 0.25 if ready else None
    builder = runner.runtime_context_builder
    builder.field_heading_confirmed = synced
    builder.field_origin_gps_confirmed = synced
    builder.field_heading_yaw_rad = 0.25 if synced else None
    builder.field_origin_lat = 34.0 if synced else None
    builder.field_origin_lon = 108.0 if synced else None
    builder.field_origin_confirmed = False
    builder.field_origin_local_x = None
    builder.field_origin_local_y = None
    builder.field_origin_local_z = None


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ({"confirmed": False}, "field_gps_reference_not_confirmed"),
        ({"frozen": False}, "field_gps_reference_not_frozen"),
        ({"ready": False}, "field_gps_reference_not_ready"),
        ({"synced": False}, "field_gps_reference_not_synced"),
    ],
)
def test_gps_mission_preflight_rejections_do_not_start_takeoff(setup, reason) -> None:
    runner = _make_runner()
    runner.configure_action_mission(_v2_steps())
    _set_gps_reference(runner, **setup)

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["failed"] is True
    assert payload["reason"] == reason
    assert runner.action_runtime.action_name is None
    assert runner.action_runtime.dispatcher.last_dispatch["sent"] == []


def test_gps_mission_preflight_rejects_service_builder_origin_mismatch() -> None:
    runner = _make_runner()
    runner.configure_action_mission(_v2_steps())
    _set_gps_reference(runner)
    runner.runtime_context_builder.field_origin_lat = 34.01

    payload = runner.action_mission_start()

    assert payload["reason"] == "field_gps_reference_not_synced"
    assert runner.action_runtime.action_name is None


def test_gps_only_mission_starts_without_local_origin() -> None:
    runner = _make_runner()
    runner.configure_action_mission(_v2_steps())
    _set_gps_reference(runner)

    assert runner._action_mission_field_requirements() == {"needs_gps": True, "needs_local": False}
    payload = runner.action_mission_start()

    assert payload["running"] is True
    assert runner.action_runtime.action_name == "takeoff"


def test_local_field_mission_still_rejects_missing_local_origin() -> None:
    runner = _make_runner()
    runner.configure_action_mission([
        MissionActionStep("goto_waypoint", {
            "x": 0.0, "y": 1.0, "altitude_m": 3.0,
            "waypoint_mode": "field", "target_frame": "local",
        })
    ])
    _set_gps_reference(runner)

    assert runner._action_mission_field_requirements() == {"needs_gps": False, "needs_local": True}
    payload = runner.action_mission_start()
    assert payload["reason"] == "field_reference_not_ready"


class ControlledMissionRuntime:
    def __init__(self, failures: dict[str, list[str]] | None = None, scan_count: int = 2) -> None:
        self.failures = {name: list(reasons) for name, reasons in (failures or {}).items()}
        self.scan_count = scan_count
        self.current_name: str | None = None
        self.current_params: dict[str, Any] = {}
        self.last_result: dict[str, Any] | None = None
        self.timeline: list[str] = []
        self.started_params: list[tuple[str, dict[str, Any]]] = []
        self.servo_count = 0

    def start(self, name, params, **kwargs):
        self.current_name = name
        self.current_params = dict(params)
        self.timeline.append(name)
        self.started_params.append((name, dict(params)))

    def tick(self, context, **kwargs):
        name = self.current_name or ""
        planned = self.failures.get(name, [])
        if planned:
            reason = planned.pop(0)
            self.last_result = {"failed": True, "done": False, "reason": reason, "detail": {}}
            return {}
        if name == "gps_multi_view_localize":
            detail = {"localized_objects": _fused_objects(self.scan_count)}
        elif name == "select_drop_targets":
            action = SelectDropTargetsAction()
            action.start(self.current_params)
            self.last_result = action.update({}).to_dict()
            return {}
        elif name == "gps_drop_sequence":
            assert len(self.current_params["targets"]) in (1, 2)
            assert len(self.current_params["payloads"]) == 2
            detail = {"released_count": 2}
        else:
            detail = {}
        self.last_result = {"failed": False, "done": True, "reason": f"{name}_done", "detail": detail}
        return {}

    def clear_navigation_queue(self, *args, **kwargs):
        return None

    def reset(self, *args, **kwargs):
        return None


def _run_orchestrator(runtime: ControlledMissionRuntime, limit: int = 30):
    orchestrator = MissionOrchestrator(runtime, _v2_steps())
    orchestrator.start()
    for _ in range(limit):
        status = orchestrator.tick({})
        if status.done or status.failed:
            return orchestrator, status
    raise AssertionError("orchestrator did not terminate")


def test_v2_mission_orchestrator_happy_timeline_and_blackboard() -> None:
    runtime = ControlledMissionRuntime()
    orchestrator, status = _run_orchestrator(runtime)

    assert status.done is True
    assert status.reason == "mission_done"
    assert runtime.timeline == [
        "takeoff", "yaw_align", "gps_multi_view_localize", "select_drop_targets",
        "gps_drop_sequence", "goto_waypoint", "land",
    ]
    assert sorted(orchestrator.blackboard.data) == ["drop_scan", "drop_sequence", "drop_targets"]
    gps_params = next(params for name, params in runtime.started_params if name == "gps_drop_sequence")
    assert [target["target_id"] for target in gps_params["targets"]] == ["fused-a", "fused-b"]


def test_scan_failure_retries_then_succeeds() -> None:
    runtime = ControlledMissionRuntime({"gps_multi_view_localize": ["scan_failed"]})
    _, status = _run_orchestrator(runtime)
    assert status.done is True
    assert runtime.timeline.count("gps_multi_view_localize") == 2


def test_scan_second_failure_jumps_to_return_home() -> None:
    runtime = ControlledMissionRuntime({"gps_multi_view_localize": ["scan_failed", "scan_failed"]})
    _, status = _run_orchestrator(runtime)
    assert status.done is True
    assert runtime.timeline == [
        "takeoff", "yaw_align", "gps_multi_view_localize",
        "gps_multi_view_localize", "goto_waypoint", "land",
    ]


def test_select_insufficient_targets_no_longer_jumps_to_return_home() -> None:
    """With allow_fewer=true, 1 target now runs gps_drop_sequence instead of jumping."""
    runtime = ControlledMissionRuntime(scan_count=1)
    _, status = _run_orchestrator(runtime)
    assert status.done is True
    assert runtime.timeline[-2:] == ["goto_waypoint", "land"]
    assert "gps_drop_sequence" in runtime.timeline


@pytest.mark.parametrize("reason", ["no_lockable_drop_targets", "target_lost_timeout"])
def test_drop_failure_returns_home_without_servo(reason: str) -> None:
    runtime = ControlledMissionRuntime({"gps_drop_sequence": [reason]})
    _, status = _run_orchestrator(runtime)
    assert status.done is True
    assert runtime.timeline[-2:] == ["goto_waypoint", "land"]
    assert runtime.servo_count == 0


def test_return_home_failure_jumps_to_land() -> None:
    runtime = ControlledMissionRuntime({"goto_waypoint": ["return_failed"]})
    _, status = _run_orchestrator(runtime)
    assert status.done is True
    assert runtime.timeline[-2:] == ["goto_waypoint", "land"]


def test_sitl_harness_gps_drop_action_frame_pwm_statistics(monkeypatch: pytest.MonkeyPatch) -> None:
    feature3.ScriptedGoto.reset()
    feature3.ScriptedYaw.reset()
    feature3.ScriptedLock.reset()
    feature3.ScriptedAlign.reset()
    monkeypatch.setattr(sequence_module, "GotoWaypointAction", feature3.ScriptedGoto)
    monkeypatch.setattr(sequence_module, "YawAlignAction", feature3.ScriptedYaw)
    monkeypatch.setattr(sequence_module, "GpsTargetLockAction", feature3.ScriptedLock)
    monkeypatch.setattr(sequence_module, "AlignDescendAction", feature3.ScriptedAlign)
    action = GpsDropSequenceAction()
    action.start(feature3._params())
    results = feature3._drive_until_terminal(action)
    emitted = [item for result in results for item in result.actions]

    global_count = sum(item["action_type"] == "global_goto" for item in emitted)
    body_nonzero = sum(
        item["action_type"] == "flight_command"
        and any(abs(float(item["params"].get(name, 0.0))) > 0.0 for name in ("vx_cmd", "vy_cmd", "vz_cmd"))
        for item in emitted
    )
    servo_pwms = [item["params"]["pwm"] for item in emitted if item["action_type"] == "set_servo"]
    assert global_count > 0
    assert body_nonzero > 0
    assert sum(pwm in {1200, 1250} for pwm in servo_pwms) == 2
    assert sum(pwm in {1700, 1750} for pwm in servo_pwms) == 2
    assert sum(item["action_type"] == "local_position" for item in emitted) == 0
