from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import replace
from typing import Any

from app.app_config import AppConfig
from fusion.fusion_manager import FusionManager
from fusion.models import FusionConfig, PerceptionTarget, SceneDetections, SceneObject
from telemetry_link.link_manager import LinkManager
from telemetry_link.models import DroneState, GimbalState, LinkStatus
from telemetry_link.config import TelemetryConfig


class YoloUdpReceiver(threading.Thread):
    def __init__(self, ip: str, port: int, stop_event: threading.Event) -> None:
        super().__init__(name="AppYoloUdpReceiver", daemon=True)
        self.stop_event = stop_event
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
        self.sock.settimeout(0.2)
        self._lock = threading.Lock()
        self._latest_target = PerceptionTarget()
        self._latest_scene = SceneDetections()
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
            scene = self._decode_scene(data)
            with self._lock:
                self._latest_target = target
                self._latest_scene = scene
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

    def get_latest_scene(self, now: float, timeout_sec: float) -> SceneDetections:
        with self._lock:
            scene = replace(self._latest_scene)
            scene.detections = list(self._latest_scene.detections)
            last_packet_time = self._last_packet_time
        if last_packet_time <= 0 or (now - last_packet_time) > timeout_sec:
            return SceneDetections(timestamp=now)
        return scene

    def close(self) -> None:
        self.sock.close()

    @staticmethod
    def _decode_target(data: dict[str, Any]) -> PerceptionTarget:
        target_data = data.get("target", data)
        if not isinstance(target_data, dict):
            target_data = {}
        return PerceptionTarget(
            timestamp=float(target_data.get("timestamp", 0.0)),
            frame_id=int(target_data.get("frame_id", 0)),
            target_valid=bool(target_data.get("target_valid", False)),
            tracking_state=str(target_data.get("tracking_state", "lost")),
            track_id=int(target_data.get("track_id", -1)),
            class_name=str(target_data.get("class_name", "")),
            confidence=float(target_data.get("confidence", 0.0)),
            cx=float(target_data.get("cx", 0.0)),
            cy=float(target_data.get("cy", 0.0)),
            w=float(target_data.get("w", 0.0)),
            h=float(target_data.get("h", 0.0)),
            image_width=float(target_data.get("image_width", 0.0)),
            image_height=float(target_data.get("image_height", 0.0)),
            target_size=float(target_data.get("target_size", 0.0)),
            ex=float(target_data.get("ex", 0.0)),
            ey=float(target_data.get("ey", 0.0)),
            lost_count=int(target_data.get("lost_count", 0)),
        )

    @staticmethod
    def _decode_scene(data: dict[str, Any]) -> SceneDetections:
        scene_data = data.get("scene")
        if not isinstance(scene_data, dict):
            return SceneDetections()
        detections = scene_data.get("detections", [])
        if not isinstance(detections, list):
            detections = []
        return SceneDetections(
            timestamp=float(scene_data.get("timestamp", 0.0)),
            frame_id=int(scene_data.get("frame_id", 0)),
            image_width=int(scene_data.get("image_width", 0)),
            image_height=int(scene_data.get("image_height", 0)),
            detections=[
                YoloUdpReceiver._decode_scene_object(item)
                for item in detections
                if isinstance(item, dict)
            ],
            valid=True,
        )

    @staticmethod
    def _decode_scene_object(data: dict[str, Any]) -> SceneObject:
        track_id = data.get("track_id")
        return SceneObject(
            track_id=None if track_id is None else int(track_id),
            class_id=int(data.get("class_id", -1)),
            class_name=str(data.get("class_name", "")),
            confidence=float(data.get("confidence", 0.0)),
            x1=float(data.get("x1", 0.0)),
            y1=float(data.get("y1", 0.0)),
            x2=float(data.get("x2", 0.0)),
            y2=float(data.get("y2", 0.0)),
            cx=float(data.get("cx", 0.0)),
            cy=float(data.get("cy", 0.0)),
            w=float(data.get("w", 0.0)),
            h=float(data.get("h", 0.0)),
            ex=float(data.get("ex", 0.0)),
            ey=float(data.get("ey", 0.0)),
            target_size=float(data.get("target_size", 0.0)),
        )


class ServiceManager:
    def __init__(self, config: AppConfig, stop_event: threading.Event) -> None:
        self.config = config
        self.stop_event = stop_event
        self.logger = logging.getLogger(self.__class__.__name__)
        self.yolo_receiver: YoloUdpReceiver | None = None
        self.link_manager: LinkManager | None = None
        self.fusion_manager = FusionManager(
            FusionConfig(
                require_gimbal_feedback=bool(config.runtime.require_gimbal_feedback)
            )
        )

    def start(self) -> None:
        if self.config.runtime.start_yolo_udp:
            self.yolo_receiver = YoloUdpReceiver(
                self.config.runtime.yolo_udp_ip,
                self.config.runtime.yolo_udp_port,
                self.stop_event,
            )
            self.yolo_receiver.start()
            self.logger.info(
                "YOLO UDP receiver started at %s:%s",
                self.config.runtime.yolo_udp_ip,
                self.config.runtime.yolo_udp_port,
            )
        else:
            self.logger.info("YOLO UDP receiver disabled")

        if self.config.runtime.connect_telemetry:
            self.link_manager = LinkManager(self.config.telemetry)
            self.link_manager.start_background()
            self.logger.info("telemetry link manager starting in background")
        else:
            self.logger.info("telemetry link manager disabled for dry-run")

    def stop(self) -> None:
        if self.yolo_receiver is not None:
            self.yolo_receiver.close()
            self.yolo_receiver = None
        if self.link_manager is not None:
            self.link_manager.stop()
            self.link_manager = None

    def reconnect_telemetry(self, config: TelemetryConfig) -> None:
        if self.link_manager is not None:
            self.link_manager.stop()
        self.config.telemetry = config
        self.link_manager = LinkManager(config)
        self.link_manager.start_background()
        self.logger.info("telemetry link manager restarted from saved configuration")

    def get_perception(self, now: float) -> PerceptionTarget:
        if self.yolo_receiver is None:
            return PerceptionTarget(timestamp=now)
        return self.yolo_receiver.get_latest_target(
            now,
            self.config.runtime.perception_timeout_sec,
        )

    def get_scene_detections(self, now: float) -> SceneDetections:
        if self.yolo_receiver is None:
            return SceneDetections(timestamp=now)
        return self.yolo_receiver.get_latest_scene(
            now,
            self.config.runtime.perception_timeout_sec,
        )

    def get_drone_state(self) -> DroneState:
        if self.link_manager is None:
            return DroneState()
        return self.link_manager.get_latest_drone_state()

    def get_gimbal_state(self) -> GimbalState:
        if self.link_manager is None:
            return GimbalState()
        return self.link_manager.get_latest_gimbal_state()

    def get_link_status(self) -> LinkStatus | None:
        if self.link_manager is None:
            return None
        return self.link_manager.get_link_status()
