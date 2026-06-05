from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.stage_registry import StageRegistry
from app.app_config import build_arg_parser, load_app_config, load_telemetry_config
from telemetry_link.config import DEFAULT_CONFIG_PATH, load_config_file
from missions.visual_tracking.stages.approach_track.config import (
    ApproachBodyConfig,
    ApproachTrackConfig,
)
from missions.visual_tracking.stages.overhead_hold.config import (
    OverheadBodyConfig,
    OverheadHoldConfig,
)


def test_loads_mission_local_config_layout() -> None:
    args = build_arg_parser().parse_args(
        ["--no-yolo-udp", "--no-ui", "--run-seconds", "1", "--send-commands", "false"]
    )

    config = load_app_config(args)

    assert config.runtime.ui_enabled is False
    assert config.ui.web_enabled is False
    assert config.runtime.connect_telemetry is True
    assert config.blackbox.enabled is True
    assert config.blackbox.sample_hz == pytest.approx(20.0)
    assert config.approach_track.approach.kp_vx == pytest.approx(4.0)
    assert config.approach_track.require_yaw_aligned_for_approach is False
    assert config.overhead_hold.gimbal.downward_pitch_rad == pytest.approx(
        -1.5707963267948966
    )
    assert config.overhead_hold.body.kp_vy == pytest.approx(3.0)
    assert config.overhead_hold.approach.kp_vx == pytest.approx(3.0)
    assert config.shaper.max_vx == pytest.approx(3.0)
    assert config.mission_name == "visual_tracking"
    assert config.mission_settings["name"] == "visual_tracking"
    assert Path(config.mission_config_path).name == "config.yaml"
    assert Path(config.mission_config_path).parent.name == "visual_tracking"
    assert config.visual_tracking.initial_mode == "OVERHEAD_HOLD"
    assert config.visual_tracking.overhead_entry_target_size_thresh == pytest.approx(10.0)
    assert config.health.max_vision_age_s == pytest.approx(0.3)
    assert config.health.max_drone_age_s == pytest.approx(0.3)
    assert config.health.max_gimbal_age_s == pytest.approx(0.3)
    assert config.runtime.lost_target_recenter_enabled is False


def test_loads_independent_web_and_terminal_ui_settings() -> None:
    args = build_arg_parser().parse_args(["--send-commands", "false"])

    config = load_app_config(args)

    assert config.ui.web_enabled is True
    assert config.ui.terminal_enabled is False
    assert config.ui.web_port == 8080


def test_app_reuses_telemetry_link_config_parser() -> None:
    assert load_telemetry_config(DEFAULT_CONFIG_PATH) == load_config_file(DEFAULT_CONFIG_PATH)


def test_app_help_does_not_expose_removed_control_config() -> None:
    assert "--control-config" not in build_arg_parser().format_help()


def test_mission_name_can_be_overridden_from_cli() -> None:
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

    assert config.mission_name == "rescue_competition"
    assert config.downward_align_descend.kp_vx == pytest.approx(0.8)
    assert config.downward_align_descend.kp_vy == pytest.approx(0.8)
    assert config.downward_align_descend.max_vx_mps == pytest.approx(0.4)
    assert config.downward_align_descend.max_vy_mps == pytest.approx(0.4)
    assert config.downward_align_descend.descend_speed_mps == pytest.approx(0.2)
    assert config.shaper.max_vx == pytest.approx(0.4)
    assert config.shaper.max_vy == pytest.approx(0.4)
    assert config.shaper.max_yaw_rate == pytest.approx(0.0)
    assert config.shaper.max_yaw_rate_rate == pytest.approx(0.0)


def test_mission_config_path_can_be_declared_in_app_config(tmp_path) -> None:
    mission_path = tmp_path / "visual_tracking.yaml"
    mission_path.write_text(
        yaml.safe_dump(
            {
                "name": "visual_tracking",
                "initial_mode": "IDLE",
                "auto_switch_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    app_path = tmp_path / "app.yaml"
    app_path.write_text(
        yaml.safe_dump(
            {
                "mission": {
                    "name": "visual_tracking",
                    "config_path": str(mission_path),
                },
                "services": {
                    "connect_telemetry": False,
                    "start_yolo_udp": False,
                    "ui_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    args = build_arg_parser().parse_args(
        [
            "--app-config",
            str(app_path),
            "--no-yolo-udp",
            "--no-ui",
            "--run-seconds",
            "1",
            "--send-commands",
            "false",
        ]
    )

    config = load_app_config(args)

    assert config.mission_config_path == str(mission_path)
    assert config.mission_name == "visual_tracking"
    assert config.visual_tracking.initial_mode == "IDLE"
    assert config.visual_tracking.auto_switch_enabled is False


def test_cli_mission_config_overrides_app_config_path(tmp_path) -> None:
    app_mission_path = tmp_path / "app_mission.yaml"
    cli_mission_path = tmp_path / "cli_mission.yaml"
    app_mission_path.write_text(
        yaml.safe_dump({"initial_mode": "IDLE"}),
        encoding="utf-8",
    )
    cli_mission_path.write_text(
        yaml.safe_dump({"initial_mode": "OVERHEAD_HOLD"}),
        encoding="utf-8",
    )
    app_path = tmp_path / "app.yaml"
    app_path.write_text(
        yaml.safe_dump(
            {
                "mission": {
                    "name": "visual_tracking",
                    "config_path": str(app_mission_path),
                },
                "services": {
                    "connect_telemetry": False,
                    "start_yolo_udp": False,
                    "ui_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    args = build_arg_parser().parse_args(
        [
            "--app-config",
            str(app_path),
            "--mission-config",
            str(cli_mission_path),
            "--no-yolo-udp",
            "--no-ui",
            "--run-seconds",
            "1",
            "--send-commands",
            "false",
        ]
    )

    config = load_app_config(args)

    assert config.mission_config_path == str(cli_mission_path)
    assert config.visual_tracking.initial_mode == "OVERHEAD_HOLD"


def test_stage_registry_runtime_config_update_preserves_controller_references() -> None:
    registry = StageRegistry(
        approach_config=ApproachTrackConfig(body=ApproachBodyConfig(kp_yaw=0.2)),
        overhead_config=OverheadHoldConfig(body=OverheadBodyConfig(kp_vy=1.0)),
    )
    overhead_mode = registry.get("OVERHEAD_HOLD")

    registry.apply_configs(
        approach_config=ApproachTrackConfig(body=ApproachBodyConfig(kp_yaw=0.7)),
        overhead_config=OverheadHoldConfig(body=OverheadBodyConfig(kp_vy=3.5)),
    )

    assert registry.approach_config.body.kp_yaw == pytest.approx(0.7)
    assert overhead_mode.body.config.kp_vy == pytest.approx(3.5)


def test_stage_registry_exposes_rescue_downward_align_descend() -> None:
    registry = StageRegistry(
        approach_config=ApproachTrackConfig(),
        overhead_config=OverheadHoldConfig(),
    )

    mode = registry.get("DOWNWARD_ALIGN_DESCEND")

    assert mode.name == "DOWNWARD_ALIGN_DESCEND"
