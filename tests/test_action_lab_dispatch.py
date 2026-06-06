from __future__ import annotations

from dataclasses import dataclass, field

from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner
from web_ui.server import ActionStartRequest, create_app


@dataclass(slots=True)
class FakeLink:
    calls: list[tuple[str, tuple[object, ...], int]] = field(default_factory=list)
    fail: bool = False

    def set_servo(self, channel: int, pwm: int, priority: int = 3) -> None:
        if self.fail:
            raise RuntimeError("servo failed")
        self.calls.append(("set_servo", (channel, pwm), priority))

    def local_position(
        self,
        x: float,
        y: float,
        z: float,
        frame: int,
        yaw: float | None = None,
        priority: int = 4,
    ) -> None:
        if self.fail:
            raise RuntimeError("local position failed")
        self.calls.append(("local_position", (x, y, z, frame, yaw), priority))

    def send_velocity_command(self, vx: float, vy: float, vz: float, frame: int = 1) -> None:
        if self.fail:
            raise RuntimeError("velocity failed")
        self.calls.append(("send_velocity_command", (vx, vy, vz, frame), 0))


def _runner() -> SystemRunner:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    runner.services.link_manager = FakeLink()
    return runner


def _payload_params(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "servo_outputs": [
            {"channel": 8, "release_pwm": 1200, "hold_pwm": 1700},
        ],
        "payload_id": "payload_1",
        "target_id": "target_a",
        "release_wait_updates": 5,
        "priority": 3,
    }
    data.update(overrides)
    return data


def _goto_params(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "x": 1.0,
        "y": 0.0,
        "altitude_m": 1.5,
        "yaw_mode": "hold",
    }
    data.update(overrides)
    return data


def _flight_command(**overrides: object) -> dict[str, object]:
    command: dict[str, object] = {
        "type": "flight_command",
        "vx_cmd": 0.4,
        "vy_cmd": -0.329,
        "vz_cmd": 0.0,
        "yaw_rate_cmd": 0.0,
        "gimbal_yaw_rate_cmd": 0.0,
        "gimbal_pitch_rate_cmd": 0.0,
        "gimbal_yaw_angle_cmd": None,
        "gimbal_pitch_angle_cmd": None,
        "enable_body": True,
        "enable_gimbal": False,
        "enable_gimbal_angle": False,
        "enable_approach": True,
        "active": True,
        "valid": True,
    }
    command.update(overrides)
    return command


def _align_result(command: dict[str, object]) -> dict[str, object]:
    return {
        "done": False,
        "failed": False,
        "reason": "aligning",
        "actions": [],
        "detail": {"command": command},
    }


def _set_drone_snapshot(runner: SystemRunner, **drone: object) -> None:
    with runner.control_command_log_lock:
        runner.latest_snapshot = {"drone": drone}


def test_send_commands_false_skips_payload_release_set_servo() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(False)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "send_commands_disabled"
    assert payload["dispatch"]["sent"] == []
    assert payload["dispatch"]["skipped"][0]["reason"] == "send_commands_disabled"


def test_send_actions_false_skips_payload_release_set_servo() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=False)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is False
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "dry_run_only"
    assert payload["dispatch"]["skipped"][0]["reason"] == "dry_run_only"


def test_send_actions_false_skips_goto_waypoint_local_position() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=False)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is False
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "dry_run_only"
    assert payload["dispatch"]["skipped"][0]["reason"] == "dry_run_only"


def test_send_commands_false_skips_goto_waypoint_local_position() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(False)

    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "send_commands_disabled"
    assert payload["dispatch"]["skipped"][0]["reason"] == "send_commands_disabled"


def test_goto_waypoint_local_position_dispatches_when_gates_enabled() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [
        ("local_position", (1.0, 0.0, -1.5, 1, None), 4)
    ]
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is True
    assert payload["note"] == "goto_waypoint_local_position_dispatch_enabled"
    assert payload["dispatch"]["sent"][0]["action_type"] == "local_position"
    assert payload["dispatch"]["sent"][0]["x"] == 1.0
    assert payload["dispatch"]["sent"][0]["y"] == 0.0
    assert payload["dispatch"]["sent"][0]["z"] == -1.5
    assert payload["dispatch"]["sent"][0]["frame"] == 1


def test_goto_waypoint_status_route_includes_dispatch_keys() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    app = create_app(runner, runner.config.ui)
    start_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/start")
    status_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/status")

    start_route.endpoint(
        ActionStartRequest(
            name="goto_waypoint",
            params=_goto_params(),
            send_actions=True,
        )
    )
    response = status_route.endpoint()

    dispatch = response["action_lab"]["dispatch"]
    assert set(dispatch) == {"sent", "skipped", "errors"}
    assert dispatch["sent"][0]["action_type"] == "local_position"
    assert dispatch["sent"][0]["z"] == -1.5


