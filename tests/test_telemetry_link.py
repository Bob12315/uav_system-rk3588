from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import pytest
from pymavlink import mavutil

from telemetry_link.command_dispatcher import dispatch_text_command
from telemetry_link.command_queue import CommandQueue
from telemetry_link.command_sender import CommandSender
from telemetry_link.config import DEFAULT_CONFIG_PATH, EndpointConfig, TelemetryConfig, build_arg_parser, load_config, load_config_file
from telemetry_link.link_manager import LinkManager, SourceRuntime
from telemetry_link.mavlink_client import MavlinkClient
from telemetry_link.models import ActionCommand, ActionType, ControlCommand, ControlType, GimbalRateCommand
from telemetry_link.state_cache import StateCache
from telemetry_link.telemetry_receiver import TelemetryReceiver


def _endpoint(name: str) -> EndpointConfig:
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


def _config(**overrides) -> TelemetryConfig:
    data = dict(
        data_source="dual",
        active_source="sitl",
        sitl=_endpoint("sitl"),
        real=_endpoint("real"),
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


def test_switch_active_source_clears_all_continuous_queues() -> None:
    manager = LinkManager(_config())
    manager.runtimes["sitl"].command_queue.put_control(
        ControlCommand(command_type=ControlType.VELOCITY, vx=1.0)
    )
    manager.runtimes["sitl"].command_queue.put_gimbal_rate(GimbalRateCommand(yaw_rate=0.2))
    manager.runtimes["real"].command_queue.put_control(
        ControlCommand(command_type=ControlType.VELOCITY, vx=2.0)
    )
    manager.runtimes["real"].command_queue.put_gimbal_rate(GimbalRateCommand(yaw_rate=0.4))

    assert manager.switch_active_source("real") is True

    assert manager.get_active_source() == "real"
    assert manager.runtimes["sitl"].command_queue.peek_control() is None
    assert manager.runtimes["sitl"].command_queue.peek_gimbal_rate() is None
    assert manager.runtimes["real"].command_queue.peek_control() is None
    assert manager.runtimes["real"].command_queue.peek_gimbal_rate() is None


class _FailingClient:
    connection_string = "fake"
    is_sitl = True
    target_system = 0
    target_component = 0

    def __init__(self) -> None:
        self.connect_calls = 0
        self.closed = False

    def connect(self) -> None:
        self.connect_calls += 1

    def wait_heartbeat(self, timeout: float) -> None:
        raise TimeoutError("no heartbeat")

    def close(self) -> None:
        self.closed = True


def test_source_runtime_start_returns_while_connect_retries_in_background() -> None:
    client = _FailingClient()
    runtime = SourceRuntime(
        name="sitl",
        endpoint=_endpoint("sitl"),
        cfg=_config(data_source="sitl", active_source="sitl"),
        state_cache=StateCache(heartbeat_timeout_sec=0.05, rx_timeout_sec=0.05),
        command_queue=CommandQueue(),
        client=client,
        stop_event=threading.Event(),
        worker_stop_event=threading.Event(),
    )

    started_at = time.monotonic()
    runtime.start(logging.getLogger("test"))
    elapsed = time.monotonic() - started_at

    try:
        assert elapsed < 0.05
        assert runtime.monitor_thread is not None
        assert runtime.monitor_thread.is_alive()
    finally:
        runtime.stop()


def test_source_runtime_stop_workers_clears_pending_actions() -> None:
    runtime = SourceRuntime(
        name="sitl",
        endpoint=_endpoint("sitl"),
        cfg=_config(data_source="sitl", active_source="sitl"),
        state_cache=StateCache(heartbeat_timeout_sec=0.05, rx_timeout_sec=0.05),
        command_queue=CommandQueue(),
        client=_FailingClient(),
        stop_event=threading.Event(),
        worker_stop_event=threading.Event(),
    )
    runtime.command_queue.put_action(ActionCommand(action_type=ActionType.ARM))

    runtime._stop_workers(close_client=False)

    assert runtime.command_queue.get_next_action() is None


def test_load_config_rejects_quoted_false_bool(tmp_path, monkeypatch) -> None:
    path = tmp_path / "telemetry.yaml"
    path.write_text(
        """
data_source: sitl
active_source: sitl
sitl:
  connection_type: tcp
real:
  connection_type: tcp
control_send_rate_hz: 10
action_cmd_retries: 0
action_retry_interval_sec: 0.01
heartbeat_timeout_sec: 0.05
rx_timeout_sec: 0.05
reconnect_interval_sec: 0.01
receiver_idle_sleep_sec: 0.01
sender_idle_sleep_sec: 0.01
request_message_intervals: "false"
message_interval_hz: {}
state_udp_enabled: "false"
ui_enabled: "false"
log_level: INFO
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["telemetry_link.main", "--config", str(path)])

    with pytest.raises(ValueError, match="request_message_intervals must be a YAML bool"):
        load_config()


def test_load_config_parses_cli_false_override(tmp_path, monkeypatch) -> None:
    path = tmp_path / "telemetry.yaml"
    path.write_text(
        """
data_source: sitl
active_source: sitl
sitl:
  connection_type: tcp
real:
  connection_type: tcp
control_send_rate_hz: 10
action_cmd_retries: 0
action_retry_interval_sec: 0.01
heartbeat_timeout_sec: 0.05
rx_timeout_sec: 0.05
reconnect_interval_sec: 0.01
receiver_idle_sleep_sec: 0.01
sender_idle_sleep_sec: 0.01
request_message_intervals: true
message_interval_hz: {}
state_udp_enabled: true
ui_enabled: false
log_level: INFO
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "telemetry_link.main",
            "--config",
            str(path),
            "--request-message-intervals",
            "false",
            "--state-udp-enabled",
            "false",
        ],
    )

    cfg = load_config()

    assert cfg.request_message_intervals is False
    assert cfg.state_udp_enabled is False


