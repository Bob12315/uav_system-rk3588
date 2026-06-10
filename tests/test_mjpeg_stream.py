from __future__ import annotations

from urllib.request import urlopen

import cv2
import numpy as np

from yolo_app.mjpeg_stream import MjpegStream


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

    stream.publish(frame)

    assert stream._jpeg is not None
    decoded = cv2.imdecode(np.frombuffer(stream._jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[:2] == (240, 320)
    assert frame.shape[:2] == (480, 640)


def test_mjpeg_stream_clamps_jpeg_quality() -> None:
    assert MjpegStream("127.0.0.1", 0, jpeg_quality=5, max_fps=0).jpeg_quality == 10
    assert MjpegStream("127.0.0.1", 0, jpeg_quality=125, max_fps=0).jpeg_quality == 100


def test_mjpeg_stream_max_fps_throttle_remains_effective() -> None:
    stream = MjpegStream("127.0.0.1", 0, jpeg_quality=75, max_fps=30)
    first = np.zeros((24, 32, 3), dtype=np.uint8)
    second = np.full((24, 32, 3), 255, dtype=np.uint8)

    stream.publish(first)
    published = stream._jpeg
    stream.publish(second)

    assert stream._jpeg == published
