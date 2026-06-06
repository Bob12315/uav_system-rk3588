from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner
from web_ui.server import create_app


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
    assert snapshot["action_lab"]["enabled"] is True
    assert snapshot["action_lab"]["send_actions"] is False
    assert snapshot["action_lab"]["requested_send_actions"] is False
    assert snapshot["action_lab"]["dry_run_only"] is True


def test_action_lab_api_status_reports_dry_run_only():
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    app = create_app(runner, config.ui)
    route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/status")

    response = route.endpoint()

    assert response["ok"] is True
    assert response["action_lab"]["enabled"] is True
    assert response["action_lab"]["send_actions"] is False
    assert response["action_lab"]["requested_send_actions"] is False
    assert response["action_lab"]["dry_run_only"] is True
