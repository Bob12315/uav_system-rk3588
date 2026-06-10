"""Regression tests for telemetry_link public send interfaces.

Freezes the current LinkManager behaviour so that future refactors
cannot accidentally change the ActionCommand / ControlCommand shape that
the app layer depends on.

These tests run without a real MAVLink connection — they only inspect
the CommandQueue entries that LinkManager produces.
"""

from __future__ import annotations

import time

import pytest

from telemetry_link.config import TelemetryConfig
from telemetry_link.link_manager import LinkManager
from telemetry_link.models import ActionCommand, ActionType, ControlCommand, ControlType


# ── helpers ──────────────────────────────────────────────────────────


def _config(**overrides) -> TelemetryConfig:
    """Minimal config that allows LinkManager construction without hw."""
    from telemetry_link.config import EndpointConfig

    def _ep(name: str) -> EndpointConfig:
        return EndpointConfig(
            name=name,
            connection_type="tcp",
            serial_port="/dev/null",
            baudrate=115200,
            udp_mode="udpin",
            udp_host="127.0.0.1",
            udp_port=14550,
            tcp_host="127.0.0.1",
            tcp_port=5762,
            eth_mode="udpin",
            eth_host="0.0.0.0",
            eth_port=14550,
        )

    data = dict(
        data_source="dual",
        active_source="sitl",
        sitl=_ep("sitl"),
        real=_ep("real"),
        control_send_rate_hz=10.0,
        action_cmd_retries=0,
        action_retry_interval_sec=0.01,
        heartbeat_timeout_sec=0.05,
        rx_timeout_sec=0.05,
        reconnect_interval_sec=0.01,
        receiver_idle_sleep_sec=0.01,
        sender_idle_sleep_sec=0.01,
        request_message_intervals=False,
        message_interval_hz={},
        gimbal_mount_mode=2,
        gimbal_yaw_min_deg=-180.0,
        gimbal_yaw_max_deg=180.0,
        gimbal_pitch_min_deg=-180.0,
        gimbal_pitch_max_deg=180.0,
        state_udp_enabled=False,
        state_udp_ip="127.0.0.1",
        state_udp_port=5010,
        ui_enabled=False,
        log_level="INFO",
    )
    data.update(overrides)
    return TelemetryConfig(**data)


def _cq(manager: LinkManager) -> object:
    """Shortcut to the active runtime's CommandQueue."""
    return manager.runtimes[manager.active_source].command_queue


# ── local_position ───────────────────────────────────────────────────


def test_local_position_queues_action_command_with_correct_params() -> None:
    manager = LinkManager(_config())
    manager.local_position(1.0, 2.0, -3.0, frame=1, priority=4)

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.LOCAL_POSITION
    assert cmd.params["x"] == pytest.approx(1.0)
    assert cmd.params["y"] == pytest.approx(2.0)
    assert cmd.params["z"] == pytest.approx(-3.0)
    assert cmd.params["frame"] == 1
    assert cmd.priority == 4
    assert "yaw" not in cmd.params  # default — no yaw


def test_local_position_with_yaw_includes_yaw_in_params() -> None:
    manager = LinkManager(_config())
    manager.local_position(1.0, 2.0, -3.0, frame=1, yaw=0.5, priority=4)

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.LOCAL_POSITION
    assert cmd.params["yaw"] == pytest.approx(0.5)


def test_local_position_defaults_parameters_sensibly() -> None:
    manager = LinkManager(_config())
    manager.local_position(0.0, 0.0, 0.0, frame=1)

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.LOCAL_POSITION
    assert cmd.priority == 4  # default
    assert cmd.params["frame"] == 1


# ── send_velocity_command ────────────────────────────────────────────


def test_send_velocity_command_queues_control_command_with_correct_values() -> None:
    manager = LinkManager(_config())
    manager.send_velocity_command(0.1, -0.2, 0.3, frame=8)

    cmd = _cq(manager).peek_control()
    assert cmd is not None
    assert cmd.command_type == ControlType.VELOCITY
    assert cmd.vx == pytest.approx(0.1)
    assert cmd.vy == pytest.approx(-0.2)
    assert cmd.vz == pytest.approx(0.3)
    assert cmd.frame == 8


