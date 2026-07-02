from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pytest

from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner
from missions.common.actions.recon_inspect_target import ReconInspectTargetAction
from web_ui.server import ActionStartRequest, create_app


@dataclass(slots=True)
class FakeLink:
    calls: list[tuple[str, tuple[object, ...], int]] = field(default_factory=list)
    fail: bool = False
    clear_nav_calls: int = 0
    hold_calls: int = 0
    clear_continuous_calls: int = 0

    # ── semantic wrappers (T4 preferred path) ─────────────────────
    def goto_local_ned(
        self,
        x_north_m: float,
        y_east_m: float,
        z_down_m: float,
        yaw_rad: float | None = None,
        priority: int = 4,
    ) -> None:
        if self.fail:
            raise RuntimeError("local position failed")
        self.calls.append(("goto_local_ned", (x_north_m, y_east_m, z_down_m, yaw_rad), priority))

    def send_body_velocity(
        self,
        vx_forward_mps: float,
        vy_right_mps: float,
        vz_down_mps: float,
        yaw_rad: float | None = None,
    ) -> None:
        if self.fail:
            raise RuntimeError("velocity failed")
        args = (vx_forward_mps, vy_right_mps, vz_down_mps)
        if yaw_rad is not None:
            args = (*args, yaw_rad)
        self.calls.append(("send_body_velocity", args, 0))

    def set_servo_output_pwm(
        self,
        servo_output: int,
        pwm: int,
        priority: int = 3,
    ) -> None:
        if self.fail:
            raise RuntimeError("servo failed")
        self.calls.append(("set_servo_output_pwm", (servo_output, pwm), priority))

    # ── legacy interfaces (fallback compat) ───────────────────────
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

    def send_velocity_command(
        self,
        vx: float,
        vy: float,
        vz: float,
        frame: int = 1,
        yaw_rad: float | None = None,
    ) -> None:
        if self.fail:
            raise RuntimeError("velocity failed")
        args = (vx, vy, vz, frame)
        if yaw_rad is not None:
            args = (*args, yaw_rad)
        self.calls.append(("send_velocity_command", args, 0))

    # ── navigation queue management (added T2) ────────────────────

    def clear_continuous_commands(self) -> None:
        self.clear_continuous_calls += 1

    def clear_pending_local_position_actions(self) -> None:
        self.clear_nav_calls += 1

    def hold_current_local_position(self, priority: int = 0) -> bool:
        self.hold_calls += 1
        return True


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


def _survey_params(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "waypoints": [
            {"x": 0.0, "y": 0.0, "altitude_m": 5.0},
            {"x": 2.0, "y": 0.0, "altitude_m": 5.0},
        ],
        "capture_updates_per_waypoint": 3,
        "max_updates_per_waypoint": 200,
        "detection_source": "scene",
        "waypoint_mode": "absolute",
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


def test_recon_observe_zero_action_dispatches_as_continuous_flight_command() -> None:
    runner = _runner()
    dispatcher = runner.action_runtime.dispatcher
    dispatcher.send_actions = True
    action = ReconInspectTargetAction()
    action.start({"targets": [{"local_x": 0.0, "local_y": 5.0}], "target_index": 0})

    dispatch = dispatcher.dispatch_actions(
        [action._zero_velocity_action()],
        action_name="recon_inspect_target",
        send_commands=True,
        link_manager=runner.services.link_manager,
    )

    assert dispatch["errors"] == []
    assert dispatch["skipped"] == []
    assert dispatch["sent"][0]["action_type"] == "flight_command"
    assert runner.services.link_manager.calls[-1][0] == "send_body_velocity"
    assert runner.services.link_manager.calls[-1][1][:3] == (0.0, 0.0, 0.0)


def _set_drone_snapshot(runner: SystemRunner, **drone: object) -> None:
    drone.setdefault("attitude_valid", True)
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
        ("goto_local_ned", (1.0, 0.0, -1.5, None), 4)
    ]
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is True
    assert payload["note"] == "local_position_dispatch_enabled"
    assert payload["dispatch"]["sent"][0]["action_type"] == "local_position"
    assert payload["dispatch"]["sent"][0]["x"] == 1.0
    assert payload["dispatch"]["sent"][0]["y"] == 0.0
    assert payload["dispatch"]["sent"][0]["z"] == -1.5
    assert payload["dispatch"]["sent"][0]["frame"] == 1


