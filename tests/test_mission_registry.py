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


def test_rescue_competition_receives_mission_settings(tmp_path) -> None:
    mission_path = tmp_path / "rescue.yaml"
    mission_path.write_text(
        yaml.safe_dump(
            {
                "name": "rescue_competition",
                "initial_stage": "DONE",
                "idle_mode": "CORRIDOR_FOLLOW",
                "drop_route_end_name": "route_1",
                "recce_route_end_name": "route_1",
                "home_route_end_name": "route_1",
                "dry_run_skip_vision": True,
                "dry_run_skip_payload_release": True,
                "recce": {
                    "cylinder_classes": ["cylinder"],
                    "hazard_classes": ["flammable"],
                    "scan_duration_s": 6.0,
                    "output_dir": str(tmp_path / "recce"),
                    "output_json": True,
                    "output_csv": False,
                },
                "route": [{"x": 1.0, "y": 2.0, "z": -3.0}],
                "drop_zones": [{"x": 4.0, "y": 5.0, "radius_m": 1.5}],
                "payloads": [{"payload_id": 1}],
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
    assert mission.config.initial_stage == RescueStage.DONE
    assert mission.config.idle_mode == "CORRIDOR_FOLLOW"
    assert mission.config.drop_route_end_name == "route_1"
    assert mission.config.dry_run_skip_vision is True
    assert mission.config.dry_run_skip_payload_release is True
    assert mission.config.recce.config.cylinder_classes == {"cylinder"}
    assert mission.config.recce.config.hazard_classes == {"flammable"}
    assert mission.config.recce.scan_duration_s == 6.0
    assert mission.config.recce.output_csv is False
    assert len(mission.config.route) == 1
    assert len(mission.config.drop_zones) == 1
    assert len(mission.config.payloads) == 1
