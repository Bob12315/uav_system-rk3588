from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from telemetry_link.models import DroneState, GimbalState

from fusion.fusion_manager import FusionManager
from fusion.models import FusionConfig, PerceptionTarget


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fusion debug runner")
    parser.add_argument(
        "--telemetry-config",
        default=str(Path(__file__).resolve().parent.parent / "telemetry_link" / "config.yaml"),
        help="Path to telemetry_link config.yaml",
    )
    parser.add_argument("--yolo-udp-ip", default="0.0.0.0")
    parser.add_argument("--yolo-udp-port", type=int, default=5005)
    parser.add_argument("--telemetry-udp-ip")
    parser.add_argument("--telemetry-udp-port", type=int)
    parser.add_argument("--perception-timeout-sec", type=float, default=1.0)
    parser.add_argument("--telemetry-timeout-sec", type=float, default=2.5)
    parser.add_argument("--print-rate-hz", type=float, default=1.0)
    parser.add_argument("--require-gimbal-feedback", action="store_true", default=False)
    parser.add_argument("--log-level", default="INFO")
    return parser


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def load_telemetry_debug_endpoint(path: str) -> tuple[str, int]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("telemetry config yaml must be a mapping")
    ip = str(data.get("state_udp_ip", "127.0.0.1"))
    port = int(data.get("state_udp_port", 5010))
    return ip, port


class YoloUdpReceiver(threading.Thread):
    def __init__(self, ip: str, port: int, stop_event: threading.Event) -> None:
        super().__init__(name="YoloUdpReceiver", daemon=True)
        self.stop_event = stop_event
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
        self.sock.settimeout(0.2)
        self._lock = threading.Lock()
        self._latest_target = PerceptionTarget()
        self._last_packet_time = 0.0
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload, _addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.logger.warning("drop invalid YOLO UDP payload: %s", exc)
                continue
            if not isinstance(data, dict):
                self.logger.warning("drop YOLO UDP payload because it is not a JSON object")
                continue
            target = self._decode_target(data)
            with self._lock:
                self._latest_target = target
                self._last_packet_time = time.time()

    def get_latest_target(self, now: float, timeout_sec: float) -> PerceptionTarget:
        with self._lock:
            target = replace(self._latest_target)
            last_packet_time = self._last_packet_time
        if last_packet_time <= 0 or (now - last_packet_time) > timeout_sec:
            target.target_valid = False
            target.tracking_state = "lost"
            target.ex = 0.0
            target.ey = 0.0
        return target

    def close(self) -> None:
        self.sock.close()

    def _decode_target(self, data: dict[str, Any]) -> PerceptionTarget:
        return PerceptionTarget(
            timestamp=float(data.get("timestamp", 0.0)),
            frame_id=int(data.get("frame_id", 0)),
            target_valid=bool(data.get("target_valid", False)),
            tracking_state=str(data.get("tracking_state", "lost")),
            track_id=int(data.get("track_id", -1)),
            class_name=str(data.get("class_name", "")),
            confidence=float(data.get("confidence", 0.0)),
            cx=float(data.get("cx", 0.0)),
            cy=float(data.get("cy", 0.0)),
            w=float(data.get("w", 0.0)),
            h=float(data.get("h", 0.0)),
            image_width=float(data.get("image_width", 0.0)),
            image_height=float(data.get("image_height", 0.0)),
            target_size=float(data.get("target_size", 0.0)),
            ex=float(data.get("ex", 0.0)),
            ey=float(data.get("ey", 0.0)),
            lost_count=int(data.get("lost_count", 0)),
        )


class TelemetryStateUdpReceiver(threading.Thread):
    def __init__(self, ip: str, port: int, stop_event: threading.Event) -> None:
        super().__init__(name="TelemetryStateUdpReceiver", daemon=True)
        self.stop_event = stop_event
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
        self.sock.settimeout(0.2)
        self._lock = threading.Lock()
        self._latest_drone = DroneState()
        self._latest_gimbal = GimbalState()
        self._last_packet_time = 0.0
        self._active_source = ""
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload, _addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.logger.warning("drop invalid telemetry UDP payload: %s", exc)
                continue
            if not isinstance(data, dict):
                self.logger.warning("drop telemetry UDP payload because it is not a JSON object")
                continue
            try:
                drone = DroneState(**dict(data.get("drone", {})))
                gimbal = GimbalState(**dict(data.get("gimbal", {})))
            except TypeError as exc:
                self.logger.warning("drop telemetry UDP payload because decode failed: %s", exc)
                continue
            with self._lock:
                self._latest_drone = drone
                self._latest_gimbal = gimbal
                self._active_source = str(data.get("active_source", ""))
                self._last_packet_time = time.time()

    def get_latest(self, now: float, timeout_sec: float) -> tuple[DroneState, GimbalState, str, bool]:
        with self._lock:
            drone = replace(self._latest_drone)
            gimbal = replace(self._latest_gimbal)
            active_source = self._active_source
            last_packet_time = self._last_packet_time
        telemetry_fresh = bool(last_packet_time > 0 and (now - last_packet_time) <= timeout_sec)
        if not telemetry_fresh:
            drone.connected = False
            drone.stale = True
            drone.control_allowed = False
            drone.attitude_valid = False
            drone.velocity_valid = False
            drone.altitude_valid = False
            drone.battery_valid = False
            drone.global_position_valid = False
            drone.relative_alt_valid = False
            drone.local_position_valid = False
            gimbal.gimbal_valid = False
        return drone, gimbal, active_source, telemetry_fresh

    def close(self) -> None:
        self.sock.close()