def test_survey_area_local_position_dispatches_like_goto_waypoint(caplog) -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    with caplog.at_level(logging.INFO, logger="SystemRunner"):
        runner.action_lab_start_action("survey_area", _survey_params(), send_actions=True)
        runner.action_lab_tick()

    assert runner.services.link_manager.calls == [
        ("goto_local_ned", (0.0, 0.0, -5.0, None), 4)
    ]
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is True
    assert payload["note"] == "local_position_dispatch_enabled"
    assert payload["dispatch"]["sent"][0]["action_type"] == "local_position"
    assert payload["dispatch"]["sent"][0]["x"] == 0.0
    assert payload["dispatch"]["sent"][0]["y"] == 0.0
    assert payload["dispatch"]["sent"][0]["z"] == -5.0
    assert payload["dispatch"]["sent"][0]["frame"] == 1
    assert payload["dispatch"]["sent"][0]["key"] == "survey_waypoint_0"
    assert "current_action=survey_area action_type=local_position dispatch_allowed=True" in caplog.text


def test_survey_area_local_position_respects_send_commands_gate() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(False)

    runner.action_lab_start_action("survey_area", _survey_params(), send_actions=True)
    runner.action_lab_tick()

    payload = runner.action_lab_status_payload()
    assert runner.services.link_manager.calls == []
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "send_commands_disabled"
    assert payload["dispatch"]["sent"] == []
    assert payload["dispatch"]["skipped"][0]["action_type"] == "local_position"
    assert payload["dispatch"]["skipped"][0]["reason"] == "send_commands_disabled"


def test_survey_area_send_actions_false_is_dry_run_only() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("survey_area", _survey_params(), send_actions=False)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == []
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is False
    assert payload["send_actions_effective"] is False
    assert payload["note"] == "dry_run_only"
    assert payload["dispatch"]["sent"] == []


def test_target_lock_still_not_dispatched() -> None:
    """target_lock remains blocked in phase 4A — yolo_lock_target is not implemented."""
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("target_lock", {}, send_actions=True)
    runner.action_lab_tick()
    payload = runner.action_lab_status_payload()
    assert runner.services.link_manager.calls == []
    assert payload["dry_run_only"] is True
    assert payload["dispatch"]["sent"] == []
    # note: target_lock now dispatches yolo_lock_target when yolo_client is available;
    # see PR B yolo tests below.


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


def test_action_start_route_receives_send_actions_true_and_status_reports_requested(caplog) -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(False)
    app = create_app(runner, runner.config.ui)
    start_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/start")
    status_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/status")

    with caplog.at_level(logging.INFO, logger="WebUiServer"):
        response = start_route.endpoint(
            ActionStartRequest(
                name="goto_waypoint",
                params=_goto_params(),
                send_actions=True,
            )
        )
    status = status_route.endpoint()

    assert response["ok"] is True
    assert response["action_lab"]["send_actions"] is True
    assert response["action_lab"]["requested_send_actions"] is True
    assert response["action_lab"]["send_actions_requested"] is True
    assert response["action_lab"]["send_actions_effective"] is False
    assert response["action_lab"]["dry_run_only"] is True
    assert response["action_lab"]["note"] == "send_commands_disabled"
    assert status["action_lab"]["requested_send_actions"] is True
    assert status["action_lab"]["send_actions_requested"] is True
    assert "/api/actions/start action=goto_waypoint send_actions=True" in caplog.text


