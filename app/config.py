"""Configuration for the Action Mission application runtime.

This module intentionally has no mission/stage/control compatibility loader.
Action Mission templates are selected through the Web UI, while this file owns
only process, telemetry, Web UI, blackbox, and default-send configuration.
"""
from __future__ import annotations

import argparse
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from application.yolo_command_client import YoloCommandConfig
from telemetry_link.config import TelemetryConfig, load_config_file as load_telemetry_config

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass(slots=True)
class AppRuntimeConfig:
    yolo_udp_ip: str
    yolo_udp_port: int
    yolo_max_datagram_bytes: int
    yolo_max_detections: int
    yolo_tombstone_capacity: int
    loop_hz: float
    perception_timeout_sec: float
    print_rate_hz: float
    require_gimbal_feedback: bool
    log_level: str
    ui_enabled: bool
    connect_telemetry: bool
    start_yolo_udp: bool
    run_seconds: float | None


@dataclass(slots=True)
class BlackboxConfig:
    enabled: bool
    output_dir: str
    sample_hz: float
    flush_every: int
    rotate_mb: float
    keep_files: int
    include_perception: bool
    include_drone: bool
    include_gimbal: bool
    include_fused: bool
    include_commands: bool
    include_events: bool


@dataclass(slots=True)
class UiConfig:
    web_enabled: bool
    web_host: str
    web_port: int
    audit_log_path: str
    security_event_log_path: str
    auth_required: bool
    credential_env: str
    credential_file_env: str
    session_ttl_sec: float
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]


@dataclass(slots=True)
class ServiceControlConfig:
    restart_app_command: list[str]
    restart_yolo_command: list[str]


@dataclass(slots=True)
class ExecutorConfig:
    body_frame: int
    gimbal_roll_deg: float
    log_commands: bool
    send_commands: bool


@dataclass(slots=True)
class AppConfig:
    runtime: AppRuntimeConfig
    blackbox: BlackboxConfig
    ui: UiConfig
    services_control: ServiceControlConfig
    telemetry: TelemetryConfig
    yolo_command: YoloCommandConfig
    executor: ExecutorConfig
    start_send_commands: bool = False


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"unknown {path} field(s): {', '.join(sorted(unknown))}")


def _bool(data: dict[str, Any], name: str, default: bool) -> bool:
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a bool")
    return value


def _to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _load_yaml(path: str) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("app config must be a mapping")
    return data


def _command_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("service restart command must be a list of strings")
    return list(value)


