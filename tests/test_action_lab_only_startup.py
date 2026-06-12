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
    # PR F: action_mission is not_configured by default
    assert snapshot["action_mission"]["enabled"] is False
    assert snapshot["action_mission"]["reason"] == "not_configured"


def test_action_mission_status_payload_not_configured_by_default() -> None:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    payload = runner.action_mission_status_payload()
    assert payload["enabled"] is False
    assert payload["running"] is False
    assert payload["done"] is False
    assert payload["failed"] is False
    assert payload["current_action"] is None
    assert payload["reason"] == "not_configured"


def test_configure_action_mission_sets_enabled() -> None:
    from app.mission_orchestrator import MissionActionStep

    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    steps = [MissionActionStep("goto_waypoint", {"x": 1.0})]
    runner.configure_action_mission(steps)

    payload = runner.action_mission_status_payload()
    assert payload["enabled"] is True
    assert payload["current_action"] == "goto_waypoint"
    assert runner.action_mission_orchestrator is not None


def test_action_mission_tick_does_not_call_when_not_configured() -> None:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    result = runner.action_mission_tick()
    assert result["enabled"] is False
    assert result["running"] is False


def test_action_mission_start_stop_reset_lifecycle() -> None:
    from app.mission_orchestrator import MissionActionStep

    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    runner.configure_action_mission([MissionActionStep("goto_waypoint", {"x": 1.0})])

    started = runner.action_mission_start()
    assert started["enabled"] is True
    assert started["running"] is True

    stopped = runner.action_mission_stop()
    assert stopped["running"] is False
    assert stopped["reason"] == "stopped"

    reset = runner.action_mission_reset()
    assert reset["running"] is False
    assert reset["reason"] == "reset"


def test_action_mission_web_api_lifecycle() -> None:
    from web_ui.server import ActionMissionConfigureRequest, ActionMissionStepRequest

    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    app = create_app(runner, config.ui)

    def endpoint(path: str):
        return next(route.endpoint for route in app.routes if getattr(route, "path", "") == path)

    status = endpoint("/api/action-mission/status")()
    assert status["ok"] is True
    assert status["action_mission"]["reason"] == "not_configured"

    configured = endpoint("/api/action-mission/configure")(
        ActionMissionConfigureRequest(
            steps=[
                ActionMissionStepRequest(name="goto_waypoint", params={"x": 1.0}),
            ],
        )
    )
    assert configured["ok"] is True
    assert configured["action_mission"]["enabled"] is True

    started = endpoint("/api/action-mission/start")()
    assert started["action_mission"]["running"] is True

    stopped = endpoint("/api/action-mission/stop")()
    assert stopped["action_mission"]["running"] is False

    reset = endpoint("/api/action-mission/reset")()
    assert reset["action_mission"]["reason"] == "reset"

    runner.action_mission_orchestrator = None
    tick = endpoint("/api/action-mission/tick")()
    assert tick["ok"] is True
    assert tick["action_mission"]["reason"] == "not_configured"


def test_action_mission_step_request_accepts_save_as() -> None:
    from web_ui.server import ActionMissionStepRequest

    request = ActionMissionStepRequest(name="multi_view_localize", params={}, save_as="drop_scan")

    assert request.save_as == "drop_scan"


def test_action_mission_step_request_accepts_label_and_on_failed() -> None:
    from web_ui.server import ActionMissionStepRequest

    request = ActionMissionStepRequest(
        name="target_lock",
        label="lock0",
        on_failed={"action": "retry_current", "max_attempts": 2},
    )

    assert request.label == "lock0"
    assert request.on_failed == {"action": "retry_current", "max_attempts": 2}


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