def test_align_descend_status_route_includes_altitude_and_command_fields() -> None:
    runner = _runner()
    app = create_app(runner, runner.config.ui)
    start_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/start")
    status_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/actions/status")
    with runner.control_command_log_lock:
        runner.latest_snapshot = {
            "drone": {"relative_altitude": 3.0, "control_allowed": True},
            "perception": {
                "target_valid": True,
                "tracking_state": "locked",
                "ex": 0.0,
                "ey": 0.0,
            },
        }

    start_route.endpoint(
        ActionStartRequest(
            name="align_descend",
            params={"finish_altitude_m": 3.0, "config": {"min_altitude_m": 2.5}},
            send_actions=False,
        )
    )
    response = status_route.endpoint()

    detail = response["action_lab"]["status"]["last_result"]["detail"]
    assert detail["current_altitude_m"] == 3.0
    assert detail["finish_altitude_m"] == 3.0
    assert detail["min_altitude_m"] == 2.5
    assert detail["altitude_source"] == "relative_altitude"
    assert detail["reached_finish_altitude"] is True
    assert detail["command"]["vz_cmd"] == 0.0


def test_align_descend_missing_altitude_dispatches_zero_stop_when_send_enabled() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    with runner.control_command_log_lock:
        runner.latest_snapshot = {
            "drone": {"control_allowed": True},
            "perception": {
                "target_valid": True,
                "tracking_state": "locked",
                "ex": 0.0,
                "ey": 0.0,
            },
        }

    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    runner.action_lab_tick()

    payload = runner.action_lab_status_payload()
    result = payload["status"]["last_result"]
    assert result["failed"] is True
    assert result["reason"] == "missing_altitude"
    assert runner.services.link_manager.calls == [
        ("send_body_velocity", (0.0, 0.0, 0.0), 0)
    ]
    assert payload["dispatch"]["sent"][0]["active"] is False
    assert payload["dispatch"]["sent"][0]["vz_cmd"] == 0.0


def test_action_lab_start_sets_running_state() -> None:
    runner = _runner()

    result = runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)

    assert result.reason == "action_started"
    assert runner.action_runner.status()["state"] == "running"
    assert runner.action_runner.status()["action_name"] == "payload_release"


def test_action_lab_starting_different_action_stops_current_and_starts_new() -> None:
    runner = _runner()
    first = runner.action_lab_start_action("align_descend", {}, send_actions=True)
    old_action = runner.action_runner.current_action

    second = runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)

    assert first.reason == "action_started"
    assert second.reason == "action_started"
    assert getattr(old_action, "stopped", False) is True
    assert runner.action_runner.status()["state"] == "running"
    assert runner.action_runner.status()["action_name"] == "payload_release"


def test_action_lab_starting_new_action_clears_dispatch_keys_and_last_dispatch() -> None:
    runner = _runner()
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    runner.action_lab_dispatched_keys.add("already_sent")
    runner.action_lab_last_dispatch = {
        "sent": [{"action_type": "flight_command"}],
        "skipped": [{"reason": "old"}],
        "errors": [{"error": "old"}],
    }

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)

    assert runner.action_lab_dispatched_keys == set()
    assert runner.action_lab_last_dispatch == {"sent": [], "skipped": [], "errors": []}


def test_action_lab_reset_clears_dispatch_and_does_not_restart() -> None:
    runner = _runner()
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_dispatched_keys.add("already_sent")
    runner.action_lab_last_dispatch = {
        "sent": [{"action_type": "set_servo"}],
        "skipped": [{"reason": "old"}],
        "errors": [{"error": "old"}],
    }

    result = runner.action_lab_reset_action()

    assert result.reason == "action_reset"
    assert runner.action_runner.status()["state"] == "idle"
    assert runner.action_runner.status()["action_name"] is None
    assert runner.action_lab_dispatched_keys == set()
    assert runner.action_lab_last_dispatch == {"sent": [], "skipped": [], "errors": []}
    assert runner.services.link_manager.calls == []


def test_action_lab_stop_sets_stopped_state() -> None:
    runner = _runner()
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)

    result = runner.action_lab_stop_action()

    assert result.reason == "action_stopped"
    assert runner.action_runner.status()["state"] == "stopped"
    assert runner.action_runner.status()["action_name"] == "payload_release"


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
        ("goto_local_ned", (1.0, 0.0, -1.5, None), 4),
        ("goto_local_ned", (1.0, 0.0, -1.5, None), 4),
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
        ("send_body_velocity", (0.4, -0.329, 0.0), 0)
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