def _load_yolo_command_config(path: str) -> YoloCommandConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("YOLO config must be a mapping")
    ip = str(data.get("command_ip", "127.0.0.1"))
    enabled = _bool(data, "command_enabled", True)
    try: loopback = ipaddress.ip_address(ip).is_loopback
    except ValueError: loopback = ip == "localhost"
    if enabled and not loopback:
        raise ValueError("YOLO command endpoint must be loopback unless an authenticated transport is configured")
    return YoloCommandConfig(
        ip=ip,
        port=int(data.get("command_port", 5006)),
        enabled=enabled,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UAV Action Mission application runtime")
    parser.add_argument("--app-config", default=str(ROOT_DIR / "config" / "app.yaml"))
    parser.add_argument("--telemetry-config", default=str(ROOT_DIR / "config" / "telemetry.yaml"))
    parser.add_argument("--yolo-config", default=str(ROOT_DIR / "config" / "yolo.yaml"))
    parser.add_argument("--yolo-udp-ip")
    parser.add_argument("--yolo-udp-port", type=int)
    parser.add_argument("--loop-hz", type=float)
    parser.add_argument("--perception-timeout-sec", type=float)
    parser.add_argument("--print-rate-hz", type=float)
    parser.add_argument("--require-gimbal-feedback", type=_to_bool)
    parser.add_argument("--log-level")
    parser.add_argument("--send-commands", type=_to_bool)
    parser.add_argument("--connect-telemetry", dest="connect_telemetry", action="store_true", default=None)
    parser.add_argument("--no-telemetry", dest="connect_telemetry", action="store_false")
    parser.add_argument("--no-yolo-udp", action="store_true")
    parser.add_argument("--ui", dest="ui_enabled", action="store_true", default=None)
    parser.add_argument("--no-ui", dest="ui_enabled", action="store_false")
    parser.add_argument("--run-seconds", type=float)
    parser.add_argument("--blackbox-enabled", type=_to_bool)
    parser.add_argument("--blackbox-output-dir")
    return parser


def load_app_config(args: argparse.Namespace) -> AppConfig:
    data = _load_yaml(args.app_config)
    _reject_unknown(data, {"runtime", "services", "ui", "services_control", "blackbox", "executor"}, "app config")
    runtime = _section(data, "runtime")
    services = _section(data, "services")
    ui = _section(data, "ui")
    blackbox = _section(data, "blackbox")
    executor = _section(data, "executor")
    control = _section(data, "services_control")
    _reject_unknown(runtime, {"yolo_udp_ip", "yolo_udp_port", "yolo_max_datagram_bytes",
                              "yolo_max_detections", "yolo_tombstone_capacity", "loop_hz", "perception_timeout_sec",
                              "print_rate_hz", "require_gimbal_feedback", "run_seconds", "log_level"}, "runtime")
    _reject_unknown(services, {"connect_telemetry", "start_yolo_udp"}, "services")
    _reject_unknown(ui, {"web_enabled", "web_host", "web_port", "audit_log_path",
                         "security_event_log_path", "auth_required", "credential_env",
                         "credential_file_env", "session_ttl_sec", "allowed_hosts", "allowed_origins"}, "ui")
    _reject_unknown(blackbox, {"enabled", "output_dir", "sample_hz", "flush_every", "rotate_mb",
                               "keep_files", "include_perception", "include_drone", "include_gimbal",
                               "include_fused", "include_commands", "include_events"}, "blackbox")
    _reject_unknown(executor, {"body_frame", "gimbal_roll_deg", "log_commands", "send_commands"}, "executor")
    _reject_unknown(control, {"restart_app_command", "restart_yolo_command"}, "services_control")
    telemetry = load_telemetry_config(args.telemetry_config)

    requested_send = _bool(executor, "send_commands", False) if args.send_commands is None else args.send_commands
    # CLI can only make send effective when an Action/Mission separately gains
    # its per-run authorization; retain the repository-safe default here.
    send_commands = bool(requested_send)
    audit = Path(str(ui.get("audit_log_path", "runtime/logs/web_ui/audit.jsonl")))
    security = Path(str(ui.get("security_event_log_path", "runtime/logs/web_ui/security.jsonl")))
    if not audit.is_absolute(): audit = ROOT_DIR / audit
    if not security.is_absolute(): security = ROOT_DIR / security
    allowed_hosts = ui.get("allowed_hosts", ["127.0.0.1", "localhost", "[::1]"])
    allowed_origins = ui.get("allowed_origins", ["http://127.0.0.1:8080"])
    if not isinstance(allowed_hosts, list) or not isinstance(allowed_origins, list):
        raise ValueError("ui.allowed_hosts and ui.allowed_origins must be lists")
    yolo_udp_ip = args.yolo_udp_ip or str(runtime.get("yolo_udp_ip", "127.0.0.1"))
    start_yolo_udp = False if args.no_yolo_udp else _bool(services, "start_yolo_udp", True)
    try: yolo_udp_is_loopback = ipaddress.ip_address(yolo_udp_ip).is_loopback
    except ValueError: yolo_udp_is_loopback = yolo_udp_ip == "localhost"
    if start_yolo_udp and not yolo_udp_is_loopback:
        raise ValueError("YOLO perception endpoint must be loopback unless an authenticated transport is configured")
    yolo_max_datagram_bytes = int(runtime.get("yolo_max_datagram_bytes", 60_000))
    yolo_max_detections = int(runtime.get("yolo_max_detections", 128))
    yolo_tombstone_capacity = int(runtime.get("yolo_tombstone_capacity", 8))
    if not 512 <= yolo_max_datagram_bytes <= 65_507:
        raise ValueError("runtime.yolo_max_datagram_bytes must be in 512..65507")
    if not 1 <= yolo_max_detections <= 4096 or not 1 <= yolo_tombstone_capacity <= 1024:
        raise ValueError("YOLO detection/tombstone bounds are invalid")

    return AppConfig(
        runtime=AppRuntimeConfig(
            yolo_udp_ip=yolo_udp_ip,
            yolo_udp_port=args.yolo_udp_port if args.yolo_udp_port is not None else int(runtime.get("yolo_udp_port", 5005)),
            yolo_max_datagram_bytes=yolo_max_datagram_bytes,
            yolo_max_detections=yolo_max_detections,
            yolo_tombstone_capacity=yolo_tombstone_capacity,
            loop_hz=args.loop_hz if args.loop_hz is not None else float(runtime.get("loop_hz", 20.0)),
            perception_timeout_sec=args.perception_timeout_sec if args.perception_timeout_sec is not None else float(runtime.get("perception_timeout_sec", 1.0)),
            print_rate_hz=args.print_rate_hz if args.print_rate_hz is not None else float(runtime.get("print_rate_hz", 2.0)),
            require_gimbal_feedback=args.require_gimbal_feedback if args.require_gimbal_feedback is not None else _bool(runtime, "require_gimbal_feedback", True),
            log_level=args.log_level or str(runtime.get("log_level", "INFO")),
            ui_enabled=args.ui_enabled if args.ui_enabled is not None else _bool(ui, "web_enabled", True),
            connect_telemetry=(args.connect_telemetry if args.connect_telemetry is not None
                               else _bool(services, "connect_telemetry", False)),
            start_yolo_udp=start_yolo_udp,
            run_seconds=args.run_seconds if args.run_seconds is not None else runtime.get("run_seconds"),
        ),
        blackbox=BlackboxConfig(
            enabled=args.blackbox_enabled if args.blackbox_enabled is not None else _bool(blackbox, "enabled", True),
            output_dir=str(ROOT_DIR / str(args.blackbox_output_dir or blackbox.get("output_dir", "runtime/logs/blackbox"))),
            sample_hz=float(blackbox.get("sample_hz", 20)), flush_every=int(blackbox.get("flush_every", 20)),
            rotate_mb=float(blackbox.get("rotate_mb", 100)), keep_files=int(blackbox.get("keep_files", 20)),
            include_perception=_bool(blackbox, "include_perception", True), include_drone=_bool(blackbox, "include_drone", True),
            include_gimbal=_bool(blackbox, "include_gimbal", True), include_fused=_bool(blackbox, "include_fused", True),
            include_commands=_bool(blackbox, "include_commands", True), include_events=_bool(blackbox, "include_events", True),
        ),
        ui=UiConfig(args.ui_enabled if args.ui_enabled is not None else _bool(ui, "web_enabled", True), str(ui.get("web_host", "127.0.0.1")), int(ui.get("web_port", 8080)), str(audit), str(security), _bool(ui, "auth_required", True), str(ui.get("credential_env", "UAV_WEB_OPERATOR_PASSWORD")), str(ui.get("credential_file_env", "UAV_WEB_OPERATOR_PASSWORD_FILE")), float(ui.get("session_ttl_sec", 28800)), tuple(str(x) for x in allowed_hosts), tuple(str(x).rstrip("/") for x in allowed_origins)),
        services_control=ServiceControlConfig(_command_list(control.get("restart_app_command")), _command_list(control.get("restart_yolo_command"))),
        telemetry=telemetry, yolo_command=_load_yolo_command_config(args.yolo_config),
        executor=ExecutorConfig(int(executor.get("body_frame", 8)), float(executor.get("gimbal_roll_deg", 0.0)), _bool(executor, "log_commands", True), send_commands),
        start_send_commands=send_commands,
    )
