from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class EndpointConfig:
    name: str
    connection_type: str
    serial_port: str
    baudrate: int
    udp_mode: str
    udp_host: str
    udp_port: int
    tcp_host: str
    tcp_port: int
    eth_mode: str
    eth_host: str
    eth_port: int


@dataclass(slots=True)
class TelemetryConfig:
    data_source: str
    active_source: str
    sitl: EndpointConfig
    real: EndpointConfig
    control_send_rate_hz: float
    action_cmd_retries: int
    action_retry_interval_sec: float
    heartbeat_timeout_sec: float
    rx_timeout_sec: float
    reconnect_interval_sec: float
    receiver_idle_sleep_sec: float
    sender_idle_sleep_sec: float
    request_message_intervals: bool
    message_interval_hz: dict[str, float]
    gimbal_mount_mode: int
    gimbal_yaw_min_deg: float
    gimbal_yaw_max_deg: float
    gimbal_pitch_min_deg: float
    gimbal_pitch_max_deg: float
    state_udp_enabled: bool
    state_udp_ip: str
    state_udp_port: int
    ui_enabled: bool
    log_level: str


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError(f"invalid bool value: {value}")
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid bool value: {value}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone MAVLink telemetry link service")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--data-source", choices=["real", "sitl", "dual"])
    parser.add_argument("--active-source", choices=["real", "sitl"])

    parser.add_argument("--real-connection-type", choices=["serial", "udp", "tcp", "eth"])
    parser.add_argument("--real-serial-port")
    parser.add_argument("--real-baudrate", type=int)
    parser.add_argument("--real-udp-mode", choices=["udpin", "udpout"])
    parser.add_argument("--real-udp-host")
    parser.add_argument("--real-udp-port", type=int)
    parser.add_argument("--real-tcp-host")
    parser.add_argument("--real-tcp-port", type=int)
    parser.add_argument("--real-eth-mode", choices=["udpin", "udpout", "tcp"])
    parser.add_argument("--real-eth-host")
    parser.add_argument("--real-eth-port", type=int)

    parser.add_argument("--sitl-connection-type", choices=["serial", "udp", "tcp", "eth"])
    parser.add_argument("--sitl-serial-port")
    parser.add_argument("--sitl-baudrate", type=int)
    parser.add_argument("--sitl-udp-mode", choices=["udpin", "udpout"])
    parser.add_argument("--sitl-udp-host")
    parser.add_argument("--sitl-udp-port", type=int)
    parser.add_argument("--sitl-tcp-host")
    parser.add_argument("--sitl-tcp-port", type=int)
    parser.add_argument("--sitl-eth-mode", choices=["udpin", "udpout", "tcp"])
    parser.add_argument("--sitl-eth-host")
    parser.add_argument("--sitl-eth-port", type=int)

    parser.add_argument("--control-send-rate-hz", type=float)
    parser.add_argument("--action-cmd-retries", type=int)
    parser.add_argument("--action-retry-interval-sec", type=float)
    parser.add_argument("--heartbeat-timeout-sec", type=float)
    parser.add_argument("--rx-timeout-sec", type=float)
    parser.add_argument("--reconnect-interval-sec", type=float)
    parser.add_argument("--receiver-idle-sleep-sec", type=float)
    parser.add_argument("--sender-idle-sleep-sec", type=float)
    parser.add_argument("--request-message-intervals", type=_to_bool)
    parser.add_argument("--gimbal-mount-mode", type=int)
    parser.add_argument("--gimbal-yaw-min-deg", type=float)
    parser.add_argument("--gimbal-yaw-max-deg", type=float)
    parser.add_argument("--gimbal-pitch-min-deg", type=float)
    parser.add_argument("--gimbal-pitch-max-deg", type=float)
    parser.add_argument("--state-udp-enabled", type=_to_bool)
    parser.add_argument("--state-udp-ip")
    parser.add_argument("--state-udp-port", type=int)
    parser.add_argument("--ui", dest="ui_enabled", action="store_true", default=None)
    parser.add_argument("--log-level")
    return parser


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("config yaml must be a mapping")
    return data


def _merge_cli_overrides(merged: dict[str, Any], args: argparse.Namespace) -> None:
    for key, value in vars(args).items():
        if key == "config" or value is None:
            continue
        if key.startswith("real_"):
            merged.setdefault("real", {})
            merged["real"][key.removeprefix("real_")] = value
        elif key.startswith("sitl_"):
            merged.setdefault("sitl", {})
            merged["sitl"][key.removeprefix("sitl_")] = value
        else:
            merged[key.replace("-", "_")] = value


def _build_endpoint(name: str, data: dict[str, Any]) -> EndpointConfig:
    return EndpointConfig(
        name=name,
        connection_type=str(data["connection_type"]),
        serial_port=str(data.get("serial_port", "/dev/ttyUSB0")),
        baudrate=int(data.get("baudrate", 115200)),
        udp_mode=str(data.get("udp_mode", "udpin")),
        udp_host=str(data.get("udp_host", "0.0.0.0")),
        udp_port=int(data.get("udp_port", 14550)),
        tcp_host=str(data.get("tcp_host", "127.0.0.1")),
        tcp_port=int(data.get("tcp_port", 5760)),
        eth_mode=str(data.get("eth_mode", "udpin")),
        eth_host=str(data.get("eth_host", "0.0.0.0")),
        eth_port=int(data.get("eth_port", 14550)),
    )


def load_config() -> TelemetryConfig:
    parser = build_arg_parser()
    args = parser.parse_args()
    merged = _load_yaml(args.config)
    _merge_cli_overrides(merged, args)

    return TelemetryConfig(
        data_source=str(merged["data_source"]),
        active_source=str(merged["active_source"]),
        sitl=_build_endpoint("sitl", dict(merged["sitl"])),
        real=_build_endpoint("real", dict(merged["real"])),
        control_send_rate_hz=float(merged["control_send_rate_hz"]),
        action_cmd_retries=int(merged["action_cmd_retries"]),
        action_retry_interval_sec=float(merged["action_retry_interval_sec"]),
        heartbeat_timeout_sec=float(merged["heartbeat_timeout_sec"]),
        rx_timeout_sec=float(merged["rx_timeout_sec"]),
        reconnect_interval_sec=float(merged["reconnect_interval_sec"]),
        receiver_idle_sleep_sec=float(merged["receiver_idle_sleep_sec"]),
        sender_idle_sleep_sec=float(merged["sender_idle_sleep_sec"]),
        request_message_intervals=_to_bool(merged["request_message_intervals"]),
        message_interval_hz={str(k): float(v) for k, v in dict(merged.get("message_interval_hz", {})).items()},
        gimbal_mount_mode=int(merged.get("gimbal_mount_mode", 2)),
        gimbal_yaw_min_deg=float(merged.get("gimbal_yaw_min_deg", -180.0)),
        gimbal_yaw_max_deg=float(merged.get("gimbal_yaw_max_deg", 180.0)),
        gimbal_pitch_min_deg=float(merged.get("gimbal_pitch_min_deg", -180.0)),
        gimbal_pitch_max_deg=float(merged.get("gimbal_pitch_max_deg", 180.0)),
        state_udp_enabled=_to_bool(merged.get("state_udp_enabled", True)),
        state_udp_ip=str(merged.get("state_udp_ip", "127.0.0.1")),
        state_udp_port=int(merged.get("state_udp_port", 5010)),
        ui_enabled=_to_bool(merged.get("ui_enabled", False)),
        log_level=str(merged["log_level"]),
    )
