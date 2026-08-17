from __future__ import annotations

import json
import socket
import threading
import time

from app.bootstrap import YoloUdpReceiver


def _packet(message_type: str, session: str, sequence: int = 0, **payload) -> bytes:
    if message_type == "perception":
        payload.setdefault("frame_id", sequence)
        payload.setdefault("image_width_px", 640)
        payload.setdefault("image_height_px", 480)
        payload.setdefault("captured_at_monotonic_ns", 1)
        payload.setdefault("detections", [])
    return json.dumps({
        "schema_major": 2,
        "schema_minor": 0,
        "message_type": message_type,
        "sequence": sequence,
        "sent_at_utc": "2026-08-16T00:00:00+00:00",
        "ttl_ms": 1000,
        "sent_at_monotonic_ns": 1,
        "producer_id": "yolo",
        "yolo_process_session_id": session,
        "producer_clock_domain_id": f"clock-{session}",
        "payload": payload,
    }, separators=(",", ":")).encode()


def test_receiver_wait_next_returns_atomic_frame_and_wakes_on_session_change() -> None:
    stop = threading.Event()
    receiver = YoloUdpReceiver("127.0.0.1", 0, stop)
    address = receiver.sock.getsockname()
    receiver.start()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sender.sendto(_packet("hello", "A", capabilities=["perception_v2"]), address)
        deadline = time.monotonic() + 1
        while receiver.health().active_session_id != "A" and time.monotonic() < deadline:
            time.sleep(0.005)
        sender.sendto(_packet("perception", "A", 1,
            target={"track_id": 7, "class_name": "target", "confidence": 0.8,
                    "cx": 320, "cy": 240}), address)
        snapshot = receiver.wait_next(after_session_id="A", after_sequence=-1, timeout_s=1)
        assert snapshot is not None
        assert snapshot.yolo_process_session_id == "A" and snapshot.sequence == 1
        assert snapshot.target is not None and snapshot.target.track_id == 7

        sender.sendto(_packet("hello", "B", capabilities=["perception_v2"]), address)
        started = time.monotonic()
        changed = receiver.wait_next(after_session_id="A", after_sequence=1, timeout_s=1)
        assert changed is None and time.monotonic() - started < 0.2
        assert receiver.health().active_session_id == "B"
    finally:
        sender.close()
        stop.set()
        receiver.close()
        receiver.join(1)
    assert not receiver.is_alive()