def test_build_arg_parser_defaults_to_root_telemetry_config(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["telemetry_link.main"])

    args = build_arg_parser().parse_args()

    assert args.config == str(DEFAULT_CONFIG_PATH)


def test_load_config_file_uses_same_root_telemetry_parser() -> None:
    cfg = load_config_file(DEFAULT_CONFIG_PATH)

    assert cfg.data_source == "sitl"
    assert cfg.active_source == "sitl"
    assert cfg.real.connection_type == "eth"


def test_load_config_parses_eth_endpoint(tmp_path, monkeypatch) -> None:
    path = tmp_path / "telemetry.yaml"
    path.write_text(
        """
data_source: real
active_source: real
sitl:
  connection_type: tcp
real:
  connection_type: eth
  eth_mode: udpout
  eth_host: 192.168.144.10
  eth_port: 14550
control_send_rate_hz: 10
action_cmd_retries: 0
action_retry_interval_sec: 0.01
heartbeat_timeout_sec: 0.05
rx_timeout_sec: 0.05
reconnect_interval_sec: 0.01
receiver_idle_sleep_sec: 0.01
sender_idle_sleep_sec: 0.01
request_message_intervals: false
message_interval_hz: {}
state_udp_enabled: false
ui_enabled: false
log_level: INFO
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["telemetry_link.main", "--config", str(path)])

    cfg = load_config()

    assert cfg.real.connection_type == "eth"
    assert cfg.real.eth_mode == "udpout"
    assert cfg.real.eth_host == "192.168.144.10"
    assert cfg.real.eth_port == 14550


def test_mavlink_client_uses_eth_udp_connection_string(monkeypatch) -> None:
    calls = []

    def fake_open(url: str, baud: int | None = None):
        calls.append((url, baud))
        return object()

    endpoint = _endpoint("real")
    endpoint.connection_type = "eth"
    endpoint.eth_mode = "udpin"
    endpoint.eth_host = "0.0.0.0"
    endpoint.eth_port = 14550
    monkeypatch.setattr("telemetry_link.mavlink_client.open_mavlink_connection", fake_open)

    client = MavlinkClient(endpoint)
    client.connect()

    assert client.connection_string == "udpin:0.0.0.0:14550"
    assert calls == [("udpin:0.0.0.0:14550", None)]


def test_mavlink_client_uses_eth_tcp_connection_string(monkeypatch) -> None:
    calls = []

    def fake_open(url: str, baud: int | None = None):
        calls.append((url, baud))
        return object()

    endpoint = _endpoint("real")
    endpoint.connection_type = "eth"
    endpoint.eth_mode = "tcp"
    endpoint.eth_host = "192.168.144.10"
    endpoint.eth_port = 5760
    monkeypatch.setattr("telemetry_link.mavlink_client.open_mavlink_connection", fake_open)

    client = MavlinkClient(endpoint)
    client.connect()

    assert client.connection_string == "tcp:192.168.144.10:5760"
    assert calls == [("tcp:192.168.144.10:5760", None)]


def test_load_config_rejects_invalid_bool_string(tmp_path, monkeypatch) -> None:
    path = tmp_path / "telemetry.yaml"
    path.write_text(
        """
data_source: sitl
active_source: sitl
sitl:
  connection_type: tcp
real:
  connection_type: tcp
control_send_rate_hz: 10
action_cmd_retries: 0
action_retry_interval_sec: 0.01
heartbeat_timeout_sec: 0.05
rx_timeout_sec: 0.05
reconnect_interval_sec: 0.01
receiver_idle_sleep_sec: 0.01
sender_idle_sleep_sec: 0.01
request_message_intervals: maybe
message_interval_hz: {}
state_udp_enabled: false
ui_enabled: false
log_level: INFO
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["telemetry_link.main", "--config", str(path)])

    with pytest.raises(ValueError, match="request_message_intervals must be a YAML bool"):
        load_config()