def test_align_descend_flight_command_dispatches_yaw_hold_when_present() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(
        _align_result(_flight_command(yaw_hold_rad=1.25))
    )

    vx_north = 0.4 * math.cos(1.25) - (-0.329) * math.sin(1.25)
    vy_east = 0.4 * math.sin(1.25) + (-0.329) * math.cos(1.25)
    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (vx_north, vy_east, 0.0, 1, 1.25), 0)
    ]
    assert dispatch["sent"][0]["yaw_hold_rad"] == 1.25
    assert dispatch["sent"][0]["frame"] == 1


def test_align_descend_flight_command_uses_velocity_yaw_for_local_conversion() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    dispatch = runner._dispatch_action_lab_result(
        _align_result(_flight_command(yaw_hold_rad=1.57, velocity_yaw_rad=0.25))
    )

    vx_north = 0.4 * math.cos(0.25) - (-0.329) * math.sin(0.25)
    vy_east = 0.4 * math.sin(0.25) + (-0.329) * math.cos(0.25)
    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (vx_north, vy_east, 0.0, 1, 1.57), 0)
    ]
    assert all(call[0] != "send_body_velocity" for call in runner.services.link_manager.calls)
    assert dispatch["sent"][0]["yaw_hold_rad"] == 1.57
    assert dispatch["sent"][0]["velocity_yaw_rad"] == 0.25


