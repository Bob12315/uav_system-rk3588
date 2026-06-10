from __future__ import annotations

import threading
import time
from http import server
from socketserver import ThreadingMixIn

import cv2


class _ThreadingHttpServer(ThreadingMixIn, server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MjpegStream:
    def __init__(
        self,
        host: str,
        port: int,
        jpeg_quality: int,
        max_fps: float,
        width: int = 0,
        height: int = 0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.jpeg_quality = max(10, min(100, int(jpeg_quality)))
        self.frame_interval = 0.0 if max_fps <= 0 else 1.0 / float(max_fps)
        self.width = max(0, int(width))
        self.height = max(0, int(height))
        self._condition = threading.Condition()
        self._jpeg: bytes | None = None
        self._last_publish = 0.0
        self._server: _ThreadingHttpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        stream = self

        class Handler(server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/video/yolo.mjpeg":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                last_frame: bytes | None = None
                try:
                    while True:
                        with stream._condition:
                            stream._condition.wait_for(lambda: stream._jpeg is not None and stream._jpeg is not last_frame)
                            frame = stream._jpeg
                        if frame is None:
                            continue
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                        last_frame = frame
                except (BrokenPipeError, ConnectionResetError):
                    return

            def log_message(self, _format: str, *_args) -> None:
                return

        self._server = _ThreadingHttpServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="YoloMjpegStream", daemon=True)
        self._thread.start()

    def publish(self, frame) -> None:
        now = time.perf_counter()
        if self.frame_interval > 0 and now - self._last_publish < self.frame_interval:
            return
        output_frame = frame
        if self.width > 0 and self.height > 0:
            output_frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(
            ".jpg",
            output_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        if not ok:
            return
        self._last_publish = now
        with self._condition:
            self._jpeg = encoded.tobytes()
            self._condition.notify_all()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
