"""Regression tests for telemetry_link public send interfaces.

Freezes the current LinkManager behaviour so that future refactors
cannot accidentally change the ActionCommand / ControlCommand shape that
the app layer depends on.

These tests run without a real MAVLink connection — they only inspect
the CommandQueue entries that LinkManager produces.
"""

from __future__ import annotations

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
