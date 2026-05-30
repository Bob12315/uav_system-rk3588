from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
TELEMETRY_DIR = ROOT_DIR / "telemetry_link"
for path in (str(ROOT_DIR), str(TELEMETRY_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from control.approach_controller import ApproachControllerConfig
    from control.body_controller import BodyControllerConfig
    from control.command_shaper import CommandShaperConfig as LegacyCommandShaperConfig
    from control.config import ControlConfig, ControlRuntimeConfig, load_config as load_control_config
    from control.control_executor import ControlExecutorConfig
    from control.control_input import ControlInputAdapterConfig
    from control.control_mode import ControlModeConfig
    from control.gimbal_controller import GimbalControllerConfig
except ModuleNotFoundError:
    @dataclass(slots=True)
    class ControlRuntimeConfig:
        yolo_udp_ip: str
        yolo_udp_port: int
        loop_hz: float
        perception_timeout_sec: float
        print_rate_hz: float
        require_gimbal_feedback: bool
        enable_gimbal_controller: bool
        enable_body_controller: bool
        enable_approach_controller: bool
        log_level: str

    @dataclass(slots=True)
    class ControlInputAdapterConfig:
        dt_default: float
        dt_min: float
        dt_max: float
        stable_hold_s: float
        age_invalid_value: float
        ex_cam_tau_s: float
        ey_cam_tau_s: float
        ex_body_tau_s: float
        ey_body_tau_s: float
        gimbal_yaw_tau_s: float
        gimbal_pitch_tau_s: float
        target_size_tau_s: float

    @dataclass(slots=True)
    class ControlModeConfig:
        max_vision_age_s: float
        max_drone_age_s: float
        max_gimbal_age_s: float
        yaw_align_thresh_rad: float
        overhead_entry_target_size_thresh: float
        overhead_entry_pitch_rad: float
        overhead_entry_pitch_tol_rad: float
        overhead_entry_yaw_tol_rad: float
        overhead_entry_hold_s: float
        overhead_exit_target_size_drop: float
        require_target_locked_for_body: bool
        require_target_stable_for_approach: bool
        require_yaw_aligned_for_approach: bool
        require_gimbal_fresh_for_gimbal: bool
        require_gimbal_fresh_for_body: bool
        require_gimbal_fresh_for_approach: bool

    @dataclass(slots=True)
    class GimbalControllerConfig:
        kp_yaw: float
        kp_pitch: float
        ki_yaw: float
        ki_pitch: float
        kd_yaw: float
        kd_pitch: float
        use_derivative: bool
        overhead_downward_pitch_rad: float
        lost_target_recenter_enabled: bool
        lost_target_recenter_timeout_sec: float
        lost_target_recenter_pitch_deg: float
        lost_target_recenter_yaw_deg: float

    @dataclass(slots=True)
    class BodyControllerConfig:
        kp_vy: float
        kd_vy: float
        use_derivative_vy: bool
        kp_yaw: float
        kd_yaw: float
        use_derivative_yaw: bool

    @dataclass(slots=True)
    class ApproachControllerConfig:
        target_size_ref: float
        kp_vx: float
        kd_vx: float
        use_derivative: bool
        allow_backward: bool

    @dataclass(slots=True)
    class LegacyCommandShaperConfig:
        max_vx: float
        max_vy: float
        max_yaw_rate: float
        max_gimbal_yaw_rate: float
        max_gimbal_pitch_rate: float
        max_vx_rate: float
        max_vy_rate: float
        max_yaw_rate_rate: float
        max_gimbal_yaw_rate_rate: float
        max_gimbal_pitch_rate_rate: float
        smooth_to_zero_when_disabled: bool
        dt_min: float

    @dataclass(slots=True)
    class ControlExecutorConfig:
        body_frame: int
        gimbal_roll_deg: float
        log_commands: bool
        send_commands: bool

    @dataclass(slots=True)
    class ControlConfig:
        runtime: ControlRuntimeConfig
        input_adapter: ControlInputAdapterConfig
        mode: ControlModeConfig
        gimbal: GimbalControllerConfig
        body: BodyControllerConfig
        approach: ApproachControllerConfig
        shaper: LegacyCommandShaperConfig
        executor: ControlExecutorConfig

    def load_control_config(_argv: list[str]) -> ControlConfig:
        raise RuntimeError("legacy control config is unavailable because control/ is not installed")
from missions.visual_tracking.stages.approach_track.config import (
    ApproachBodyConfig,
    ApproachForwardConfig,
    ApproachGimbalConfig,
    ApproachTrackConfig,
)
from missions.common.control.command_shaper import CommandShaperConfig
from missions.common.control.debug_config import StageDebugConfig
from missions.common.control.executor import FlightCommandExecutorConfig
from missions.common.control.input_adapter import InputAdapterConfig
from missions.visual_tracking.stages.overhead_hold.config import (
    OverheadApproachConfig,
    OverheadBodyConfig,
    OverheadGimbalConfig,
    OverheadHoldConfig,
)
from app.mission_manager import MissionManagerConfig
from telemetry_link.config import EndpointConfig, TelemetryConfig
from uav_ui.yolo_command_client import YoloCommandConfig


@dataclass(slots=True)
class AppRuntimeConfig:
    yolo_udp_ip: str
    yolo_udp_port: int
    loop_hz: float
    perception_timeout_sec: float
    print_rate_hz: float
    require_gimbal_feedback: bool
    log_level: str
    ui_enabled: bool
    connect_telemetry: bool
    start_yolo_udp: bool
    run_seconds: float | None
    lost_target_recenter_enabled: bool
    lost_target_recenter_timeout_sec: float
    lost_target_recenter_pitch_deg: float
    lost_target_recenter_yaw_deg: float


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
    terminal_enabled: bool
    web_host: str
    web_port: int
    audit_log_path: str


@dataclass(slots=True)
class ServiceControlConfig:
    restart_app_command: list[str]
    restart_yolo_command: list[str]


@dataclass(slots=True)
class AppConfig:
    runtime: AppRuntimeConfig
    blackbox: BlackboxConfig
    ui: UiConfig
    services_control: ServiceControlConfig
    control: ControlConfig
    telemetry: TelemetryConfig
    yolo_command: YoloCommandConfig
    mission_name: str
    mission_settings: dict[str, Any]
    input_adapter: InputAdapterConfig
    mission: MissionManagerConfig
    approach_track: ApproachTrackConfig
    overhead_hold: OverheadHoldConfig
    shaper: CommandShaperConfig
    executor: FlightCommandExecutorConfig
    debug: StageDebugConfig
    mission_config_path: str | None
    start_gimbal: bool
    start_body: bool
    start_approach: bool
    start_send_commands: bool


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refactored UAV control app runtime")
    parser.add_argument("--app-config", default=str(ROOT_DIR / "config" / "app.yaml"))
    parser.add_argument(
        "--mission-config",
        default=None,
        help="Path to mission config yaml; defaults to missions/<mission_name>/config.yaml.",
    )
    parser.add_argument(
        "--control-config",
        default=None,
        help="Legacy control config fallback. New app runtime reads config/app.yaml by default.",
    )
    parser.add_argument(
        "--telemetry-config",
        default=str(ROOT_DIR / "config" / "telemetry.yaml"),
        help="Path to telemetry config yaml",
    )
    parser.add_argument(
        "--yolo-config",
        default=str(ROOT_DIR / "yolo_app" / "config.yaml"),
        help="Path to yolo_app config.yaml for UI target commands",
    )
    parser.add_argument("--yolo-udp-ip")
    parser.add_argument("--yolo-udp-port", type=int)
    parser.add_argument("--loop-hz", type=float)
    parser.add_argument("--perception-timeout-sec", type=float)
    parser.add_argument("--print-rate-hz", type=float)
    parser.add_argument("--require-gimbal-feedback", type=_to_bool)
    parser.add_argument("--log-level")
    parser.add_argument("--send-commands", type=_to_bool)
    parser.add_argument("--force-mode")
    parser.add_argument(
        "--mission-name",
        default=None,
        help="Mission plugin name to run; defaults to visual_tracking.",
    )
    parser.add_argument(
        "--start-auto-control",
        action="store_true",
        help="Start controllers; command sending still follows --send-commands/config executor.send_commands.",
    )
    parser.add_argument(
        "--connect-telemetry",
        action="store_true",
        help="Connect telemetry services. Default app startup is dry-run without MAVLink.",
    )
    parser.add_argument(
        "--no-yolo-udp",
        action="store_true",
        help="Do not bind the YOLO UDP receiver; use an empty perception target.",
    )
    parser.add_argument("--ui", dest="ui_enabled", action="store_true", default=None)
    parser.add_argument("--no-ui", dest="ui_enabled", action="store_false")
    parser.add_argument(
        "--run-seconds",
        type=float,
        help="Stop automatically after this many seconds; useful for smoke tests.",
    )
    parser.add_argument("--blackbox-enabled", type=_to_bool)
    parser.add_argument("--blackbox-output-dir")
    return parser


def load_app_config(args: argparse.Namespace) -> AppConfig:
    if args.control_config and not Path(args.app_config).exists():
        return _load_legacy_app_config(args)

    app_config_path = Path(args.app_config)
    app_data = _load_yaml(args.app_config)
    app_mission_data = _section(app_data, "mission")
    mission_name_hint = _resolve_mission_name(args, app_mission_data, app_mission_data)
    mission_config_path = _resolve_mission_config_path(
        args,
        app_mission_data,
        app_config_path,
        mission_name_hint,
    )
    mission_file_data = _load_yaml_if_exists(mission_config_path)
    mission_data = _normalize_mission_config(
        mission_file_data if mission_file_data else app_mission_data
    )
    mission_name = _resolve_mission_name(args, app_mission_data, mission_data)
    if not mission_file_data and mission_config_path:
        mission_config_path = _resolve_mission_config_path(
            args,
            app_mission_data,
            app_config_path,
            mission_name,
        )
        mission_file_data = _load_yaml_if_exists(mission_config_path)
        mission_data = _normalize_mission_config(
            mission_file_data if mission_file_data else app_mission_data
        )
    telemetry_cfg = load_telemetry_config(args.telemetry_config)
    yolo_command_cfg = load_yolo_command_config(args.yolo_config)

    runtime_data = _section(app_data, "runtime")
    services_data = _section(app_data, "services")
    ui_data = _section(app_data, "ui")
    services_control_data = _section(app_data, "services_control")
    blackbox_data = _section(app_data, "blackbox")
    recovery_data = _normalize_recovery_config(
        mission_file_data if mission_file_data else app_data,
        runtime_data,
    )
    executor_data = _section(app_data, "executor")

    input_adapter_cfg = _build_input_adapter_config(_section(mission_data, "input_adapter"))
    mission_cfg = _build_mission_manager_config(mission_data)
    approach_track_cfg = _build_approach_track_config(mission_data, mission_data)
    overhead_hold_cfg = _build_overhead_hold_config(mission_data, mission_data)
    shaper_cfg = _build_shaper_config(_section(mission_data, "shaper"))
    executor_cfg = _build_executor_config(executor_data)
    debug_cfg = StageDebugConfig()

    send_commands = executor_cfg.send_commands
    if args.send_commands is not None:
        send_commands = bool(args.send_commands)
    if not args.start_auto_control and args.send_commands is None:
        send_commands = False
    if args.force_mode:
        debug_cfg.force_mode = args.force_mode

    connect_telemetry = _cfg_bool(
        services_data,
        "connect_telemetry",
        _cfg_bool(runtime_data, "connect_telemetry", False),
        "services",
    )
    connect_telemetry = bool(connect_telemetry or args.connect_telemetry or args.start_auto_control)
    ui_enabled = _cfg_bool(
        services_data,
        "ui_enabled",
        _cfg_bool(runtime_data, "ui_enabled", telemetry_cfg.ui_enabled),
        "services",
    )
    if args.ui_enabled is not None:
        ui_enabled = bool(args.ui_enabled)
    terminal_enabled = _cfg_bool(ui_data, "terminal_enabled", ui_enabled, "ui")
    if args.ui_enabled is not None:
        terminal_enabled = bool(args.ui_enabled)
    audit_log_path = Path(str(ui_data.get("audit_log_path", "logs/web_ui/audit.jsonl"))).expanduser()
    if not audit_log_path.is_absolute():
        audit_log_path = ROOT_DIR / audit_log_path
    ui_cfg = UiConfig(
        web_enabled=_cfg_bool(ui_data, "web_enabled", False, "ui"),
        terminal_enabled=terminal_enabled,
        web_host=str(ui_data.get("web_host", "0.0.0.0")),
        web_port=int(ui_data.get("web_port", 8080)),
        audit_log_path=str(audit_log_path),
    )
    if args.ui_enabled is False:
        ui_cfg.web_enabled = False
    service_control_cfg = ServiceControlConfig(
        restart_app_command=_command_list(services_control_data.get("restart_app_command")),
        restart_yolo_command=_command_list(services_control_data.get("restart_yolo_command")),
    )

    runtime_cfg = AppRuntimeConfig(
        yolo_udp_ip=args.yolo_udp_ip or str(runtime_data.get("yolo_udp_ip", "0.0.0.0")),
        yolo_udp_port=(
            args.yolo_udp_port
            if args.yolo_udp_port is not None
            else int(runtime_data.get("yolo_udp_port", 5005))
        ),
        loop_hz=args.loop_hz if args.loop_hz is not None else float(runtime_data.get("loop_hz", 20.0)),
        perception_timeout_sec=(
            args.perception_timeout_sec
            if args.perception_timeout_sec is not None
            else float(runtime_data.get("perception_timeout_sec", 1.0))
        ),
        print_rate_hz=(
            args.print_rate_hz
            if args.print_rate_hz is not None
            else float(runtime_data.get("print_rate_hz", 2.0))
        ),
        require_gimbal_feedback=(
            args.require_gimbal_feedback
            if args.require_gimbal_feedback is not None
            else _cfg_bool(runtime_data, "require_gimbal_feedback", True)
        ),
        log_level=args.log_level or str(runtime_data.get("log_level", "INFO")),
        ui_enabled=terminal_enabled,
        connect_telemetry=connect_telemetry,
        start_yolo_udp=(
            False
            if args.no_yolo_udp
            else _cfg_bool(
                services_data,
                "start_yolo_udp",
                _cfg_bool(runtime_data, "start_yolo_udp", True),
                "services",
            )
        ),
        run_seconds=args.run_seconds if args.run_seconds is not None else runtime_data.get("run_seconds"),
        lost_target_recenter_enabled=_cfg_bool(
            recovery_data,
            "lost_target_recenter_enabled",
            True,
            "recovery.lost_target",
        ),
        lost_target_recenter_timeout_sec=float(
            recovery_data.get("lost_target_recenter_timeout_sec", 10.0)
        ),
        lost_target_recenter_pitch_deg=float(
            recovery_data.get("lost_target_recenter_pitch_deg", 0.0)
        ),
        lost_target_recenter_yaw_deg=float(
            recovery_data.get("lost_target_recenter_yaw_deg", 0.0)
        ),
    )
    if runtime_cfg.run_seconds is not None:
        runtime_cfg.run_seconds = float(runtime_cfg.run_seconds)
    blackbox_cfg = _build_blackbox_config(blackbox_data, args)

    runtime_compat_data = dict(runtime_data)
    runtime_compat_data.update(recovery_data)
    control_cfg = _build_control_compat(
        runtime_compat_data,
        mission_data,
        mission_data,
        executor_cfg,
    )
    executor_cfg.send_commands = bool(send_commands)

    return AppConfig(
        runtime=runtime_cfg,
        blackbox=blackbox_cfg,
        ui=ui_cfg,
        services_control=service_control_cfg,
        control=control_cfg,
        telemetry=telemetry_cfg,
        yolo_command=yolo_command_cfg,
        mission_name=mission_name,
        mission_settings=dict(mission_data),
        input_adapter=input_adapter_cfg,
        mission=mission_cfg,
        approach_track=approach_track_cfg,
        overhead_hold=overhead_hold_cfg,
        shaper=shaper_cfg,
        executor=executor_cfg,
        debug=debug_cfg,
        mission_config_path=mission_config_path,
        start_gimbal=bool(args.start_auto_control),
        start_body=bool(args.start_auto_control),
        start_approach=bool(args.start_auto_control),
        start_send_commands=bool(send_commands),
    )


def load_mission_stage_runtime_config(
    mission_config_path: str | None,
) -> tuple[InputAdapterConfig, ApproachTrackConfig, OverheadHoldConfig, CommandShaperConfig]:
    mission_data = _normalize_mission_config(_load_yaml_if_exists(mission_config_path))
    return (
        _build_input_adapter_config(_section(mission_data, "input_adapter")),
        _build_approach_track_config(mission_data, mission_data),
        _build_overhead_hold_config(mission_data, mission_data),
        _build_shaper_config(_section(mission_data, "shaper")),
    )

def load_telemetry_config(path: str) -> TelemetryConfig:
    merged = _load_yaml(path)

    def build_endpoint(name: str, data: dict[str, Any]) -> EndpointConfig:
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

    return TelemetryConfig(
        data_source=str(merged["data_source"]),
        active_source=str(merged["active_source"]),
        sitl=build_endpoint("sitl", dict(merged["sitl"])),
        real=build_endpoint("real", dict(merged["real"])),
        control_send_rate_hz=float(merged["control_send_rate_hz"]),
        action_cmd_retries=int(merged["action_cmd_retries"]),
        action_retry_interval_sec=float(merged["action_retry_interval_sec"]),
        heartbeat_timeout_sec=float(merged["heartbeat_timeout_sec"]),
        rx_timeout_sec=float(merged["rx_timeout_sec"]),
        reconnect_interval_sec=float(merged["reconnect_interval_sec"]),
        receiver_idle_sleep_sec=float(merged["receiver_idle_sleep_sec"]),
        sender_idle_sleep_sec=float(merged["sender_idle_sleep_sec"]),
        request_message_intervals=_strict_bool(
            merged["request_message_intervals"],
            "telemetry.request_message_intervals",
        ),
        message_interval_hz={
            str(k): float(v) for k, v in dict(merged.get("message_interval_hz", {})).items()
        },
        gimbal_mount_mode=int(merged.get("gimbal_mount_mode", 2)),
        gimbal_yaw_min_deg=float(merged.get("gimbal_yaw_min_deg", -180.0)),
        gimbal_yaw_max_deg=float(merged.get("gimbal_yaw_max_deg", 180.0)),
        gimbal_pitch_min_deg=float(merged.get("gimbal_pitch_min_deg", -180.0)),
        gimbal_pitch_max_deg=float(merged.get("gimbal_pitch_max_deg", 180.0)),
        state_udp_enabled=_cfg_bool(merged, "state_udp_enabled", True, "telemetry"),
        state_udp_ip=str(merged.get("state_udp_ip", "127.0.0.1")),
        state_udp_port=int(merged.get("state_udp_port", 5010)),
        ui_enabled=_cfg_bool(merged, "ui_enabled", False, "telemetry"),
        log_level=str(merged.get("log_level", "INFO")),
    )


def _build_blackbox_config(data: dict[str, Any], args: argparse.Namespace) -> BlackboxConfig:
    enabled = _cfg_bool(data, "enabled", False, "blackbox")
    if args.blackbox_enabled is not None:
        enabled = bool(args.blackbox_enabled)

    output_dir = str(data.get("output_dir", "logs/blackbox"))
    if args.blackbox_output_dir:
        output_dir = args.blackbox_output_dir
    output_path = Path(output_dir).expanduser()
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path

    return BlackboxConfig(
        enabled=enabled,
        output_dir=str(output_path),
        sample_hz=float(data.get("sample_hz", 20.0)),
        flush_every=max(1, int(data.get("flush_every", 20))),
        rotate_mb=float(data.get("rotate_mb", 100.0)),
        keep_files=max(0, int(data.get("keep_files", 20))),
        include_perception=_cfg_bool(data, "include_perception", True, "blackbox"),
        include_drone=_cfg_bool(data, "include_drone", True, "blackbox"),
        include_gimbal=_cfg_bool(data, "include_gimbal", True, "blackbox"),
        include_fused=_cfg_bool(data, "include_fused", True, "blackbox"),
        include_commands=_cfg_bool(data, "include_commands", True, "blackbox"),
        include_events=_cfg_bool(data, "include_events", True, "blackbox"),
    )


def _command_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("service restart command must be a list of strings")
    return list(value)


def load_yolo_command_config(path: str) -> YoloCommandConfig:
    merged = _load_yaml(path)
    command_ip = str(merged.get("command_ip", "127.0.0.1"))
    if command_ip in {"0.0.0.0", "::"}:
        command_ip = "127.0.0.1"
    return YoloCommandConfig(
        ip=command_ip,
        port=int(merged.get("command_port", 5006)),
        enabled=_cfg_bool(merged, "command_enabled", True, "yolo"),
    )


def _build_input_adapter_config(data: dict[str, Any]) -> InputAdapterConfig:
    return InputAdapterConfig(
        dt_default=float(data.get("dt_default", 0.02)),
        dt_min=float(data.get("dt_min", 0.001)),
        dt_max=float(data.get("dt_max", 0.5)),
        stable_hold_s=float(data.get("stable_hold_s", 0.3)),
        age_invalid_value=float(data.get("age_invalid_value", float("inf"))),
        ex_cam_tau_s=float(data.get("ex_cam_tau_s", 0.08)),
        ey_cam_tau_s=float(data.get("ey_cam_tau_s", 0.08)),
        ex_body_tau_s=float(data.get("ex_body_tau_s", 0.08)),
        ey_body_tau_s=float(data.get("ey_body_tau_s", 0.08)),
        gimbal_yaw_tau_s=float(data.get("gimbal_yaw_tau_s", 0.10)),
        gimbal_pitch_tau_s=float(data.get("gimbal_pitch_tau_s", 0.10)),
        target_size_tau_s=float(data.get("target_size_tau_s", 0.12)),
    )


def _build_approach_track_config(
    flight_data: dict[str, Any],
    mission_data: dict[str, Any],
) -> ApproachTrackConfig:
    mode = _section(flight_data, "approach_track")
    gates = _section(mode, "gates") if mode else mission_data
    gimbal = _section(mode, "gimbal") if mode else _section(flight_data, "gimbal")
    body = _section(mode, "body") if mode else _section(flight_data, "body")
    approach = _section(mode, "forward") if mode else _section(flight_data, "approach")
    return ApproachTrackConfig(
        gimbal=ApproachGimbalConfig(
            kp_yaw=float(gimbal.get("kp_yaw", 3.2)),
            kp_pitch=float(gimbal.get("kp_pitch", 1.8)),
            ki_yaw=float(gimbal.get("ki_yaw", 0.05)),
            ki_pitch=float(gimbal.get("ki_pitch", 0.03)),
            kd_yaw=float(gimbal.get("kd_yaw", 0.18)),
            kd_pitch=float(gimbal.get("kd_pitch", 0.12)),
            use_derivative=_cfg_bool(gimbal, "use_derivative", False, "gimbal"),
            deadband_x=float(gimbal.get("deadband_x", 0.01)),
            deadband_y=float(gimbal.get("deadband_y", 0.01)),
            center_hold_yaw_threshold=float(gimbal.get("center_hold_yaw_threshold", 0.018)),
            center_hold_pitch_threshold=float(gimbal.get("center_hold_pitch_threshold", 0.024)),
            integral_limit=float(gimbal.get("integral_limit", 0.25)),
            derivative_limit_yaw=_optional_float(gimbal.get("derivative_limit_yaw", 1.5)),
            derivative_limit_pitch=_optional_float(gimbal.get("derivative_limit_pitch", 1.0)),
            max_yaw_rate=float(gimbal.get("max_yaw_rate", 1.1)),
            max_pitch_rate=float(gimbal.get("max_pitch_rate", 0.85)),
            yaw_sign=float(gimbal.get("yaw_sign", 1.0)),
            pitch_sign=float(gimbal.get("pitch_sign", -1.0)),
            dt_min=float(gimbal.get("dt_min", 1e-3)),
        ),
        body=ApproachBodyConfig(
            kp_vy=float(body.get("kp_vy", 1.0)),
            kd_vy=float(body.get("kd_vy", 0.0)),
            use_derivative_vy=_cfg_bool(body, "use_derivative_vy", False, "body"),
            kp_yaw=float(body.get("kp_yaw", 1.2)),
            kp_ex_cam_yaw=float(body.get("kp_ex_cam_yaw", 0.0)),
            kd_yaw=float(body.get("kd_yaw", 0.0)),
            use_derivative_yaw=_cfg_bool(body, "use_derivative_yaw", False, "body"),
            deadband_ex_body=float(body.get("deadband_ex_body", 0.02)),
            deadband_gimbal_yaw=float(body.get("deadband_gimbal_yaw", 0.02)),
            yaw_rate_damping=float(body.get("yaw_rate_damping", 0.0)),
            yaw_step_rate=float(body.get("yaw_step_rate", 0.0)),
            max_vy=float(body.get("max_vy", 1.0)),
            max_yaw_rate=float(body.get("max_yaw_rate", 1.0)),
            vy_sign=float(body.get("vy_sign", 1.0)),
            yaw_sign=float(body.get("yaw_sign", 1.0)),
            dt_min=float(body.get("dt_min", 1e-3)),
        ),
        approach=ApproachForwardConfig(
            target_size_ref=float(approach.get("target_size_ref", 0.35)),
            kp_vx=float(approach.get("kp_vx", 1.0)),
            kd_vx=float(approach.get("kd_vx", 0.0)),
            use_derivative=_cfg_bool(approach, "use_derivative", False, "approach"),
            deadband_size=float(approach.get("deadband_size", 0.02)),
            ex_cam_slowdown_start=float(approach.get("ex_cam_slowdown_start", 0.15)),
            max_ex_cam_for_approach=float(approach.get("max_ex_cam_for_approach", 0.35)),
            max_forward_vx=float(approach.get("max_forward_vx", 0.8)),
            max_backward_vx=float(approach.get("max_backward_vx", 0.2)),
            vx_sign=float(approach.get("vx_sign", 1.0)),
            allow_backward=_cfg_bool(approach, "allow_backward", False, "approach"),
            min_valid_target_size=float(approach.get("min_valid_target_size", 0.01)),
            dt_min=float(approach.get("dt_min", 1e-3)),
        ),
        max_vision_age_s=float(mission_data.get("max_vision_age_s", 0.3)),
        max_drone_age_s=float(mission_data.get("max_drone_age_s", 0.3)),
        max_gimbal_age_s=float(mission_data.get("max_gimbal_age_s", 0.3)),
        require_target_locked_for_body=_cfg_bool(
            gates,
            "require_target_locked_for_body",
            True,
            "approach_track.gates",
        ),
        require_target_stable_for_approach=_cfg_bool(
            gates,
            "require_target_stable_for_approach",
            True,
            "approach_track.gates",
        ),
        require_yaw_aligned_for_approach=_cfg_bool(
            gates,
            "require_yaw_aligned_for_approach",
            True,
            "approach_track.gates",
        ),
        require_gimbal_fresh_for_gimbal=_cfg_bool(
            gates,
            "require_gimbal_fresh_for_gimbal",
            False,
            "approach_track.gates",
        ),
        require_gimbal_fresh_for_body=_cfg_bool(
            gates,
            "require_gimbal_fresh_for_body",
            True,
            "approach_track.gates",
        ),
        require_gimbal_fresh_for_approach=_cfg_bool(
            gates,
            "require_gimbal_fresh_for_approach",
            True,
            "approach_track.gates",
        ),
        yaw_align_thresh_rad=float(gates.get("yaw_align_thresh_rad", 0.35)),
        yaw_align_enter_thresh_rad=float(
            gates.get(
                "yaw_align_enter_thresh_rad",
                min(float(gates.get("yaw_align_thresh_rad", 0.35)), 0.15),
            )
        ),
        yaw_align_exit_thresh_rad=float(
            gates.get(
                "yaw_align_exit_thresh_rad",
                float(gates.get("yaw_align_thresh_rad", 0.35)),
            )
        ),
        yaw_align_hold_s=float(gates.get("yaw_align_hold_s", 0.4)),
        min_yaw_quality=float(gates.get("min_yaw_quality", 0.0)),
    )


def _build_overhead_hold_config(
    flight_data: dict[str, Any],
    mission_data: dict[str, Any],
) -> OverheadHoldConfig:
    mode = _section(flight_data, "overhead_hold")
    gates = _section(mode, "gates") if mode else mission_data
    gimbal = _section(mode, "gimbal") if mode else _section(flight_data, "gimbal")
    body = _section(mode, "lateral") if mode else _section(flight_data, "body")
    approach = _section(mode, "longitudinal") if mode else _section(flight_data, "approach")
    return OverheadHoldConfig(
        gimbal=OverheadGimbalConfig(
            downward_pitch_rad=float(
                gimbal.get(
                    "downward_pitch_rad",
                    gimbal.get("overhead_downward_pitch_rad", -1.5707963267948966),
                )
            ),
            deadband_yaw=float(gimbal.get("deadband_yaw", gimbal.get("overhead_deadband_yaw", 0.02))),
            deadband_pitch=float(
                gimbal.get(
                    "pitch_tolerance_rad",
                    gimbal.get("overhead_deadband_pitch", 0.03),
                )
            ),
            kp_yaw=float(gimbal.get("kp_yaw", gimbal.get("overhead_kp_yaw", 0.0))),
            kp_pitch=float(gimbal.get("kp_pitch", gimbal.get("overhead_kp_pitch", 1.5))),
            max_yaw_rate=float(gimbal.get("max_yaw_rate", gimbal.get("overhead_max_yaw_rate", 0.3))),
            max_pitch_rate=float(gimbal.get("max_pitch_rate", gimbal.get("overhead_max_pitch_rate", 0.8))),
            yaw_sign=float(gimbal.get("yaw_sign", 1.0)),
            pitch_sign=float(gimbal.get("pitch_sign", -1.0)),
        ),
        body=OverheadBodyConfig(
            kp_vy=float(body.get("kp_vy", body.get("overhead_kp_vy", 1.0))),
            kd_vy=float(body.get("kd_vy", body.get("overhead_kd_vy", 0.0))),
            use_derivative_vy=_cfg_bool(
                body,
                "use_derivative" if "use_derivative" in body else "overhead_use_derivative_vy",
                False,
                "overhead_hold.lateral",
            ),
            deadband_ex_cam=float(body.get("deadband_ex_cam", body.get("overhead_deadband_ex_cam", 0.02))),
            kp_yaw=float(body.get("kp_yaw", body.get("overhead_kp_yaw", 0.0))),
            deadband_yaw=float(body.get("deadband_yaw", body.get("overhead_deadband_yaw", 0.05))),
            max_vy=float(body.get("max_vy", 1.0)),
            max_yaw_rate=float(body.get("max_yaw_rate", 1.0)),
            vy_sign=float(body.get("vy_sign", 1.0)),
            yaw_sign=float(body.get("yaw_sign", 1.0)),
            dt_min=float(body.get("dt_min", 1e-3)),
        ),
        approach=OverheadApproachConfig(
            kp_vx=float(approach.get("kp_vx", approach.get("overhead_kp_vx", 1.0))),
            kd_vx=float(approach.get("kd_vx", approach.get("overhead_kd_vx", 0.0))),
            use_derivative=_cfg_bool(
                approach,
                "use_derivative" if "use_derivative" in approach else "overhead_use_derivative",
                False,
                "overhead_hold.longitudinal",
            ),
            deadband_ey_cam=float(
                approach.get("deadband_ey_cam", approach.get("overhead_deadband_ey_cam", 0.02))
            ),
            vx_sign=float(approach.get("vx_sign", approach.get("overhead_vx_sign", 1.0))),
            allow_backward=_cfg_bool(
                approach,
                "allow_backward" if "allow_backward" in approach else "overhead_allow_backward",
                False,
                "overhead_hold.longitudinal",
            ),
            max_forward_vx=float(approach.get("max_forward_vx", 0.8)),
            max_backward_vx=float(approach.get("max_backward_vx", 0.2)),
            dt_min=float(approach.get("dt_min", 1e-3)),
        ),
        max_vision_age_s=float(mission_data.get("max_vision_age_s", 0.3)),
        max_drone_age_s=float(mission_data.get("max_drone_age_s", 0.3)),
        max_gimbal_age_s=float(mission_data.get("max_gimbal_age_s", 0.3)),
        require_gimbal_fresh_for_gimbal=_cfg_bool(
            gates,
            "require_gimbal_fresh_for_gimbal",
            False,
            "overhead_hold.gates",
        ),
        require_gimbal_fresh_for_body=_cfg_bool(
            gates,
            "require_gimbal_fresh_for_body",
            True,
            "overhead_hold.gates",
        ),
        require_gimbal_fresh_for_approach=_cfg_bool(
            gates,
            "require_gimbal_fresh_for_approach",
            True,
            "overhead_hold.gates",
        ),
    )


def _build_shaper_config(data: dict[str, Any]) -> CommandShaperConfig:
    return CommandShaperConfig(
        max_vx=float(data.get("max_vx", 0.8)),
        max_vy=float(data.get("max_vy", 1.0)),
        max_vz=float(data.get("max_vz", 0.5)),
        max_yaw_rate=float(data.get("max_yaw_rate", 1.0)),
        max_gimbal_yaw_rate=float(data.get("max_gimbal_yaw_rate", 1.0)),
        max_gimbal_pitch_rate=float(data.get("max_gimbal_pitch_rate", 1.0)),
        max_vx_rate=float(data.get("max_vx_rate", 1.0)),
        max_vy_rate=float(data.get("max_vy_rate", 1.5)),
        max_vz_rate=float(data.get("max_vz_rate", 1.0)),
        max_yaw_rate_rate=float(data.get("max_yaw_rate_rate", 2.0)),
        max_gimbal_yaw_rate_rate=float(data.get("max_gimbal_yaw_rate_rate", 3.0)),
        max_gimbal_pitch_rate_rate=float(data.get("max_gimbal_pitch_rate_rate", 3.0)),
        smooth_to_zero_when_disabled=_cfg_bool(
            data,
            "smooth_to_zero_when_disabled",
            True,
            "shaper",
        ),
        dt_min=float(data.get("dt_min", 1e-3)),
    )


def _build_executor_config(data: dict[str, Any]) -> FlightCommandExecutorConfig:
    return FlightCommandExecutorConfig(
        body_frame=int(data.get("body_frame", 1)),
        gimbal_roll_deg=float(data.get("gimbal_roll_deg", 0.0)),
        log_commands=_cfg_bool(data, "log_commands", True, "executor"),
        send_commands=_cfg_bool(data, "send_commands", False, "executor"),
    )


def _build_mission_manager_config(data: dict[str, Any]) -> MissionManagerConfig:
    return MissionManagerConfig(
        initial_mode=str(data.get("initial_mode", "APPROACH_TRACK")),
        overhead_entry_target_size_thresh=float(
            data.get("overhead_entry_target_size_thresh", 0.30)
        ),
        overhead_entry_pitch_rad=float(
            data.get("overhead_entry_pitch_rad", -1.5707963267948966)
        ),
        overhead_entry_pitch_tol_rad=float(data.get("overhead_entry_pitch_tol_rad", 0.20)),
        overhead_entry_yaw_tol_rad=float(data.get("overhead_entry_yaw_tol_rad", 0.15)),
        overhead_entry_hold_s=float(data.get("overhead_entry_hold_s", 0.5)),
        overhead_exit_target_size_drop=float(
            data.get("overhead_exit_target_size_drop", 0.06)
        ),
        auto_switch_enabled=_cfg_bool(data, "auto_switch_enabled", True, "mission"),
    )


def _resolve_mission_name(
    args: argparse.Namespace,
    app_mission_data: dict[str, Any],
    mission_data: dict[str, Any],
) -> str:
    if args.mission_name:
        return str(args.mission_name).strip() or "visual_tracking"
    if "name" in mission_data:
        return str(mission_data.get("name") or "visual_tracking").strip() or "visual_tracking"
    if "name" in app_mission_data:
        return str(app_mission_data.get("name") or "visual_tracking").strip() or "visual_tracking"
    return "visual_tracking"


def _resolve_mission_config_path(
    args: argparse.Namespace,
    app_mission_data: dict[str, Any],
    app_config_path: Path,
    mission_name: str,
) -> str:
    path_value = args.mission_config
    if path_value is None:
        path_value = app_mission_data.get("config_path")
    if path_value is None:
        path_value = ROOT_DIR / "missions" / mission_name / "config.yaml"
    path = Path(str(path_value)).expanduser()
    if path.is_absolute():
        return str(path)

    app_relative = app_config_path.resolve().parent / path
    if app_relative.exists():
        return str(app_relative)
    return str(ROOT_DIR / path)


def _build_control_compat(
    runtime: dict[str, Any],
    mission: dict[str, Any],
    flight: dict[str, Any],
    executor: FlightCommandExecutorConfig,
) -> ControlConfig:
    input_adapter = _section(flight, "input_adapter")
    approach_track = _section(flight, "approach_track")
    gimbal = _section(approach_track, "gimbal") if approach_track else _section(flight, "gimbal")
    body = _section(approach_track, "body") if approach_track else _section(flight, "body")
    approach = (
        _section(approach_track, "forward")
        if approach_track
        else _section(flight, "approach")
    )
    shaper = _section(flight, "shaper")
    return ControlConfig(
        runtime=ControlRuntimeConfig(
            yolo_udp_ip=str(runtime.get("yolo_udp_ip", "0.0.0.0")),
            yolo_udp_port=int(runtime.get("yolo_udp_port", 5005)),
            loop_hz=float(runtime.get("loop_hz", 20.0)),
            perception_timeout_sec=float(runtime.get("perception_timeout_sec", 1.0)),
            print_rate_hz=float(runtime.get("print_rate_hz", 2.0)),
            require_gimbal_feedback=_cfg_bool(runtime, "require_gimbal_feedback", True, "runtime"),
            enable_gimbal_controller=_cfg_bool(runtime, "enable_gimbal_controller", True, "runtime"),
            enable_body_controller=_cfg_bool(runtime, "enable_body_controller", True, "runtime"),
            enable_approach_controller=_cfg_bool(runtime, "enable_approach_controller", True, "runtime"),
            log_level=str(runtime.get("log_level", "INFO")),
        ),
        input_adapter=ControlInputAdapterConfig(**asdict(_build_input_adapter_config(input_adapter))),
        mode=ControlModeConfig(
            max_vision_age_s=float(mission.get("max_vision_age_s", 0.3)),
            max_drone_age_s=float(mission.get("max_drone_age_s", 0.3)),
            max_gimbal_age_s=float(mission.get("max_gimbal_age_s", 0.3)),
            yaw_align_thresh_rad=float(mission.get("yaw_align_thresh_rad", 0.35)),
            overhead_entry_target_size_thresh=float(
                mission.get("overhead_entry_target_size_thresh", 0.30)
            ),
            overhead_entry_pitch_rad=float(
                mission.get("overhead_entry_pitch_rad", -1.5707963267948966)
            ),
            overhead_entry_pitch_tol_rad=float(mission.get("overhead_entry_pitch_tol_rad", 0.20)),
            overhead_entry_yaw_tol_rad=float(mission.get("overhead_entry_yaw_tol_rad", 0.15)),
            overhead_entry_hold_s=float(mission.get("overhead_entry_hold_s", 0.5)),
            overhead_exit_target_size_drop=float(
                mission.get("overhead_exit_target_size_drop", 0.06)
            ),
            require_target_locked_for_body=_cfg_bool(
                mission,
                "require_target_locked_for_body",
                True,
                "mission",
            ),
            require_target_stable_for_approach=_cfg_bool(
                mission,
                "require_target_stable_for_approach",
                True,
                "mission",
            ),
            require_yaw_aligned_for_approach=_cfg_bool(
                mission,
                "require_yaw_aligned_for_approach",
                True,
                "mission",
            ),
            require_gimbal_fresh_for_gimbal=_cfg_bool(
                mission,
                "require_gimbal_fresh_for_gimbal",
                False,
                "mission",
            ),
            require_gimbal_fresh_for_body=_cfg_bool(
                mission,
                "require_gimbal_fresh_for_body",
                True,
                "mission",
            ),
            require_gimbal_fresh_for_approach=_cfg_bool(
                mission,
                "require_gimbal_fresh_for_approach",
                True,
                "mission",
            ),
        ),
        gimbal=GimbalControllerConfig(
            kp_yaw=float(gimbal.get("kp_yaw", 3.2)),
            kp_pitch=float(gimbal.get("kp_pitch", 1.8)),
            ki_yaw=float(gimbal.get("ki_yaw", 0.05)),
            ki_pitch=float(gimbal.get("ki_pitch", 0.03)),
            kd_yaw=float(gimbal.get("kd_yaw", 0.18)),
            kd_pitch=float(gimbal.get("kd_pitch", 0.12)),
            use_derivative=_cfg_bool(gimbal, "use_derivative", False, "gimbal"),
            overhead_downward_pitch_rad=float(
                gimbal.get("overhead_downward_pitch_rad", -1.5707963267948966)
            ),
            lost_target_recenter_enabled=_cfg_bool(
                runtime,
                "lost_target_recenter_enabled",
                True,
                "runtime",
            ),
            lost_target_recenter_timeout_sec=float(
                runtime.get("lost_target_recenter_timeout_sec", 10.0)
            ),
            lost_target_recenter_pitch_deg=float(
                runtime.get("lost_target_recenter_pitch_deg", 0.0)
            ),
            lost_target_recenter_yaw_deg=float(runtime.get("lost_target_recenter_yaw_deg", 0.0)),
        ),
        body=BodyControllerConfig(
            kp_vy=float(body.get("kp_vy", 1.0)),
            kd_vy=float(body.get("kd_vy", 0.0)),
            use_derivative_vy=_cfg_bool(body, "use_derivative_vy", False, "body"),
            kp_yaw=float(body.get("kp_yaw", 1.2)),
            kd_yaw=float(body.get("kd_yaw", 0.0)),
            use_derivative_yaw=_cfg_bool(body, "use_derivative_yaw", False, "body"),
        ),
        approach=ApproachControllerConfig(
            target_size_ref=float(approach.get("target_size_ref", 0.35)),
            kp_vx=float(approach.get("kp_vx", 1.0)),
            kd_vx=float(approach.get("kd_vx", 0.0)),
            use_derivative=_cfg_bool(approach, "use_derivative", False, "approach"),
            allow_backward=_cfg_bool(approach, "allow_backward", False, "approach"),
        ),
        shaper=LegacyCommandShaperConfig(
            max_vx=float(shaper.get("max_vx", 0.8)),
            max_vy=float(shaper.get("max_vy", 1.0)),
            max_yaw_rate=float(shaper.get("max_yaw_rate", 1.0)),
            max_gimbal_yaw_rate=float(shaper.get("max_gimbal_yaw_rate", 1.0)),
            max_gimbal_pitch_rate=float(shaper.get("max_gimbal_pitch_rate", 1.0)),
            max_vx_rate=float(shaper.get("max_vx_rate", 1.0)),
            max_vy_rate=float(shaper.get("max_vy_rate", 1.5)),
            max_yaw_rate_rate=float(shaper.get("max_yaw_rate_rate", 2.0)),
            max_gimbal_yaw_rate_rate=float(shaper.get("max_gimbal_yaw_rate_rate", 3.0)),
            max_gimbal_pitch_rate_rate=float(shaper.get("max_gimbal_pitch_rate_rate", 3.0)),
            smooth_to_zero_when_disabled=_cfg_bool(
                shaper,
                "smooth_to_zero_when_disabled",
                True,
                "shaper",
            ),
            dt_min=float(shaper.get("dt_min", 1e-3)),
        ),
        executor=ControlExecutorConfig(
            body_frame=executor.body_frame,
            gimbal_roll_deg=executor.gimbal_roll_deg,
            log_commands=executor.log_commands,
            send_commands=executor.send_commands,
        ),
    )


def _load_legacy_app_config(args: argparse.Namespace) -> AppConfig:
    control_cfg = load_control_config(["--config", args.control_config])
    telemetry_cfg = load_telemetry_config(args.telemetry_config)
    yolo_command_cfg = load_yolo_command_config(args.yolo_config)
    executor_cfg = FlightCommandExecutorConfig(
        body_frame=control_cfg.executor.body_frame,
        gimbal_roll_deg=control_cfg.executor.gimbal_roll_deg,
        log_commands=control_cfg.executor.log_commands,
        send_commands=False,
    )
    return AppConfig(
        runtime=AppRuntimeConfig(
            yolo_udp_ip=args.yolo_udp_ip or control_cfg.runtime.yolo_udp_ip,
            yolo_udp_port=args.yolo_udp_port or control_cfg.runtime.yolo_udp_port,
            loop_hz=args.loop_hz or control_cfg.runtime.loop_hz,
            perception_timeout_sec=args.perception_timeout_sec
            or control_cfg.runtime.perception_timeout_sec,
            print_rate_hz=args.print_rate_hz or control_cfg.runtime.print_rate_hz,
            require_gimbal_feedback=args.require_gimbal_feedback
            if args.require_gimbal_feedback is not None
            else control_cfg.runtime.require_gimbal_feedback,
            log_level=args.log_level or control_cfg.runtime.log_level,
            ui_enabled=telemetry_cfg.ui_enabled if args.ui_enabled is None else args.ui_enabled,
            connect_telemetry=bool(args.connect_telemetry or args.start_auto_control),
            start_yolo_udp=not args.no_yolo_udp,
            run_seconds=args.run_seconds,
            lost_target_recenter_enabled=bool(control_cfg.gimbal.lost_target_recenter_enabled),
            lost_target_recenter_timeout_sec=float(control_cfg.gimbal.lost_target_recenter_timeout_sec),
            lost_target_recenter_pitch_deg=float(control_cfg.gimbal.lost_target_recenter_pitch_deg),
            lost_target_recenter_yaw_deg=float(control_cfg.gimbal.lost_target_recenter_yaw_deg),
        ),
        blackbox=_build_blackbox_config({}, args),
        ui=UiConfig(
            web_enabled=False,
            terminal_enabled=telemetry_cfg.ui_enabled if args.ui_enabled is None else bool(args.ui_enabled),
            web_host="0.0.0.0",
            web_port=8080,
            audit_log_path=str(ROOT_DIR / "logs" / "web_ui" / "audit.jsonl"),
        ),
        services_control=ServiceControlConfig([], []),
        control=control_cfg,
        telemetry=telemetry_cfg,
        yolo_command=yolo_command_cfg,
        mission_name="visual_tracking",
        mission_settings={},
        input_adapter=InputAdapterConfig(**asdict(control_cfg.input_adapter)),
        mission=MissionManagerConfig(
            overhead_entry_target_size_thresh=control_cfg.mode.overhead_entry_target_size_thresh,
            overhead_entry_pitch_rad=control_cfg.mode.overhead_entry_pitch_rad,
            overhead_entry_pitch_tol_rad=control_cfg.mode.overhead_entry_pitch_tol_rad,
            overhead_entry_yaw_tol_rad=control_cfg.mode.overhead_entry_yaw_tol_rad,
            overhead_entry_hold_s=control_cfg.mode.overhead_entry_hold_s,
            overhead_exit_target_size_drop=control_cfg.mode.overhead_exit_target_size_drop,
        ),
        approach_track=_build_approach_track_config_from_control(control_cfg),
        overhead_hold=_build_overhead_hold_config_from_control(control_cfg),
        shaper=CommandShaperConfig(
            max_vx=control_cfg.shaper.max_vx,
            max_vy=control_cfg.shaper.max_vy,
            max_yaw_rate=control_cfg.shaper.max_yaw_rate,
            max_gimbal_yaw_rate=control_cfg.shaper.max_gimbal_yaw_rate,
            max_gimbal_pitch_rate=control_cfg.shaper.max_gimbal_pitch_rate,
            max_vx_rate=control_cfg.shaper.max_vx_rate,
            max_vy_rate=control_cfg.shaper.max_vy_rate,
            max_yaw_rate_rate=control_cfg.shaper.max_yaw_rate_rate,
            max_gimbal_yaw_rate_rate=control_cfg.shaper.max_gimbal_yaw_rate_rate,
            max_gimbal_pitch_rate_rate=control_cfg.shaper.max_gimbal_pitch_rate_rate,
            smooth_to_zero_when_disabled=control_cfg.shaper.smooth_to_zero_when_disabled,
            dt_min=control_cfg.shaper.dt_min,
        ),
        executor=executor_cfg,
        debug=StageDebugConfig(force_mode=args.force_mode),
        mission_config_path=None,
        start_gimbal=bool(control_cfg.runtime.enable_gimbal_controller and args.start_auto_control),
        start_body=bool(control_cfg.runtime.enable_body_controller and args.start_auto_control),
        start_approach=bool(control_cfg.runtime.enable_approach_controller and args.start_auto_control),
        start_send_commands=False,
    )


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config yaml must be a mapping: {path}")
    return data


def _load_yaml_if_exists(path: str) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    return _load_yaml(path)


def _normalize_mission_config(data: dict[str, Any]) -> dict[str, Any]:
    if "freshness" not in data and "transitions" not in data:
        return dict(data)

    freshness = _section(data, "freshness")
    transitions = _section(data, "transitions")
    enter_overhead = _section(transitions, "approach_track_to_overhead_hold")
    exit_overhead = _section(transitions, "overhead_hold_to_approach_track")

    normalized = dict(data)
    normalized.update({
        "initial_mode": data.get("initial_mode", "APPROACH_TRACK"),
        "auto_switch_enabled": data.get("auto_switch_enabled", True),
        "max_vision_age_s": freshness.get("max_vision_age_s", 0.3),
        "max_drone_age_s": freshness.get("max_drone_age_s", 0.3),
        "max_gimbal_age_s": freshness.get("max_gimbal_age_s", 0.3),
        "overhead_entry_target_size_thresh": enter_overhead.get(
            "target_size_thresh",
            0.30,
        ),
        "overhead_entry_pitch_rad": enter_overhead.get(
            "gimbal_pitch_rad",
            -1.5707963267948966,
        ),
        "overhead_entry_pitch_tol_rad": enter_overhead.get(
            "gimbal_pitch_tol_rad",
            0.20,
        ),
        "overhead_entry_yaw_tol_rad": enter_overhead.get("gimbal_yaw_tol_rad", 0.15),
        "overhead_entry_hold_s": enter_overhead.get("hold_s", 0.5),
        "overhead_exit_target_size_drop": exit_overhead.get("target_size_drop", 0.06),
    })
    if "name" in data:
        normalized["name"] = data["name"]

    for key in (
        "yaw_align_thresh_rad",
        "require_target_locked_for_body",
        "require_target_stable_for_approach",
        "require_yaw_aligned_for_approach",
        "require_gimbal_fresh_for_gimbal",
        "require_gimbal_fresh_for_body",
        "require_gimbal_fresh_for_approach",
        "yaw_align_enter_thresh_rad",
        "yaw_align_exit_thresh_rad",
        "yaw_align_hold_s",
        "min_yaw_quality",
    ):
        if key in data:
            normalized[key] = data[key]
    return normalized


def _normalize_recovery_config(
    data: dict[str, Any],
    runtime_fallback: dict[str, Any],
) -> dict[str, Any]:
    recovery = _section(data, "recovery")
    lost_target = _section(recovery, "lost_target")
    if lost_target:
        return {
            "lost_target_recenter_enabled": lost_target.get(
                "recenter_gimbal_enabled",
                True,
            ),
            "lost_target_recenter_timeout_sec": lost_target.get("recenter_after_s", 10.0),
            "lost_target_recenter_pitch_deg": lost_target.get("recenter_pitch_deg", 0.0),
            "lost_target_recenter_yaw_deg": lost_target.get("recenter_yaw_deg", 0.0),
        }

    return {
        "lost_target_recenter_enabled": runtime_fallback.get(
            "lost_target_recenter_enabled",
            True,
        ),
        "lost_target_recenter_timeout_sec": runtime_fallback.get(
            "lost_target_recenter_timeout_sec",
            10.0,
        ),
        "lost_target_recenter_pitch_deg": runtime_fallback.get(
            "lost_target_recenter_pitch_deg",
            0.0,
        ),
        "lost_target_recenter_yaw_deg": runtime_fallback.get(
            "lost_target_recenter_yaw_deg",
            0.0,
        ),
    }


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    section = data.get(key, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"config section '{key}' must be a mapping")
    return dict(section)


def _cfg_bool(
    data: dict[str, Any],
    key: str,
    default: bool,
    section: str = "config",
) -> bool:
    if key not in data:
        return bool(default)
    return _strict_bool(data[key], f"{section}.{key}")


def _strict_bool(value: Any, path: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"invalid boolean for {path}: {value!r}")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _to_bool(value: str | bool) -> bool:
    try:
        return _strict_bool(value, "cli")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _build_approach_track_config_from_control(control_cfg: ControlConfig) -> ApproachTrackConfig:
    return _build_approach_track_config(
        {
            "gimbal": asdict(control_cfg.gimbal),
            "body": asdict(control_cfg.body),
            "approach": asdict(control_cfg.approach),
        },
        asdict(control_cfg.mode),
    )


def _build_overhead_hold_config_from_control(control_cfg: ControlConfig) -> OverheadHoldConfig:
    return _build_overhead_hold_config(
        {
            "gimbal": asdict(control_cfg.gimbal),
            "body": asdict(control_cfg.body),
            "approach": asdict(control_cfg.approach),
        },
        asdict(control_cfg.mode),
    )
