from __future__ import annotations

import pytest
import yaml

from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner
from missions.registry import available_mission_names, build_mission
from missions.rescue_competition import RescueCompetitionMission, RescueStage
from missions.visual_tracking import VisualTrackingMission


def _config():
    args = build_arg_parser().parse_args(
        ["--no-yolo-udp", "--no-ui", "--run-seconds", "1", "--send-commands", "false"]
    )
    return load_app_config(args)


def test_build_mission_defaults_to_visual_tracking() -> None:
    assert isinstance(build_mission("", _config()), VisualTrackingMission)
    assert isinstance(build_mission("visual_tracking", _config()), VisualTrackingMission)


def test_available_mission_names_include_ui_switch_targets() -> None:
    assert available_mission_names() == ("visual_tracking", "rescue_competition")


def test_build_mission_can_construct_rescue_competition_skeleton() -> None:
    mission = build_mission("rescue_competition", _config())

    assert isinstance(mission, RescueCompetitionMission)
    assert mission.name == "rescue_competition"


def test_build_mission_rejects_unknown_name() -> None:
    with pytest.raises(KeyError):
        build_mission("unknown", _config())


def test_system_runner_uses_configured_mission_name() -> None:
    args = build_arg_parser().parse_args(
        [
            "--no-yolo-udp",
            "--no-ui",
            "--run-seconds",
            "1",
            "--send-commands",
            "false",
            "--mission-name",
            "rescue_competition",
        ]
    )
    config = load_app_config(args)

    runner = SystemRunner(config)

    assert isinstance(runner.mission_runner.mission, RescueCompetitionMission)


def test_system_runner_can_switch_mission_at_runtime() -> None:
    config = _config()
    runner = SystemRunner(config)
    runner.controller_switches.set_send_commands(True)

    result = runner._handle_mission_command(["switch", "rescue_competition"])

    assert result.ok
    assert "mission switched" in result.message
    assert isinstance(runner.mission_runner.mission, RescueCompetitionMission)
    assert runner.controller_switches.snapshot().send_commands is False
    assert runner.debug_runtime.config.force_mode is None


def test_system_runner_can_start_current_mission() -> None:
    config = _config()
    runner = SystemRunner(config)
    runner._switch_mission("rescue_competition")

    result = runner._handle_mission_command(["start"])

    assert result.ok
    assert "mission start requested" in result.message
    assert runner.mission_runner.mission._start_requested is True


def test_system_runner_tracks_selected_stage_for_each_mission() -> None:
    runner = SystemRunner(_config())

    visual = runner._handle_mission_command(["stage", "IDLE"])
    runner._switch_mission("rescue_competition")
    rescue = runner._handle_mission_command(["stage", "TAKEOFF"])

    assert visual.ok
    assert rescue.ok
    assert runner.mission_stage_selections == {
        "visual_tracking": "IDLE",
        "rescue_competition": "TAKEOFF",
    }
    assert runner.web_status_snapshot()["mission_stage_selection"] == "TAKEOFF"


def test_system_runner_mission_stage_auto_restores_generic_selection() -> None:
    runner = SystemRunner(_config())
    runner._handle_mission_command(["stage", "IDLE"])

    result = runner._handle_mission_command(["stage", "auto"])

    assert result.ok
    assert result.message == "mission stage auto"
    assert runner.mission_stage_selections["visual_tracking"] == "AUTO"


def test_web_missions_exposes_stage_buttons_for_every_registered_mission() -> None:
    runner = SystemRunner(_config())

    missions = {item["name"]: item for item in runner.web_missions()}

    assert missions["visual_tracking"]["stage_modes"] == [
        "IDLE",
        "APPROACH_TRACK",
        "OVERHEAD_HOLD",
        "CORRIDOR_FOLLOW",
    ]
    assert "TAKEOFF" in missions["rescue_competition"]["stage_modes"]
    assert "SURVEY_DROP_POINTS" in missions["rescue_competition"]["stage_modes"]
    assert missions["visual_tracking"]["selected_stage"] == "AUTO"
    assert missions["rescue_competition"]["selected_stage"] == "AUTO"


def test_rescue_competition_receives_mission_settings(tmp_path) -> None:
    mission_path = tmp_path / "rescue.yaml"
    mission_path.write_text(
        yaml.safe_dump(
            {
                "name": "rescue_competition",
                "initial_stage": "FINISH",
                "idle_mode": "CORRIDOR_FOLLOW",
                "recce": {
                    "capture_hold_s": 2.5,
                    "output_dir": str(tmp_path / "recce"),
                },
                "vision": {
                    "cylinder_classes": ["cylinder"],
                    "hazard_classes": ["flammable"],
                },
                "route": {
                    "home": {"x": 1.0, "y": 2.0},
                    "drop_area_center": {"x": 30.0, "y": 0.0},
                    "recce_area_center": {"x": 55.0, "y": 0.0},
                },
                "payload_slots": [{"id": 1, "servo_channel": 8}],
            }
        ),
        encoding="utf-8",
    )
    args = build_arg_parser().parse_args(
        [
            "--no-yolo-udp",
            "--no-ui",
            "--run-seconds",
            "1",
            "--send-commands",
            "false",
            "--mission-config",
            str(mission_path),
        ]
    )
    config = load_app_config(args)

    mission = build_mission(config.mission_name, config)

    assert isinstance(mission, RescueCompetitionMission)
    assert mission.config.initial_stage == RescueStage.FINISH
    assert mission.config.idle_mode == "CORRIDOR_FOLLOW"
    assert mission.config.route.home_x == pytest.approx(1.0)
    assert mission.config.route.home_y == pytest.approx(2.0)
    assert mission.config.vision.cylinder_classes == {"cylinder"}
    assert mission.config.vision.hazard_classes == {"flammable"}
    assert mission.config.recce.capture_hold_s == pytest.approx(2.5)
    assert mission.config.recce.output_dir == str(tmp_path / "recce")
    assert len(mission.config.payload_slots) == 1
    assert mission.config.payload_slots[0].servo_channel == 8