def test_goto_waypoint_local_position_unavailable_is_skipped() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.services.link_manager = object()

    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=True)
    runner.action_lab_tick()

    payload = runner.action_lab_status_payload()
    assert payload["dispatch"]["sent"] == []
    assert payload["dispatch"]["skipped"][0]["reason"] == "local_position_dispatch_not_available"


def test_goto_waypoint_once_false_dispatches_each_update() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=True)
    runner.action_lab_tick()
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [
        ("local_position", (1.0, 0.0, -1.5, 1, None), 4),
        ("local_position", (1.0, 0.0, -1.5, 1, None), 4),
    ]


def test_goto_waypoint_local_position_exception_goes_to_errors_without_breaking_api() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.services.link_manager.fail = True
    app = create_app(runner, runner.config.ui)
    start_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/start")

    response = start_route.endpoint(
        ActionStartRequest(
            name="goto_waypoint",
            params=_goto_params(),
            send_actions=True,
        )
    )

    assert response["ok"] is True
    assert response["action_lab"]["dispatch"]["sent"] == []
    assert "local position failed" in response["action_lab"]["dispatch"]["errors"][0]["error"]


def test_send_actions_false_skips_align_descend_flight_command() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=False)

    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command()))

    assert runner.services.link_manager.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["action_type"] == "flight_command"
    assert dispatch["skipped"][0]["reason"] == "dry_run_only"


def test_send_commands_false_skips_align_descend_flight_command() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(False)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command()))

    assert runner.services.link_manager.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["action_type"] == "flight_command"
    assert dispatch["skipped"][0]["reason"] == "send_commands_disabled"


def test_align_descend_flight_command_dispatches_when_gates_enabled() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command()))

    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (0.4, -0.329, 0.0, 8), 0)
    ]
    assert dispatch["sent"][0]["action_type"] == "flight_command"
    assert dispatch["sent"][0]["vx_cmd"] == 0.4
    assert dispatch["sent"][0]["vy_cmd"] == -0.329
    assert dispatch["sent"][0]["vz_cmd"] == 0.0
    assert dispatch["sent"][0]["priority"] == 5
    assert dispatch["sent"][0]["key"] == "align_descend_flight_command"
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_effective"] is True
    assert payload["note"] == "action_dispatch_enabled"


def test_align_descend_flight_command_once_false_dispatches_each_update() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    runner._dispatch_action_lab_result(_align_result(_flight_command()))
    runner._dispatch_action_lab_result(_align_result(_flight_command()))

    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (0.4, -0.329, 0.0, 8), 0),
        ("send_velocity_command", (0.4, -0.329, 0.0, 8), 0),
    ]


def test_align_descend_flight_command_ignores_once_true_for_continuous_dispatch() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    action = {
        "action_type": "flight_command",
        "params": _flight_command(),
        "key": "align_descend_flight_command",
        "once": True,
        "priority": 5,
    }

    runner._dispatch_action_lab_actions([action])
    runner._dispatch_action_lab_actions([action])

    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (0.4, -0.329, 0.0, 8), 0),
        ("send_velocity_command", (0.4, -0.329, 0.0, 8), 0),
    ]
    assert runner.action_lab_dispatched_keys == set()


def test_align_descend_flight_command_invalid_is_inactive_skipped() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command(valid=False)))

    assert runner.services.link_manager.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["action_type"] == "flight_command"
    assert dispatch["skipped"][0]["reason"] == "flight_command_inactive"
    assert dispatch["skipped"][0]["vx_cmd"] == 0.4


def test_align_descend_flight_command_inactive_valid_sends_zero_velocity_stop() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command(active=False)))

    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (0.0, 0.0, 0.0, 8), 0)
    ]
    assert dispatch["skipped"] == []
    assert dispatch["sent"][0]["action_type"] == "flight_command"
    assert dispatch["sent"][0]["active"] is False
    assert dispatch["sent"][0]["valid"] is True
    assert dispatch["sent"][0]["vx_cmd"] == 0.0
    assert dispatch["sent"][0]["vy_cmd"] == 0.0
    assert dispatch["sent"][0]["vz_cmd"] == 0.0


def test_align_descend_flight_command_unavailable_is_skipped() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.services.link_manager = object()
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command()))

    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["action_type"] == "flight_command"
    assert dispatch["skipped"][0]["reason"] == "flight_command_dispatch_not_available"
    assert dispatch["skipped"][0]["vx_cmd"] == 0.4


def test_align_descend_flight_command_exception_goes_to_errors_without_breaking_api() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.services.link_manager.fail = True
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command()))

    assert dispatch["sent"] == []
    assert dispatch["errors"][0]["action_type"] == "flight_command"
    assert "velocity failed" in dispatch["errors"][0]["error"]