def test_align_descend_flight_command_once_false_dispatches_each_update() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)

    runner._dispatch_action_lab_result(_align_result(_flight_command()))
    runner._dispatch_action_lab_result(_align_result(_flight_command()))

    assert runner.services.link_manager.calls == [
        ("send_body_velocity", (0.4, -0.329, 0.0), 0),
        ("send_body_velocity", (0.4, -0.329, 0.0), 0),
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
        ("send_body_velocity", (0.4, -0.329, 0.0), 0),
        ("send_body_velocity", (0.4, -0.329, 0.0), 0),
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
        ("send_body_velocity", (0.0, 0.0, 0.0), 0)
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
        ("goto_local_ned", (1.0, 0.0, -1.5, 0.5), 4)
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

    assert runner.arm_heading_yaw_rad == pytest.approx(0.1)
    assert runner.arm_heading_fallback is False
    assert runner.services.link_manager.calls == [
        ("goto_local_ned", (1.0, 0.0, -1.5, pytest.approx(0.1)), 4)
    ]
    payload = runner.action_lab_status_payload()
    assert payload["dispatch"]["sent"][0]["yaw"] == pytest.approx(0.1)
    assert payload["dispatch"]["sent"][0]["input_frame"] == "local_ned"
    assert payload["dispatch"]["sent"][0]["input_target"] == {
        "x": 1.0, "y": 0.0, "z": -1.5,
    }
    assert payload["dispatch"]["sent"][0]["local_target"] == {
        "x": 1.0, "y": 0.0, "z": -1.5,
    }


def test_goto_waypoint_field_heading_dispatch_sent_includes_yaw() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    assert runner.runtime_context_builder.confirm_field_heading(
        yaw_rad=-0.65,
        drone={"local_position_valid": True, "local_x": 0.0, "local_y": 0.0, "local_z": 0.0},
        source="test",
    )

    runner.action_lab_start_action(
        "goto_waypoint",
        _goto_params(yaw_mode="field_heading"),
        send_actions=True,
    )
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [
        ("goto_local_ned", (1.0, 0.0, -1.5, pytest.approx(-0.65)), 4)
    ]
    payload = runner.action_lab_status_payload()
    assert payload["dispatch"]["sent"][0]["yaw"] == pytest.approx(-0.65)


def test_field_heading_status_reports_delta_and_manual_confirm_does_not_call_link() -> None:
    runner = _runner()
    _set_drone_snapshot(
        runner,
        armed=False,
        yaw=0.5,
        local_position_valid=True,
        local_x=10.0,
        local_y=20.0,
        local_z=-1.0,
    )

    result = runner.confirm_field_heading_manual()
    status = runner.field_heading_status()

    assert result.ok is True
    assert "field heading/origin confirmed" in result.message
    assert status["field_heading_confirmed"] is True
    assert status["field_heading_source"] == "manual_web"
    assert status["field_heading_yaw_rad"] == pytest.approx(0.5)
    assert status["origin_confirmed"] is True
    assert status["origin_local_x"] == pytest.approx(10.0)
    assert status["origin_local_y"] == pytest.approx(20.0)
    assert status["origin_local_z"] == pytest.approx(-1.0)
    assert status["current_field_x"] == pytest.approx(0.0)
    assert status["current_field_y"] == pytest.approx(0.0)
    link_manager = runner.services.link_manager
    runner.services.link_manager = None
    snapshot = runner.web_status_snapshot()
    runner.services.link_manager = link_manager
    assert snapshot["field_position"]["x"] == pytest.approx(0.0)
    assert snapshot["field_position"]["y"] == pytest.approx(0.0)
    assert snapshot["field_transform"]["confirmed"] is True
    assert status["delta_current_to_field_deg"] == pytest.approx(0.0)
    assert runner.services.link_manager.calls == []


def test_field_heading_manual_confirm_fails_when_local_position_invalid() -> None:
    runner = _runner()
    _set_drone_snapshot(runner, armed=False, yaw=0.5, local_position_valid=False)

    result = runner.confirm_field_heading_manual()

    assert result.ok is False
    assert "LOCAL_NED" in result.message
    assert runner.runtime_context_builder.field_heading_confirmed is False
    assert runner.services.link_manager.calls == []


def test_field_heading_manual_confirm_fails_when_attitude_invalid() -> None:
    runner = _runner()
    _set_drone_snapshot(runner, armed=False, yaw=0.5, attitude_valid=False)

    result = runner.confirm_field_heading_manual()

    assert result.ok is False
    assert result.message == "attitude yaw not valid"
    assert runner.runtime_context_builder.field_heading_confirmed is False
    assert runner.services.link_manager.calls == []


def test_arm_heading_context_fallback_when_first_seen_armed() -> None:
    runner = _runner()
    _set_drone_snapshot(runner, armed=True, yaw=-0.25)

    context = runner.action_lab_context()

    assert context["arm_heading_yaw_rad"] == -0.25
    assert context["arm_heading_fallback"] is True


def test_arm_heading_context_ignores_invalid_attitude_default_yaw() -> None:
    runner = _runner()
    _set_drone_snapshot(runner, armed=True, yaw=0.0, attitude_valid=False)

    context = runner.action_lab_context()

    assert "arm_heading_yaw_rad" not in context
    assert runner.arm_heading_yaw_rad is None


def test_payload_release_dispatches_release_pwm_to_servo_output_8() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)

    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_tick()

    assert runner.services.link_manager.calls == [
        ("set_servo_output_pwm", (8, 1200), 3),
        ("send_body_velocity", (0.0, 0.0, 0.0), 0),
    ]
    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is True
    assert payload["note"] == "action_dispatch_enabled"
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

    assert ("set_servo_output_pwm", (8, 1200), 3) in runner.services.link_manager.calls
    assert ("set_servo_output_pwm", (8, 1700), 3) in runner.services.link_manager.calls
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
        ("set_servo_output_pwm", (8, 1200), 3),
        ("set_servo_output_pwm", (9, 1700), 3),
        ("send_body_velocity", (0.0, 0.0, 0.0), 0),
    ]
    payload = runner.action_lab_status_payload()
    servo_sent = [item for item in payload["dispatch"]["sent"] if item["action_type"] == "set_servo"]
    assert [item["channel"] for item in servo_sent] == [8, 9]
    assert [item["pwm"] for item in servo_sent] == [1200, 1700]
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

    assert runner.services.link_manager.calls == [("set_servo_output_pwm", (8, 1900), 3)]
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


# ======================================================================
# T4 — fallback path tests (link_manager without semantic wrappers)
# ======================================================================


