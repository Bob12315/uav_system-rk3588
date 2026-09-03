from __future__ import annotations

import threading
import time
from urllib.request import urlopen

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from yolo_app.mjpeg_stream import MjpegStream


def _wait_for_jpeg(stream: MjpegStream, timeout: float = 1.0) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with stream._condition:
            if stream._jpeg is not None:
                return stream._jpeg
        time.sleep(0.005)
    raise AssertionError("MJPEG encoder did not publish a frame")


def test_mjpeg_stream_serves_published_frame() -> None:
    stream = MjpegStream("127.0.0.1", 0, jpeg_quality=75, max_fps=0)
    stream.start()
    try:
        stream.publish(np.zeros((24, 32, 3), dtype=np.uint8))
        assert stream._server is not None
        with urlopen(
            f"http://127.0.0.1:{stream._server.server_port}/video/yolo.mjpeg",
            timeout=2,
        ) as response:
            payload = response.read(128)
        assert b"Content-Type: image/jpeg" in payload
    finally:
        stream.close()


def test_mjpeg_stream_resizes_before_encoding_without_mutating_input() -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    stream = MjpegStream("127.0.0.1", 0, jpeg_quality=50, max_fps=0, width=320, height=240)
    stream.start()
    try:
        stream.publish(frame)
        encoded = _wait_for_jpeg(stream)
        decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None
        assert decoded.shape[:2] == (240, 320)
        assert frame.shape[:2] == (480, 640)
    finally:
        stream.close()


def test_mjpeg_stream_clamps_jpeg_quality() -> None:
    assert MjpegStream("127.0.0.1", 0, jpeg_quality=5, max_fps=0).jpeg_quality == 10
    assert MjpegStream("127.0.0.1", 0, jpeg_quality=125, max_fps=0).jpeg_quality == 100


def test_mjpeg_stream_max_fps_throttle_remains_effective() -> None:
    stream = MjpegStream("127.0.0.1", 0, jpeg_quality=75, max_fps=30)
    first = np.zeros((24, 32, 3), dtype=np.uint8)
    second = np.full((24, 32, 3), 255, dtype=np.uint8)
    stream.start()
    try:
        stream.publish(first)
        stream.publish(second)
        encoded = _wait_for_jpeg(stream)
        decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None
        assert float(decoded.mean()) < 1.0
        assert stream.encoder_metrics["submitted"] == 1
    finally:
        stream.close()


def test_mjpeg_stream_latest_only_queue_replaces_pending_frame(monkeypatch) -> None:
    stream = MjpegStream("127.0.0.1", 0, jpeg_quality=75, max_fps=0)
    real_imencode = cv2.imencode
    encoder_started = threading.Event()
    encoder_release = threading.Event()

    def slow_imencode(*args, **kwargs):
        encoder_started.set()
        assert encoder_release.wait(timeout=1.0)
        return real_imencode(*args, **kwargs)

    monkeypatch.setattr(cv2, "imencode", slow_imencode)
    stream.start()
    try:
        stream.publish(np.zeros((24, 32, 3), dtype=np.uint8))
        assert encoder_started.wait(timeout=1.0)
        stream.publish(np.full((24, 32, 3), 100, dtype=np.uint8))
        stream.publish(np.full((24, 32, 3), 200, dtype=np.uint8))
        assert stream.encoder_metrics["replaced"] == 1
        encoder_release.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and stream.encoder_metrics["encoded"] < 2:
            time.sleep(0.005)
        assert stream.encoder_metrics["encoded"] == 2
    finally:
        encoder_release.set()
        stream.close()