def test_send_velocity_command_latest_wins() -> None:
    manager = LinkManager(_config())
    manager.send_velocity_command(1.0, 2.0, 3.0)
    manager.send_velocity_command(4.0, 5.0, 6.0, frame=1)

    cmd = _cq(manager).peek_control()
    assert cmd.vx == pytest.approx(4.0)
    assert cmd.vy == pytest.approx(5.0)
    assert cmd.vz == pytest.approx(6.0)


# ── stop_control ─────────────────────────────────────────────────────


def test_stop_control_queues_stop_command_with_all_zero_velocity() -> None:
    manager = LinkManager(_config())
    manager.send_velocity_command(1.0, 2.0, 3.0)  # first send velocity
    manager.stop_control(frame=1)

    cmd = _cq(manager).peek_control()
    assert cmd is not None
    assert cmd.command_type == ControlType.STOP
    assert cmd.vx == pytest.approx(0.0)
    assert cmd.vy == pytest.approx(0.0)
    assert cmd.vz == pytest.approx(0.0)
    assert cmd.yaw_rate == pytest.approx(0.0)
    assert cmd.frame == 1


def test_stop_control_preserves_frame() -> None:
    manager = LinkManager(_config())
    manager.stop_control(frame=8)

    cmd = _cq(manager).peek_control()
    assert cmd is not None
    assert cmd.command_type == ControlType.STOP
    assert cmd.frame == 8


def test_stop_body_velocity_queues_stop_with_body_ned_frame() -> None:
    from telemetry_link.frames import BODY_NED

    manager = LinkManager(_config())
    manager.stop_body_velocity()

    cmd = _cq(manager).peek_control()
    assert cmd is not None
    assert cmd.command_type == ControlType.STOP
    assert cmd.vx == 0.0
    assert cmd.vy == 0.0
    assert cmd.vz == 0.0
    assert cmd.yaw_rate == 0.0
    assert cmd.frame == BODY_NED


# ── set_servo ────────────────────────────────────────────────────────


def test_set_servo_queues_action_command_with_correct_channel_pwm_priority() -> None:
    manager = LinkManager(_config())
    manager.set_servo(channel=8, pwm=1200, priority=3)

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.SET_SERVO
    assert cmd.params["channel"] == 8
    assert cmd.params["pwm"] == 1200
    assert cmd.priority == 3


def test_set_servo_default_priority_is_3() -> None:
    manager = LinkManager(_config())
    manager.set_servo(channel=9, pwm=1900)

    cmd = _cq(manager).get_next_action()
    assert cmd.priority == 3


# ── release_payload — soft-disabled (T3) ──────────────────────────────


def test_release_payload_raises_not_implemented_error() -> None:
    """LinkManager.release_payload() is soft-disabled — it raises
    NotImplementedError and must NOT queue any action.

    The canonical payload-drop path is:

        PayloadReleaseAction → set_servo → ActionCommand(SET_SERVO)
    """
    manager = LinkManager(_config())
    with pytest.raises(NotImplementedError, match="release_payload is disabled"):
        manager.release_payload(payload_id=1, priority=3)

    # verify nothing was enqueued
    assert _cq(manager).get_next_action() is None