@dataclass(slots=True)
class _FakeLinkFallback:
    """A link_manager stub that only exposes the legacy interfaces,
    NOT the T1 semantic wrappers.  Used to confirm the fallback path
    still works."""
    calls: list[tuple[str, tuple[object, ...], int]] = field(default_factory=list)
    fail: bool = False

    def local_position(self, x, y, z, frame, yaw=None, priority=4):
        if self.fail:
            raise RuntimeError("local position failed")
        self.calls.append(("local_position", (x, y, z, frame, yaw), priority))

    def send_velocity_command(self, vx, vy, vz, frame=1, yaw_rad=None):
        if self.fail:
            raise RuntimeError("velocity failed")
        args = (vx, vy, vz, frame)
        if yaw_rad is not None:
            args = (*args, yaw_rad)
        self.calls.append(("send_velocity_command", args, 0))

    def set_servo(self, channel, pwm, priority=3):
        if self.fail:
            raise RuntimeError("servo failed")
        self.calls.append(("set_servo", (channel, pwm), priority))


def _runner_fallback() -> SystemRunner:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    runner.services.link_manager = _FakeLinkFallback()
    return runner


def test_fallback_local_position_still_dispatches_when_wrappers_absent() -> None:
    runner = _runner_fallback()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=True)
    runner.action_lab_tick()
    assert runner.services.link_manager.calls == [
        ("local_position", (1.0, 0.0, -1.5, 1, None), 4)
    ]


def test_fallback_flight_command_still_dispatches_when_wrappers_absent() -> None:
    runner = _runner_fallback()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    dispatch = runner._dispatch_action_lab_result(_align_result(_flight_command()))
    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (0.4, -0.329, 0.0, 8), 0)
    ]
    assert dispatch["sent"][0]["action_type"] == "flight_command"


def test_fallback_flight_command_passes_yaw_hold_when_supported() -> None:
    runner = _runner_fallback()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    dispatch = runner._dispatch_action_lab_result(
        _align_result(_flight_command(yaw_hold_rad=-0.4))
    )
    vx_north = 0.4 * math.cos(-0.4) - (-0.329) * math.sin(-0.4)
    vy_east = 0.4 * math.sin(-0.4) + (-0.329) * math.cos(-0.4)
    assert runner.services.link_manager.calls == [
        ("send_velocity_command", (vx_north, vy_east, 0.0, 1, -0.4), 0)
    ]
    assert dispatch["sent"][0]["yaw_hold_rad"] == -0.4
    assert dispatch["sent"][0]["frame"] == 1


def test_fallback_set_servo_still_dispatches_when_wrappers_absent() -> None:
    runner = _runner_fallback()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("payload_release", _payload_params(), send_actions=True)
    runner.action_lab_tick()
    assert runner.services.link_manager.calls == [
        ("set_servo", (8, 1200), 3),
        ("send_velocity_command", (0.0, 0.0, 0.0, 8), 0),
    ]


# ======================================================================
# PR A — policy-driven gate + body_velocity + servo_output compat
# ======================================================================


def _body_velocity_params(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "action_type": "body_velocity",
        "params": {
            "vx_body_mps": 0.4,
            "vy_body_mps": -0.329,
            "vz_body_mps": 0.0,
            "active": True,
            "valid": True,
        },
        "key": "align_descend_body_velocity",
        "once": False,
        "priority": 5,
    }
    # merge param-level overrides instead of replacing the whole dict
    for key, value in overrides.items():
        if key == "params" and isinstance(value, dict):
            data["params"].update(value)
        else:
            data[key] = value
    return data


def test_body_velocity_dispatches_from_align_descend() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    dispatch = runner._dispatch_action_lab_actions([_body_velocity_params()])

    assert runner.services.link_manager.calls == [
        ("send_body_velocity", (0.4, -0.329, 0.0), 0)
    ]
    assert dispatch["sent"][0]["action_type"] == "body_velocity"


def test_body_velocity_continuous_ignores_once() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    action = _body_velocity_params(once=True)

    runner._dispatch_action_lab_actions([action])
    runner._dispatch_action_lab_actions([action])

    assert runner.services.link_manager.calls == [
        ("send_body_velocity", (0.4, -0.329, 0.0), 0),
        ("send_body_velocity", (0.4, -0.329, 0.0), 0),
    ]
    assert runner.action_lab_dispatched_keys == set()