def test_goto_waypoint_local_position_dispatch_preserves_yaw() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action(
        "goto_waypoint",
        _goto_params(yaw_mode="fixed", yaw_rad=0.5),
        send_actions=True,
    )
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [
        ("local_position", (1.0, 0.0, -1.5, 1, 0.5), 4)
    ]
    payload = runner.action_lab_status_payload()
    assert payload["dispatch"]["sent"][0]["yaw"] == 0.5


def test_goto_waypoint_arm_heading_dispatch_sent_includes_yaw() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    _set_drone_snapshot(runner, armed=False, yaw=0.1)
    runner.action_lab_context()
    _set_drone_snapshot(runner, armed=True, yaw=1.25)

    runner.action_lab_start_action(
        "goto_waypoint",
        _goto_params(yaw_mode="arm_heading"),
        send_actions=True,
    )
    runner.action_lab_tick()

    assert runner.arm_heading_yaw_rad == 1.25
    assert runner.arm_heading_fallback is False
    assert runner.services.link_manager.calls == [
        ("local_position", (1.0, 0.0, -1.5, 1, 1.25), 4)
    ]
    payload = runner.action_lab_status_payload()
    assert payload["dispatch"]["sent"][0]["yaw"] == 1.25


def test_arm_heading_context_fallback_when_first_seen_armed() -> None:
    runner = _runner()
    _set_drone_snapshot(runner, armed=True, yaw=-0.25)

    context = runner.action_lab_context()

    assert context["arm_heading_yaw_rad"] == -0.25
    assert context["arm_heading_fallback"] is True


def test_payload_release_dispatches_release_pwm_to_servo_output_8() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [("set_servo", (8, 1200), 3)]
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is True
    assert payload["note"] == "payload_set_servo_dispatch_enabled"
    assert payload["dispatch"]["sent"][0]["action_type"] == "set_servo"
    assert payload["dispatch"]["sent"][0]["channel"] == 8
    assert payload["dispatch"]["sent"][0]["pwm"] == 1200
    assert payload["dispatch"]["sent"][0]["key"].endswith("_release_servo8")
    assert payload["last_servo_command"]["channel"] == 8
    assert payload["last_servo_command"]["pwm"] == 1200


def test_payload_release_dispatches_hold_pwm_to_servo_output_8() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    for _ in range(6):
        runner.action_lab_tick()

    assert ("set_servo", (8, 1200), 3) in runner.services.link_manager.calls
    assert ("set_servo", (8, 1700), 3) in runner.services.link_manager.calls
    payload = runner.action_lab_status_payload()
    assert payload["dispatch"]["sent"][0]["channel"] == 8
    assert payload["dispatch"]["sent"][0]["pwm"] == 1700
    assert payload["dispatch"]["sent"][0]["key"].endswith("_hold_servo8")


def test_payload_release_dual_servo_outputs_dispatch() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action(
        "payload_release",
        _payload_params(
            servo_outputs=[
                {"channel": 8, "release_pwm": 1200, "hold_pwm": 1700},
                {"channel": 9, "release_pwm": 1700, "hold_pwm": 1200},
            ]
        ),
        send_actions=True,
    )
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [
        ("set_servo", (8, 1200), 3),
        ("set_servo", (9, 1700), 3),
    ]
    payload = runner.action_lab_status_payload()
    assert [item["channel"] for item in payload["dispatch"]["sent"]] == [8, 9]
    assert [item["pwm"] for item in payload["dispatch"]["sent"]] == [1200, 1700]
    assert set(payload["dispatch"]) == {"sent", "skipped", "errors"}


def test_once_key_dispatches_only_once() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    action = {
        "action_type": "set_servo",
        "params": {"channel": 8, "pwm": 1900},
        "key": "payload_release_once",
        "once": True,
        "priority": 3,
    }

    first = runner._dispatch_action_lab_actions([action])
    second = runner._dispatch_action_lab_actions([action])

    assert runner.services.link_manager.calls == [("set_servo", (8, 1900), 3)]
    assert len(first["sent"]) == 1
    assert second["skipped"][0]["reason"] == "once_already_dispatched"


def test_start_new_action_clears_dispatched_keys() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_dispatched_keys.add("already_sent")

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)

    assert runner.action_lab_dispatched_keys == set()


def test_reset_clears_dispatched_keys() -> None:
    runner = _runner()
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_dispatched_keys.add("already_sent")

    runner.action_lab_reset_action()

    assert runner.action_lab_dispatched_keys == set()


def test_set_servo_exception_goes_to_errors_without_breaking_api() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.services.link_manager.fail = True
    app = create_app(runner, runner.config.ui)
    start_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/start")

    response = start_route.endpoint(
        ActionStartRequest(
            name="payload_release",
            params=_payload_params(),
            send_actions=True,
        )
    )

    assert response["ok"] is True
    assert response["action_lab"]["dispatch"]["sent"] == []
    assert "servo failed" in response["action_lab"]["dispatch"]["errors"][0]["error"]
    assert response["action_lab"]["last_servo_command"]["error"] == "servo failed"
