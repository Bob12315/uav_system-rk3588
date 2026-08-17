from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import replace
from typing import Any

from app.config import AppConfig
from fusion.fusion_manager import FusionManager
from fusion.models import FusionConfig, PerceptionTarget, SceneDetections, SceneObject
from telemetry_link.link_manager import LinkManager
from telemetry_link.models import DroneState, GimbalState, LinkStatus
from telemetry_link.config import TelemetryConfig
from telemetry_link.ports import LinkControlAdapter, VehicleCommandAdapter, VehicleStateAdapter
from contracts.perception_protocol import PERCEPTION_SCHEMA_VERSION
from contracts.platform.vehicle_state import VehicleStateSnapshot
from contracts.platform.perception import PerceptionHealthSnapshot
from application.perception_session import PerceptionSessionGate


class YoloUdpReceiver(threading.Thread):
    def __init__(self, ip: str, port: int, stop_event: threading.Event, *,
                 max_datagram_bytes: int = 60_000, max_detections: int = 128,
                 tombstone_capacity: int = 8) -> None:
        super().__init__(name="AppYoloUdpReceiver", daemon=True)
        self.stop_event = stop_event
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
        self.sock.settimeout(0.2)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._latest_target = PerceptionTarget()
        self._latest_scene = SceneDetections()
        self._last_packet_time = 0.0
        self._last_sequence = -1
        self._v2_gate = PerceptionSessionGate(
            max_datagram_bytes=max_datagram_bytes,
            max_detections=max_detections,
            tombstone_capacity=tombstone_capacity,
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload, _addr = self.sock.recvfrom(self._v2_gate.max_datagram_bytes + 1)
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                protocol, frame = self._v2_gate.ingest(payload, received_at_monotonic_ns=time.monotonic_ns())
            if protocol in {"hello", "hello_heartbeat"}:
                with self._condition:
                    if protocol == "hello":
                        self._latest_target = PerceptionTarget()
                        self._latest_scene = SceneDetections()
                        self._last_packet_time = 0.0
                        self._last_sequence = -1
                    self._condition.notify_all()
                continue
            if protocol not in {"v1", "perception"}:
                self.logger.warning("drop YOLO UDP payload reason=%s", protocol)
                continue
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                self.logger.warning("drop YOLO UDP payload because it is not a JSON object")
                continue
            if protocol == "perception":
                body = data.get("payload", {})
                data = {"target": body.get("target") or {},
                        "scene": {"timestamp": body.get("timestamp", 0.0), "frame_id": body.get("frame_id", 0),
                                  "image_width": body.get("image_width_px", 0), "image_height": body.get("image_height_px", 0),
                                  "detections": body.get("detections", [])},
                        "sequence": body.get("frame_id", getattr(frame, "sequence", 0)),
                        "published_at_monotonic": time.monotonic()}
            elif data.get("schema_version") != PERCEPTION_SCHEMA_VERSION:
                continue
            try:
                sequence = int(data["sequence"])
                published = float(data["published_at_monotonic"])
            except (KeyError, TypeError, ValueError):
                self.logger.warning("drop malformed YOLO UDP envelope")
                continue
            if sequence <= self._last_sequence or time.monotonic() - published > 2.0:
                self.logger.warning("drop out-of-order or stale YOLO UDP envelope sequence=%s", sequence)
                continue
            try:
                target = self._decode_target(data)
                scene = self._decode_scene(data)
            except (TypeError, ValueError, OverflowError) as exc:
                self.logger.warning("drop invalid YOLO UDP payload fields: %s", exc)
                continue
            with self._condition:
                self._latest_target = target
                self._latest_scene = scene
                self._last_packet_time = time.time()
                self._last_sequence = sequence
                self._condition.notify_all()

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

    def get_latest_frame(self, now: float, timeout_sec: float) -> tuple[PerceptionTarget, SceneDetections]:
        with self._lock:
            target = replace(self._latest_target)
            scene = replace(self._latest_scene)
            scene.detections = list(self._latest_scene.detections)
            last_packet_time = self._last_packet_time
        if last_packet_time <= 0 or (now - last_packet_time) > timeout_sec:
            target.target_valid = False
            target.tracking_state = "lost"
            target.ex = target.ey = 0.0
            return target, SceneDetections(timestamp=now)
        return target, scene

    def close(self) -> None:
        self.sock.close()

    def packet_age(self, now: float) -> float | None:
        with self._lock:
            last_packet_time = self._last_packet_time
        return None if last_packet_time <= 0 else max(0.0, now - last_packet_time)

    def platform_snapshot(self):
        with self._lock:
            return self._v2_gate.latest

    def snapshot(self):
        return self.platform_snapshot()

    def wait_next(self, *, after_session_id: str, after_sequence: int,
                  timeout_s: float):
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while True:
                session = self._v2_gate.active_session_id
                latest = self._v2_gate.latest
                if session != after_session_id:
                    return latest
                if latest is not None and latest.sequence > after_sequence:
                    return latest
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def health(self) -> PerceptionHealthSnapshot:
        with self._lock:
            latest = self._v2_gate.latest
            session = self._v2_gate.active_session_id
            revision = self._v2_gate.revision
        if session is None:
            return PerceptionHealthSnapshot(False, None, None, "hello_not_received", revision)
        if latest is None:
            return PerceptionHealthSnapshot(False, session, None, "frame_not_received", revision)
        age_s = max(0.0, (time.monotonic_ns() - latest.received_at_monotonic_ns) / 1_000_000_000)
        ttl_s = max(0.001, self._v2_gate.latest_ttl_ms / 1000.0)
        healthy = age_s <= ttl_s
        return PerceptionHealthSnapshot(healthy, session, age_s, "ok" if healthy else "stale", revision)

    def active_process_session_id(self) -> str | None:
        with self._lock:
            if "vision_command_v2" not in self._v2_gate.capabilities:
                return None
            return self._v2_gate.active_session_id

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
        self.state_port = VehicleStateAdapter(lambda: self.link_manager)
        self.link_control = LinkControlAdapter(lambda: self.link_manager)
        self.command_port = VehicleCommandAdapter(lambda: self.link_manager)
        self.fusion_manager = FusionManager(
            FusionConfig(
                require_gimbal_feedback=bool(config.runtime.require_gimbal_feedback)
            )
        )
        self._field_version_port: object | None = None
        self._execution_fence_query: object | None = None

    def set_field_reference_version_port(self, port: object) -> None:
        self._field_version_port = port
        if self.link_manager is not None:
            self.link_manager.set_field_reference_version_port(port)

    def set_execution_fence_query(self, port: object) -> None:
        self._execution_fence_query = port
        if self.link_manager is not None:
            self.link_manager.set_execution_fence_query(port)

    def start(self) -> None:
        if self.config.runtime.start_yolo_udp:
            self.yolo_receiver = YoloUdpReceiver(
                self.config.runtime.yolo_udp_ip,
                self.config.runtime.yolo_udp_port,
                self.stop_event,
                max_datagram_bytes=self.config.runtime.yolo_max_datagram_bytes,
                max_detections=self.config.runtime.yolo_max_detections,
                tombstone_capacity=self.config.runtime.yolo_tombstone_capacity,
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
            if self._execution_fence_query is not None:
                self.link_manager.set_execution_fence_query(self._execution_fence_query)
            if self._field_version_port is not None:
                self.link_manager.set_field_reference_version_port(self._field_version_port)
            self.link_manager.start_background()
            self.logger.info("telemetry link manager starting in background")
        else:
            self.logger.info("telemetry link manager disabled; running without a MAVLink link")

    def stop(self) -> None:
        if self.yolo_receiver is not None:
            receiver = self.yolo_receiver
            receiver.close()
            if receiver.is_alive():
                receiver.join(timeout=1.0)
            self.yolo_receiver = None
        if self.link_manager is not None:
            self.link_manager.stop()
            self.link_manager = None

    def reconnect_telemetry(self, config: TelemetryConfig) -> None:
        if self.link_manager is not None:
            self.link_manager.stop()
        self.config.telemetry = config
        self.link_manager = LinkManager(config)
        if self._execution_fence_query is not None:
            self.link_manager.set_execution_fence_query(self._execution_fence_query)
        if self._field_version_port is not None:
            self.link_manager.set_field_reference_version_port(self._field_version_port)
        self.link_manager.start_background()
        self.logger.info("telemetry link manager restarted from saved configuration")

    def get_perception(self, now: float) -> PerceptionTarget:
        if self.yolo_receiver is None:
            return PerceptionTarget(timestamp=now)
        return self.yolo_receiver.get_latest_target(
            now,
            self.config.runtime.perception_timeout_sec,
        )

    def get_perception_frame(self, now: float) -> tuple[PerceptionTarget, SceneDetections]:
        if self.yolo_receiver is None:
            return PerceptionTarget(timestamp=now), SceneDetections(timestamp=now)
        return self.yolo_receiver.get_latest_frame(now, self.config.runtime.perception_timeout_sec)

    def get_perception_platform_snapshot(self):
        return None if self.yolo_receiver is None else self.yolo_receiver.platform_snapshot()

    def get_yolo_process_session_id(self) -> str | None:
        return None if self.yolo_receiver is None else self.yolo_receiver.active_process_session_id()

    def perception_status(self, now: float) -> dict[str, object]:
        """Expose whether the optional UDP perception input is usable.

        The app deliberately runs without the board-local YOLO environment.
        Visual Actions receive an invalid target in that mode and therefore
        fail closed; nonvisual Actions remain available.
        """
        if self.yolo_receiver is None:
            return {"perception_source": "disabled", "stale": True, "age_sec": None}
        age = self.yolo_receiver.packet_age(now)
        return {
            "perception_source": "udp",
            "stale": age is None or age > self.config.runtime.perception_timeout_sec,
            "age_sec": age,
        }

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

    def get_vehicle_snapshot(self) -> VehicleStateSnapshot:
        return self.state_port.snapshot()

    def get_gimbal_state(self) -> GimbalState:
        if self.link_manager is None:
            return GimbalState()
        return self.link_manager.get_latest_gimbal_state()

    def get_link_status(self) -> LinkStatus | None:
        if self.link_manager is None:
            return None
        return self.link_manager.get_link_status()