def test_body_velocity_valid_false_is_skipped() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    dispatch = runner._dispatch_action_lab_actions(
        [_body_velocity_params(params={"vx_body_mps": 0.4, "valid": False})]
    )

    assert runner.services.link_manager.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["action_type"] == "body_velocity"
    assert dispatch["skipped"][0]["reason"] == "flight_command_inactive"


def test_body_velocity_active_false_sends_zero_stop() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("align_descend", {}, send_actions=True)
    dispatch = runner._dispatch_action_lab_actions(
        [_body_velocity_params(params={"vx_body_mps": 0.4, "active": False, "valid": True})]
    )

    assert runner.services.link_manager.calls == [
        ("send_body_velocity", (0.0, 0.0, 0.0), 0)
    ]
    assert dispatch["sent"][0]["active"] is False
    assert dispatch["sent"][0]["valid"] is True
    assert dispatch["sent"][0]["vx_cmd"] == 0.0


def test_body_velocity_requires_align_descend_in_allowed_actions() -> None:
    """body_velocity dispatch must only allow align_descend (not e.g. goto_waypoint)."""
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_start_action("goto_waypoint", _goto_params(), send_actions=True)
    action = _body_velocity_params(key="goto_body_velocity")
    dispatch = runner._dispatch_action_lab_actions([action])

    assert runner.services.link_manager.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["reason"] == "action_dispatch_not_enabled"


def test_set_servo_accepts_servo_output_param() -> None:
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_send_actions = True
    action = {
        "action_type": "set_servo",
        "params": {"servo_output": 9, "pwm": 1900},
        "key": "servo_output_test",
        "once": True,
        "priority": 3,
    }
    dispatch = runner._dispatch_action_lab_actions([action])

    assert runner.services.link_manager.calls == [
        ("set_servo_output_pwm", (9, 1900), 3)
    ]
    assert dispatch["sent"][0]["channel"] == 9


# ======================================================================
# PR B — yolo_lock_target dispatch
# ======================================================================


@dataclass(slots=True)
class FakeYoloClient:
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    fail: bool = False

    def lock_target(self, track_id: int) -> None:
        if self.fail:
            raise RuntimeError("yolo failed")
        self.calls.append(("lock_target", (track_id,)))


def _runner_with_yolo() -> SystemRunner:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    runner.services.link_manager = FakeLink()
    runner.action_runtime.dispatcher.yolo_client = FakeYoloClient()
    return runner


def test_yolo_lock_target_dispatches_when_send_actions_true() -> None:
    runner = _runner_with_yolo()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_send_actions = True
    action = {
        "action_type": "yolo_lock_target",
        "params": {"track_id": 42},
        "key": "target_lock",
        "once": True,
        "priority": 5,
    }
    dispatch = runner._dispatch_action_lab_actions([action])

    yolo = runner.action_runtime.dispatcher.yolo_client
    assert yolo.calls == [("lock_target", (42,))]
    assert dispatch["sent"][0]["action_type"] == "yolo_lock_target"
    assert dispatch["sent"][0]["track_id"] == 42


def test_yolo_lock_target_dispatches_when_send_commands_false() -> None:
    """key PR B test: requires_send_commands=False means yolo_lock_target
    still dispatches even when SEND=false."""
    runner = _runner_with_yolo()
    runner.controller_switches.set_send_commands(False)
    runner.action_lab_send_actions = True
    action = {
        "action_type": "yolo_lock_target",
        "params": {"track_id": 42},
        "key": "target_lock",
        "once": True,
        "priority": 5,
    }
    dispatch = runner._dispatch_action_lab_actions([action])

    yolo = runner.action_runtime.dispatcher.yolo_client
    assert yolo.calls == [("lock_target", (42,))]
    assert dispatch["sent"][0]["action_type"] == "yolo_lock_target"


def test_yolo_lock_target_send_actions_false_is_dry_run_only() -> None:
    """send_actions=false still blocks yolo_lock_target."""
    runner = _runner_with_yolo()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_send_actions = False
    action = {
        "action_type": "yolo_lock_target",
        "params": {"track_id": 42},
        "key": "target_lock",
        "once": True,
        "priority": 5,
    }
    dispatch = runner._dispatch_action_lab_actions([action])

    yolo = runner.action_runtime.dispatcher.yolo_client
    assert yolo.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["reason"] == "dry_run_only"


