from __future__ import annotations

from dataclasses import dataclass, field

from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner
from web_ui.server import ActionStartRequest, create_app


@dataclass(slots=True)
class FakeLink:
    calls: list[tuple[int, int, int]] = field(default_factory=list)

    def set_servo(self, channel: int, pwm: int, priority: int = 3) -> None:
        self.calls.append((channel, pwm, priority))


def _runner() -> SystemRunner:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    runner.services.link_manager = FakeLink()
    return runner


def _payload_params() -> dict[str, object]:
    return {
        "channels": [13],
        "release_pwm": 1900,
        "hold_pwm": 1100,
        "payload_id": "payload_1",
        "target_id": "target_a",
        "release_wait_updates": 1,
        "priority": 4,
    }


def _goto_params() -> dict[str, object]:
    return {"x": 1.0, "y": 2.0, "altitude_m": 5.0}


def test_action_lab_send_actions_false_does_not_dispatch_set_servo() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=False)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    assert runner.action_lab_status_payload()["send_actions_effective"] is False


def test_action_lab_send_commands_false_does_not_dispatch_set_servo() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(False)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "send_commands_disabled"


def test_action_lab_non_payload_release_does_not_dispatch() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "only_payload_release_dispatch_enabled"


def test_action_lab_payload_release_dispatches_set_servo_when_all_gates_enabled() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [(13, 1900, 4)]
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is True
    assert payload["dry_run_only"] is False
    assert len(payload["dispatch"]["sent"]) == 1


def test_action_lab_once_key_dispatches_only_once() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    action = {
        "action_type": "set_servo",
        "params": {"channel": 13, "pwm": 1900},
        "key": "payload_release_once",
        "once": True,
        "priority": 4,
    }

    first = runner._dispatch_action_lab_actions([action])
    second = runner._dispatch_action_lab_actions([action])

    assert runner.services.link_manager.calls == [(13, 1900, 4)]
    assert len(first["sent"]) == 1
    assert second["skipped"][0]["reason"] == "once_already_dispatched"


def test_action_lab_start_new_action_clears_dispatched_keys() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_dispatched_keys.add("already_sent")

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)

    assert runner.action_lab_dispatched_keys == set()


def test_action_lab_reset_clears_dispatched_keys() -> None:
    runner = _runner()
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_dispatched_keys.add("already_sent")

    runner.action_lab_reset_action()

    assert runner.action_lab_dispatched_keys == set()


def test_action_lab_api_status_includes_dispatch_summary() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    app = create_app(runner, runner.config.ui)
    start_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/start")
    status_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/status")

    start_route.endpoint(
        ActionStartRequest(
            name="payload_release",
            params=_payload_params(),
            send_actions=True,
        )
    )
    response = status_route.endpoint()

    assert response["ok"] is True
    action_lab = response["action_lab"]
    assert action_lab["send_actions_requested"] is True
    assert action_lab["send_actions_effective"] is True
    assert set(action_lab["dispatch"]) == {"sent", "skipped", "errors"}
