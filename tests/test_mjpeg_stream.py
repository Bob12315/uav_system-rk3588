from __future__ import annotations

from urllib.request import urlopen

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