def test_release_payload_not_called_by_action_dispatcher() -> None:
    """The app-layer ActionDispatcher must NOT call release_payload."""
    import os

    dispatcher_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "action_dispatcher.py"
    )
    with open(dispatcher_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "release_payload" not in content


def test_release_payload_not_called_by_payload_release_action() -> None:
    """PayloadReleaseAction must produce set_servo actions, not release_payload."""
    import os

    action_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "missions",
        "common",
        "actions",
        "payload_release.py",
    )
    with open(action_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert '"release_payload"' not in content
    assert "'release_payload'" not in content
    assert "RELEASE_PAYLOAD" not in content


# ======================================================================
# T1 — frames.py + semantic wrappers
# ======================================================================


def test_frames_constants_match_pymavlink() -> None:
    from pymavlink import mavutil

    from telemetry_link.frames import BODY_NED, GLOBAL, GLOBAL_RELATIVE_ALT_INT, LOCAL_NED

    assert LOCAL_NED == mavutil.mavlink.MAV_FRAME_LOCAL_NED
    assert BODY_NED == mavutil.mavlink.MAV_FRAME_BODY_NED
    assert GLOBAL_RELATIVE_ALT_INT == mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
    assert GLOBAL == mavutil.mavlink.MAV_FRAME_GLOBAL


def test_goto_local_ned_queues_local_position_with_correct_frame_and_yaw() -> None:
    from telemetry_link.frames import LOCAL_NED

    manager = LinkManager(_config())
    manager.goto_local_ned(
        x_north_m=1.0,
        y_east_m=2.0,
        z_down_m=-3.0,
        yaw_rad=0.5,
        priority=4,
    )

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.LOCAL_POSITION
    assert cmd.params["x"] == pytest.approx(1.0)
    assert cmd.params["y"] == pytest.approx(2.0)
    assert cmd.params["z"] == pytest.approx(-3.0)
    assert cmd.params["frame"] == LOCAL_NED
    assert cmd.params["yaw"] == pytest.approx(0.5)
    assert cmd.priority == 4


def test_goto_local_ned_optional_yaw_is_absent_when_not_passed() -> None:
    from telemetry_link.frames import LOCAL_NED

    manager = LinkManager(_config())
    manager.goto_local_ned(x_north_m=0.0, y_east_m=0.0, z_down_m=0.0)

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.LOCAL_POSITION
    assert cmd.params["frame"] == LOCAL_NED
    assert "yaw" not in cmd.params


def test_send_body_velocity_queues_velocity_with_body_ned_frame() -> None:
    from telemetry_link.frames import BODY_NED

    manager = LinkManager(_config())
    manager.send_body_velocity(
        vx_forward_mps=0.1,
        vy_right_mps=-0.2,
        vz_down_mps=0.3,
    )

    cmd = _cq(manager).peek_control()
    assert cmd is not None
    assert cmd.command_type == ControlType.VELOCITY
    assert cmd.vx == pytest.approx(0.1)
    assert cmd.vy == pytest.approx(-0.2)
    assert cmd.vz == pytest.approx(0.3)
    assert cmd.frame == BODY_NED


def test_set_servo_output_pwm_delegates_to_set_servo() -> None:
    manager = LinkManager(_config())
    manager.set_servo_output_pwm(servo_output=8, pwm=1200, priority=3)

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.SET_SERVO
    assert cmd.params["channel"] == 8
    assert cmd.params["pwm"] == 1200
    assert cmd.priority == 3


def test_set_servo_output_pwm_doc_confirms_servo_not_rc() -> None:
    doc = getattr(LinkManager.set_servo_output_pwm, "__doc__", "")
    assert doc is not None
    assert "SERVO output" in doc or "servo_output" in doc
    assert "NOT an RC" in doc


# ── CommandQueue: put_latest_action / clear_actions ──────────────────


def _make_local_position_cmd(x: float = 0.0, y: float = 0.0, z: float = 0.0, priority: int = 4) -> ActionCommand:
    return ActionCommand(
        action_type=ActionType.LOCAL_POSITION,
        params={"x": float(x), "y": float(y), "z": float(z), "frame": 1},
        priority=priority,
        created_at=0.0,
    )


def _make_set_servo_cmd(channel: int = 8, pwm: int = 1500, priority: int = 3) -> ActionCommand:
    return ActionCommand(
        action_type=ActionType.SET_SERVO,
        params={"channel": int(channel), "pwm": int(pwm)},
        priority=priority,
        created_at=0.0,
    )


def test_put_latest_action_replaces_same_type() -> None:
    from telemetry_link.command_queue import CommandQueue

    q = CommandQueue()
    q.put_latest_action(_make_local_position_cmd(x=1.0))
    q.put_latest_action(_make_local_position_cmd(x=2.0))

    cmd = q.get_next_action()
    assert cmd is not None
    assert cmd.params["x"] == pytest.approx(2.0)

    cmd = q.get_next_action()
    assert cmd is None  # only one remained


def test_put_latest_action_does_not_affect_other_types() -> None:
    from telemetry_link.command_queue import CommandQueue

    q = CommandQueue()
    q.put_action(_make_set_servo_cmd(channel=1))
    q.put_latest_action(_make_local_position_cmd(x=99.0))
    q.put_action(_make_set_servo_cmd(channel=2))

    # Two SET_SERVO and one LOCAL_POSITION — all three remain
    types = []
    for _ in range(3):
        cmd = q.get_next_action()
        assert cmd is not None
        types.append(cmd.action_type)

    assert types.count(ActionType.SET_SERVO) == 2
    assert types.count(ActionType.LOCAL_POSITION) == 1
    assert q.get_next_action() is None


def test_clear_actions_by_type_removes_only_matching() -> None:
    from telemetry_link.command_queue import CommandQueue

    q = CommandQueue()
    q.put_action(_make_set_servo_cmd(channel=1))
    q.put_action(_make_local_position_cmd(x=1.0))
    q.put_action(_make_set_servo_cmd(channel=2))

    q.clear_actions(ActionType.LOCAL_POSITION)

    cmd = q.get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.SET_SERVO

    cmd = q.get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.SET_SERVO

    assert q.get_next_action() is None


def test_clear_actions_without_type_clears_all() -> None:
    from telemetry_link.command_queue import CommandQueue

    q = CommandQueue()
    q.put_action(_make_set_servo_cmd())
    q.put_action(_make_local_position_cmd())

    q.clear_actions()  # no type filter — clears everything

    assert q.get_next_action() is None


def test_local_position_latest_only_prevents_pileup() -> None:
    """LinkManager.local_position uses latest-only, so two calls produce one action."""
    manager = LinkManager(_config())
    manager.local_position(1.0, 2.0, -3.0, frame=1, priority=4)
    manager.local_position(10.0, 20.0, -30.0, frame=1, priority=4)

    queue = _cq(manager)
    cmd = queue.get_next_action()
    assert cmd is not None
    assert cmd.params["x"] == pytest.approx(10.0)
    assert cmd.params["y"] == pytest.approx(20.0)
    assert cmd.params["z"] == pytest.approx(-30.0)

    # only one entry remains
    assert queue.get_next_action() is None


def test_hold_current_local_position_sends_hold_command() -> None:
    """hold_current_local_position sends a LOCAL_POSITION at the current drone state."""
    from telemetry_link.frames import LOCAL_NED

    manager = LinkManager(_config())
    runtime = manager.runtimes[manager.active_source]
    # set link as connected so state is not marked disconnected/stale
    runtime.state_cache.update_link(connected=True, last_rx_time=time.time())
    # inject a valid local position into the state cache
    runtime.state_cache.update_drone_state(
        local_position_valid=True,
        attitude_valid=True,
        local_x=12.0,
        local_y=34.0,
        local_z=-5.0,
        yaw=1.0,
        last_local_position_time=time.time(),
        last_attitude_time=time.time(),
    )

    result = manager.hold_current_local_position(priority=0)
    assert result is True

    cmd = _cq(manager).get_next_action()
    assert cmd is not None
    assert cmd.action_type == ActionType.LOCAL_POSITION
    assert cmd.params["x"] == pytest.approx(12.0)
    assert cmd.params["y"] == pytest.approx(34.0)
    assert cmd.params["z"] == pytest.approx(-5.0)
    assert cmd.params["frame"] == LOCAL_NED
    assert cmd.params["yaw"] == pytest.approx(1.0)


def test_hold_current_local_position_returns_false_when_position_invalid() -> None:
    """Without a valid local position, hold_current returns False."""
    manager = LinkManager(_config())
    result = manager.hold_current_local_position(priority=0)
    assert result is False


def test_clear_navigation_queue_with_hold_calls_both() -> None:
    """ActionRuntimeService.clear_navigation_queue with hold_current=True
    clears pending AND sends a hold."""
    from app.action_runtime import ActionRuntimeService

    calls = {"clear": 0, "hold": 0}

    class FakeLink:
        def clear_pending_local_position_actions(self) -> None:
            calls["clear"] += 1
        def hold_current_local_position(self, priority: int = 0) -> bool:
            calls["hold"] += 1
            return True

    ActionRuntimeService.clear_navigation_queue(FakeLink(), hold_current=True)
    assert calls["clear"] == 1
    assert calls["hold"] == 1
