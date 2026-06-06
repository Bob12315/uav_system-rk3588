from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner


def test_app_config_falls_back_when_legacy_missions_are_unavailable():
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])

    config = load_app_config(args)

    assert config.mission_enabled is False
    assert config.mission_name == "action_lab_only"
    assert config.mission_config_path is None


def test_system_runner_snapshot_works_without_mission_runtime():
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)

    runner = SystemRunner(config)
    snapshot = runner.web_status_snapshot()

    assert snapshot["mission"] == "action_lab_only"
    assert snapshot["stage"] == "NO_MISSION"
    assert snapshot["stage_modes"] == ["NO_MISSION"]
    assert snapshot["mission_stage_selection"] == "NO_MISSION"
    assert snapshot["actions"] == []