def test_local_position_ned_updates_raw_local_position_and_relative_altitude() -> None:
    cache = StateCache(heartbeat_timeout_sec=1.0, rx_timeout_sec=1.0)
    now = time.time()
    cache.mark_connected(target_system=1, target_component=1, transport="tcp", now=now)
    receiver = TelemetryReceiver(
        client=None,
        state_cache=cache,
        cfg=_config(data_source="sitl", active_source="sitl", rx_timeout_sec=1.0),
        stop_event=threading.Event(),
    )
    message = SimpleNamespace(x=1.25, y=-2.5, z=-3.75, vx=0.1, vy=0.2, vz=0.3)

    receiver._handle_message("LOCAL_POSITION_NED", message, now)

    state = cache.get_latest_drone_state_validated(time.time())
    assert state.local_position_valid is True
    assert state.local_x == pytest.approx(1.25)
    assert state.local_y == pytest.approx(-2.5)
    assert state.local_z == pytest.approx(-3.75)
    assert state.relative_altitude == pytest.approx(3.75)


def test_dispatch_set_servo_queues_action_command() -> None:
    manager = LinkManager(_config(data_source="sitl", active_source="sitl"))

    result = dispatch_text_command(manager, "set_servo 9 1900")

    action = manager.runtimes["sitl"].command_queue.get_next_action()
    assert result.ok is True
    assert action is not None
    assert action.action_type == ActionType.SET_SERVO
    assert action.params == {"channel": 9, "pwm": 1900}


def test_dispatch_set_relay_queues_action_command() -> None:
    manager = LinkManager(_config(data_source="sitl", active_source="sitl"))

    result = dispatch_text_command(manager, "set_relay 0 on")

    action = manager.runtimes["sitl"].command_queue.get_next_action()
    assert result.ok is True
    assert action is not None
    assert action.action_type == ActionType.SET_RELAY
    assert action.params == {"relay_id": 0, "state": True}


def test_dispatch_release_payload_rejects_unconfigured_mapping() -> None:
    manager = LinkManager(_config(data_source="sitl", active_source="sitl"))

    result = dispatch_text_command(manager, "release_payload 1")

    assert result.ok is False
    assert "not configured" in result.message
    assert manager.runtimes["sitl"].command_queue.get_next_action() is None


