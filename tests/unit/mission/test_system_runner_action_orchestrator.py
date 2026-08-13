"""Action Mission preflight tests using the schema-v3 runtime reference."""
from __future__ import annotations

from app.config import build_arg_parser, load_app_config
from missions.engine import MissionActionStep
from application.runner import SystemRunner


def _runner() -> SystemRunner:
    return SystemRunner(load_app_config(build_arg_parser().parse_args(["--no-yolo-udp", "--no-ui"])))


def _field_steps() -> list[MissionActionStep]:
    return [MissionActionStep("goto_waypoint", {"waypoint_mode": "field", "x": 1.0, "y": 32.5, "altitude_m": 3.0})]


def test_field_action_mission_rejects_unconfirmed_runtime_reference() -> None:
    runner = _runner()
    runner.configure_action_mission(_field_steps())
    result = runner.action_mission_start(authorize=True, target_source="sitl")
    assert result["failed"] is True
    assert result["reason"] == "field_gps_reference_not_confirmed"


def test_nonfield_action_mission_does_not_need_field_reference() -> None:
    runner = _runner()
    runner.configure_action_mission([MissionActionStep("takeoff", {"altitude_m": 3.0})])
    result = runner.action_mission_start(authorize=True, target_source="sitl")
    assert result["running"] is True