def main() -> int:
    args = build_arg_parser().parse_args()
    telemetry_udp_ip, telemetry_udp_port = load_telemetry_debug_endpoint(args.telemetry_config)
    if args.telemetry_udp_ip:
        telemetry_udp_ip = args.telemetry_udp_ip
    if args.telemetry_udp_port is not None:
        telemetry_udp_port = args.telemetry_udp_port

    setup_logging(args.log_level)
    logger = logging.getLogger("fusion_debug")
    stop_event = threading.Event()

    def _handle_signal(signum, _frame) -> None:
        logger.info("received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "starting fusion debug yolo_udp=%s:%s telemetry_udp=%s:%s require_gimbal_feedback=%s",
        args.yolo_udp_ip,
        args.yolo_udp_port,
        telemetry_udp_ip,
        telemetry_udp_port,
        args.require_gimbal_feedback,
    )

    yolo_receiver = YoloUdpReceiver(args.yolo_udp_ip, args.yolo_udp_port, stop_event)
    telemetry_receiver = TelemetryStateUdpReceiver(telemetry_udp_ip, telemetry_udp_port, stop_event)
    fusion_manager = FusionManager(
        FusionConfig(require_gimbal_feedback=bool(args.require_gimbal_feedback))
    )

    yolo_receiver.start()
    telemetry_receiver.start()
    sleep_sec = 1.0 / max(args.print_rate_hz, 0.1)

    try:
        while not stop_event.is_set():
            now = time.time()
            perception = yolo_receiver.get_latest_target(now, args.perception_timeout_sec)
            drone, gimbal, active_source, telemetry_fresh = telemetry_receiver.get_latest(
                now, args.telemetry_timeout_sec
            )
            fused = fusion_manager.update(perception, drone, gimbal)
            logger.info(
                "active_source=%s telemetry_fresh=%s\n"
                "target: valid=%s locked=%s track_id=%s tracking_state=%s bbox_w=%s bbox_h=%s bbox_area=%s\n"
                "errors: cam=(%.3f,%.3f) body=(%.3f,%.3f)\n"
                "gimbal: valid=%s yaw=%.3f pitch=%.3f\n"
                "drone: rpy=(%.3f,%.3f,%.3f) yaw_rate=%.3f vel=(%.3f,%.3f,%.3f) alt=%.3f\n"
                "validity: vision_valid=%s drone_valid=%s control_allowed=%s control_enabled=%s state_valid=%s fusion_valid=%s\n"
                "src_ts perception=%.3f drone=%.3f gimbal=%.3f",
                active_source,
                telemetry_fresh,
                fused.target_valid,
                fused.target_locked,
                fused.track_id,
                fused.tracking_state,
                fused.bbox_w,
                fused.bbox_h,
                fused.bbox_area,
                fused.ex_cam,
                fused.ey_cam,
                fused.ex_body,
                fused.ey_body,
                fused.gimbal_valid,
                fused.gimbal_yaw,
                fused.gimbal_pitch,
                fused.roll,
                fused.pitch,
                fused.yaw,
                fused.yaw_rate,
                fused.vx,
                fused.vy,
                fused.vz,
                fused.altitude,
                fused.vision_valid,
                fused.drone_valid,
                fused.control_allowed,
                fused.control_enabled,
                fused.state_valid,
                fused.fusion_valid,
                fused.perception_timestamp,
                fused.drone_timestamp,
                fused.gimbal_timestamp,
            )
            time.sleep(sleep_sec)
    finally:
        stop_event.set()
        yolo_receiver.close()
        telemetry_receiver.close()
        logger.info("fusion debug stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
