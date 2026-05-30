from __future__ import annotations

import json
from yolo_app.models import CurrentTarget, DetectionObject, Track
from yolo_app.target_manager import build_scene_detections
from yolo_app.udp_publisher import UdpPublisher


def _track(track_id: int = 7, x1: float = 100.0, y1: float = 80.0) -> Track:
    return Track(
        track_id=track_id,
        class_id=2,
        class_name="cylinder",
        confidence=0.75,
        x1=x1,
        y1=y1,
        x2=x1 + 60.0,
        y2=y1 + 40.0,
    )


def _target() -> CurrentTarget:
    return CurrentTarget(
        timestamp=1.2,
        frame_id=10,
        target_valid=True,
        tracking_state="locked",
        track_id=7,
        class_id=2,
        class_name="cylinder",
        confidence=0.75,
        cx=130.0,
        cy=100.0,
        w=60.0,
        h=40.0,
        ex=-0.59375,
        ey=-0.5833333333333334,
        image_width=640,
        image_height=480,
        target_size=0.09375,
        lost_count=0,
    )


def test_detection_object_from_track_matches_current_target_geometry() -> None:
    detection = DetectionObject.from_track(_track(), image_width=640, image_height=480)

    assert detection.track_id == 7
    assert detection.class_id == 2
    assert detection.class_name == "cylinder"
    assert detection.confidence == 0.75
    assert detection.cx == 130.0
    assert detection.cy == 100.0
    assert detection.w == 60.0
    assert detection.h == 40.0
    assert detection.ex == -0.59375
    assert detection.ey == -0.5833333333333334
    assert detection.target_size == 0.09375


def test_build_scene_detections_includes_all_tracks() -> None:
    scene = build_scene_detections(
        tracks=[_track(track_id=1), _track(track_id=2, x1=200.0)],
        image_width=640,
        image_height=480,
        frame_id=11,
        timestamp=2.0,
    )

    assert scene.timestamp == 2.0
    assert scene.frame_id == 11
    assert scene.image_width == 640
    assert scene.image_height == 480
    assert [detection.track_id for detection in scene.detections] == [1, 2]


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, payload: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((payload, addr))

    def close(self) -> None:
        pass


def test_udp_publisher_envelope_contains_target_and_scene(monkeypatch) -> None:
    fake_socket = _FakeSocket()
    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: fake_socket)
    publisher = UdpPublisher("127.0.0.1", 5005)
    scene = build_scene_detections([_track()], 640, 480, 10, 1.2)

    publisher.publish(_target(), scene)

    payload = json.loads(fake_socket.sent[0][0].decode("utf-8"))
    assert set(payload) == {"target", "scene"}
    assert payload["target"]["target_valid"] is True
    assert payload["scene"]["detections"][0]["track_id"] == 7