def test_yolo_lock_target_once_key_dispatches_only_once() -> None:
    runner = _runner_with_yolo()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_send_actions = True
    action = {
        "action_type": "yolo_lock_target",
        "params": {"track_id": 42},
        "key": "target_lock",
        "once": True,
        "priority": 5,
    }
    first = runner._dispatch_action_lab_actions([action])
    second = runner._dispatch_action_lab_actions([action])

    yolo = runner.action_runtime.dispatcher.yolo_client
    assert yolo.calls == [("lock_target", (42,))]
    assert len(first["sent"]) == 1
    assert second["skipped"][0]["reason"] == "once_already_dispatched"


def test_yolo_lock_target_client_unavailable_is_skipped() -> None:
    runner = _runner()
    runner.action_runtime.dispatcher.yolo_client = None  # simulate no client
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_send_actions = True
    action = {
        "action_type": "yolo_lock_target",
        "params": {"track_id": 42},
        "key": "target_lock",
        "once": True,
        "priority": 5,
    }
    dispatch = runner._dispatch_action_lab_actions([action])

    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["reason"] == "yolo_client_not_available"


def test_yolo_lock_target_exception_goes_to_errors() -> None:
    runner = _runner_with_yolo()
    runner.controller_switches.set_send_commands(True)
    runner.action_lab_send_actions = True
    runner.action_runtime.dispatcher.yolo_client.fail = True
    action = {
        "action_type": "yolo_lock_target",
        "params": {"track_id": 42},
        "key": "target_lock",
        "once": True,
        "priority": 5,
    }
    dispatch = runner._dispatch_action_lab_actions([action])

    assert dispatch["sent"] == []
    assert "yolo failed" in dispatch["errors"][0]["error"]


def test_action_lab_start_stop_reset_clear_navigation_queue_does_not_crash() -> None:
    """SystemRunner action_lab_start/stop/reset calls clear_continuous, clear_nav and hold_current."""
    runner = _runner()
    fl: FakeLink = runner.services.link_manager  # type: ignore[assignment]

    # start a goto_waypoint action — clears continuous + nav queue
    runner.action_lab_start_action("goto_waypoint", {"x": 1.0, "y": 0.0, "altitude_m": 1.5})
    assert runner.action_runtime.runner.state == "running"
    assert fl.clear_continuous_calls == 1  # start clears continuous
    assert fl.clear_nav_calls == 1  # start clears nav

    # stop with hold_current=True
    runner.action_lab_stop_action()
    assert runner.action_runtime.runner.state in ("idle", "stopped")
    assert fl.clear_continuous_calls == 2  # stop clears continuous
    assert fl.clear_nav_calls == 2  # stop clears nav
    assert fl.hold_calls == 1  # stop holds current position

    # reset also clears and holds
    runner.action_lab_reset_action()
    assert runner.action_runtime.runner.state == "idle"
    assert fl.clear_continuous_calls == 3
    assert fl.clear_nav_calls == 3
    assert fl.hold_calls == 2


def test_multi_view_localize_dispatches_local_position_when_gates_enabled() -> None:
    """multi_view_localize is in allowed_actions for local_position dispatch."""
    runner = _runner()
    runner.controller_switches.set_send_commands(True)
    runner.arm_heading_yaw_rad = 0.0

    runner.action_lab_start_action(
        "multi_view_localize",
        {
            "waypoint_mode": "absolute",
            "waypoints": [{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
            "capture_updates_per_waypoint": 1,
            "settle_updates_per_waypoint": 1,
            "max_updates_per_waypoint": 10,
            "yaw_mode": "hold",
        },
        send_actions=True,
    )
    runner.action_lab_tick()

    # check that local_position was sent via goto_local_ned
    calls = runner.services.link_manager.calls
    assert len(calls) >= 1
    assert calls[0][0] == "goto_local_ned"

    payload = runner.action_lab_status_payload()
    assert payload["send_actions_requested"] is True
    assert payload["send_actions_effective"] is True
    assert payload["note"] == "local_position_dispatch_enabled"
    assert payload["dispatch"]["sent"][0]["action_type"] == "local_position"