class _FakeMav:
    def __init__(self) -> None:
        self.command_long_calls = []
        self.local_position_calls = []

    def command_long_send(self, *args) -> None:
        self.command_long_calls.append(args)

    def set_position_target_local_ned_send(self, *args) -> None:
        self.local_position_calls.append(args)


class _FakeMaster:
    target_system = 1
    target_component = 2

    def __init__(self) -> None:
        self.mav = _FakeMav()


class _RawMessageClient:
    def __init__(self) -> None:
        self.master = _FakeMaster()

    def send_raw_message(self, callback) -> None:
        callback(self.master)


def _sender_with_fake_client() -> tuple[CommandSender, _RawMessageClient]:
    client = _RawMessageClient()
    sender = CommandSender(
        client=client,
        command_queue=CommandQueue(),
        state_cache=StateCache(heartbeat_timeout_sec=1.0, rx_timeout_sec=1.0),
        cfg=_config(data_source="sitl", active_source="sitl"),
        stop_event=threading.Event(),
    )
    return sender, client


def test_command_sender_set_servo_uses_mav_cmd_do_set_servo() -> None:
    sender, client = _sender_with_fake_client()

    sender._send_action(
        ActionCommand(
            action_type=ActionType.SET_SERVO,
            params={"channel": 9, "pwm": 1900},
        )
    )

    call = client.master.mav.command_long_calls[-1]
    assert call[2] == mavutil.mavlink.MAV_CMD_DO_SET_SERVO
    assert call[4:11] == (9.0, 1900.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_command_sender_set_relay_uses_mav_cmd_do_set_relay() -> None:
    sender, client = _sender_with_fake_client()

    sender._send_action(
        ActionCommand(
            action_type=ActionType.SET_RELAY,
            params={"relay_id": 0, "state": True},
        )
    )

    call = client.master.mav.command_long_calls[-1]
    assert call[2] == mavutil.mavlink.MAV_CMD_DO_SET_RELAY
    assert call[4:11] == (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_command_sender_velocity_ignores_yaw_axis() -> None:
    sender, client = _sender_with_fake_client()

    sender._send_velocity(
        client.master,
        ControlCommand(
            command_type=ControlType.VELOCITY,
            vx=1.0,
            vy=2.0,
            vz=3.0,
            yaw_rate=0.5,
            frame=8,
        ),
    )

    call = client.master.mav.local_position_calls[-1]
    type_mask = call[4]
    assert type_mask & mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
    assert type_mask & mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
    assert call[8:11] == (1.0, 2.0, 3.0)


def test_command_sender_explicit_yaw_rate_keeps_yaw_rate_enabled() -> None:
    sender, client = _sender_with_fake_client()

    sender._send_yaw_rate(
        client.master,
        ControlCommand(command_type=ControlType.YAW_RATE, yaw_rate=0.5, frame=8),
    )

    call = client.master.mav.local_position_calls[-1]
    type_mask = call[4]
    assert type_mask & mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
    assert not type_mask & mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
    assert call[-1] == pytest.approx(0.5)


def test_command_sender_local_position_can_hold_yaw() -> None:
    sender, client = _sender_with_fake_client()

    sender._send_local_position(
        client.master,
        ActionCommand(
            action_type=ActionType.LOCAL_POSITION,
            params={"x": 1.0, "y": 2.0, "z": -3.0, "frame": 1, "yaw": 0.75},
        ),
    )

    call = client.master.mav.local_position_calls[-1]
    type_mask = call[4]
    assert not type_mask & mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
    assert type_mask & mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
    assert call[5:8] == (1.0, 2.0, -3.0)
    assert call[14] == pytest.approx(0.75)


def test_command_sender_release_payload_does_not_emit_mavlink_without_mapping() -> None:
    sender, client = _sender_with_fake_client()

    sender._send_action(
        ActionCommand(
            action_type=ActionType.RELEASE_PAYLOAD,
            params={"payload_id": 1},
        )
    )

    assert client.master.mav.command_long_calls == []
