from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
TELEMETRY_DIR = ROOT_DIR / "telemetry_link"
for path in (str(ROOT_DIR), str(TELEMETRY_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from .command_dispatcher import dispatch_text_command
    from .config import load_config
    from .link_manager import LinkManager
    from .state_publisher import StatePublisher
except ImportError:  # pragma: no cover - supports direct script execution
    from command_dispatcher import dispatch_text_command
    from config import load_config
    from link_manager import LinkManager
    from state_publisher import StatePublisher
from uav_ui.terminal_ui import run_terminal_ui
from utils import setup_logging


def main() -> int:
    cfg = load_config()
    ui_log_file = str(Path(__file__).with_name("telemetry_link_ui.log")) if cfg.ui_enabled else None
    setup_logging(cfg.log_level, ui_log_file)
    logger = logging.getLogger("telemetry_link")
    manager = LinkManager(cfg)
    stop_event = threading.Event()
    state_publisher = StatePublisher(cfg.state_udp_ip, cfg.state_udp_port) if cfg.state_udp_enabled else None

    def _stdin_command_loop() -> None:
        while not stop_event.is_set():
            line = sys.stdin.readline()
            if not line:
                time.sleep(0.1)
                continue
            command = line.strip()
            result = dispatch_text_command(manager, command, logger)
            if not result.ok:
                logger.warning(result.message)

    def _publish_state_once() -> None:
        if state_publisher is None:
            return
        state = manager.get_latest_drone_state()
        gimbal = manager.get_latest_gimbal_state()
        link = manager.get_link_status()
        active_source = manager.get_active_source()
        state_publisher.publish(state, gimbal, link, active_source)

    def _state_publish_loop() -> None:
        while not stop_event.is_set():
            _publish_state_once()
            if stop_event.wait(1.0):
                break

    def _handle_signal(signum, frame) -> None:
        logger.info("received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stop_event.is_set():
        try:
            logger.info(
                "starting telemetry link service data_source=%s active_source=%s",
                cfg.data_source,
                cfg.active_source,
            )
            manager.start()
            break
        except Exception as exc:
            logger.warning("start failed: %s; retry in %.1fs", exc, cfg.reconnect_interval_sec)
            time.sleep(cfg.reconnect_interval_sec)

    try:
        if cfg.ui_enabled:
            state_publish_thread = threading.Thread(name="StatePublishLoop", target=_state_publish_loop, daemon=True)
            state_publish_thread.start()
            run_terminal_ui(manager, stop_event)
        else:
            command_thread = threading.Thread(name="StdinCommandLoop", target=_stdin_command_loop, daemon=True)
            command_thread.start()
            while not stop_event.is_set():
                state = manager.get_latest_drone_state()
                gimbal = manager.get_latest_gimbal_state()
                link = manager.get_link_status()
                active_source = manager.get_active_source()
                _publish_state_once()
                logger.info(
                    "source=%s active_source=%s link=%s reconnecting=%s connected=%s stale=%s mode=%s control_allowed=%s armed=%s\n"
                    "att_valid=%s rpy=(%.2f,%.2f,%.2f) rates=(%.2f,%.2f,%.2f)\n"
                    "alt_valid=%s alt=%.2f rel_alt=%.2f\n"
                    "vel_valid=%s vel=(%.2f,%.2f,%.2f) vel_src=%s vel_q=%s\n"
                    "global_valid=%s pos=(%.7f,%.7f)\n"
                    "batt_valid=%s batt=%.2fV batt_rem=%s gps_fix=%s sats=%s\n"
                    "gimbal_valid=%s gimbal_rpy=(%.2f,%.2f,%.2f)\n"
                    "hb_age=%.2fs rx_age=%.2fs",
                    active_source,
                    active_source,
                    link.status_text,
                    link.reconnecting,
                    state.connected,
                    state.stale,
                    state.mode,
                    state.control_allowed,
                    state.armed,
                    state.attitude_valid,
                    state.roll,
                    state.pitch,
                    state.yaw,
                    state.roll_rate,
                    state.pitch_rate,
                    state.yaw_rate,
                    state.altitude_valid,
                    state.altitude,
                    state.relative_altitude,
                    state.velocity_valid,
                    state.vx,
                    state.vy,
                    state.vz,
                    state.velocity_source,
                    state.velocity_quality,
                    state.global_position_valid,
                    state.lat,
                    state.lon,
                    state.battery_valid,
                    state.battery_voltage,
                    state.battery_remaining,
                    state.gps_fix_type,
                    state.satellites_visible,
                    gimbal.gimbal_valid,
                    gimbal.roll,
                    gimbal.pitch,
                    gimbal.yaw,
                    state.hb_age_sec,
                    state.rx_age_sec,
                )
                time.sleep(1.0)
    finally:
        if state_publisher is not None:
            state_publisher.close()
        manager.stop()
        logger.info("telemetry link service stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
