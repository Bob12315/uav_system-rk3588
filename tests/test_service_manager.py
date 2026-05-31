from __future__ import annotations

import json
import socket
import threading
import time
from types import SimpleNamespace

from app.service_manager import ServiceManager, YoloUdpReceiver


def test_yolo_receiver_decodes_legacy_current_target_payload() -> None:
    target = YoloUdpReceiver._decode_target(
        {
            "timestamp": 1.2,
            "frame_id": 3,
            "target_valid": True,
            "tracking_state": "locked",
            "track_id": 7,
            "class_name": "cylinder",
            "confidence": 0.8,
            "cx": 10.0,
            "cy": 20.0,
            "w": 30.0,
            "h": 40.0,
            "image_width": 640,
            "image_height": 480,
            "target_size": 0.1,
            "ex": -0.5,
            "ey": 0.25,
            "lost_count": 0,
        }
    )
    scene = YoloUdpReceiver._decode_scene({"target_valid": True})

    assert target.target_valid is True
    assert target.track_id == 7
    assert target.class_name == "cylinder"
    assert scene.valid is False
    assert scene.detections == []


def test_yolo_receiver_decodes_envelope_target_and_scene() -> None:
    data = {
        "target": {
            "timestamp": 2.0,
            "frame_id": 4,
            "target_valid": True,
            "tracking_state": "locked",
            "track_id": 9,
            "class_name": "target",
        },
        "scene": {
            "timestamp": 2.0,
            "frame_id": 4,
            "image_width": 1280,
            "image_height": 720,
            "detections": [
                {
                    "track_id": 9,
                    "class_id": 3,
                    "class_name": "target",
                    "confidence": 0.91,
                    "x1": 10,
                    "y1": 20,
                    "x2": 30,
                    "y2": 50,
                    "cx": 20,
                    "cy": 35,
                    "w": 20,
                    "h": 30,
                    "ex": -0.2,
                    "ey": 0.1,
                    "target_size": 0.04,
                }
            ],
        },
    }

    target = YoloUdpReceiver._decode_target(data)
    scene = YoloUdpReceiver._decode_scene(data)

    assert target.track_id == 9
    assert target.class_name == "target"
    assert scene.valid is True
    assert scene.image_width == 1280
    assert scene.detections[0].track_id == 9
    assert scene.detections[0].confidence == 0.91


def test_yolo_receiver_times_out_scene_detections() -> None:
    receiver = YoloUdpReceiver.__new__(YoloUdpReceiver)
    receiver._latest_scene = YoloUdpReceiver._decode_scene(
        {
            "scene": {
                "timestamp": 1.0,
                "frame_id": 1,
                "detections": [{"track_id": 1, "class_name": "target"}],
            }
        }
    )
    receiver._last_packet_time = time.time() - 10.0
    import threading

    receiver._lock = threading.Lock()

    scene = receiver.get_latest_scene(time.time(), timeout_sec=0.1)

    assert scene.valid is False
    assert scene.detections == []


def test_yolo_receiver_drops_bad_fields_and_keeps_listening() -> None:
    stop_event = threading.Event()
    receiver = YoloUdpReceiver("127.0.0.1", 0, stop_event)
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.start()

    try:
        address = receiver.sock.getsockname()
        client.sendto(json.dumps({"track_id": "invalid"}).encode("utf-8"), address)
        client.sendto(
            json.dumps({"target_valid": True, "tracking_state": "locked", "track_id": 7}).encode("utf-8"),
            address,
        )

        deadline = time.time() + 1.0
        while time.time() < deadline:
            target = receiver.get_latest_target(time.time(), timeout_sec=1.0)
            if target.track_id == 7:
                break
            time.sleep(0.01)

        assert receiver.is_alive()
        assert target.target_valid is True
        assert target.track_id == 7
    finally:
        stop_event.set()
        receiver.close()
        receiver.join(timeout=1.0)
        client.close()


def test_service_manager_reconnect_stops_old_link_and_starts_new_link(monkeypatch) -> None:
    created = []

    class FakeLinkManager:
        def __init__(self, config) -> None:
            self.config = config
            self.stopped = False
            self.started = False
            created.append(self)

        def stop(self) -> None:
            self.stopped = True

        def start_background(self) -> None:
            self.started = True

    monkeypatch.setattr("app.service_manager.LinkManager", FakeLinkManager)
    old_config = object()
    new_config = object()
    app_config = SimpleNamespace(
        runtime=SimpleNamespace(require_gimbal_feedback=False),
        telemetry=old_config,
    )
    manager = ServiceManager(app_config, threading.Event())
    old_link = FakeLinkManager(old_config)
    manager.link_manager = old_link

    manager.reconnect_telemetry(new_config)

    assert old_link.stopped is True
    assert manager.config.telemetry is new_config
    assert manager.link_manager is created[-1]
    assert manager.link_manager.config is new_config
    assert manager.link_manager.started is True
