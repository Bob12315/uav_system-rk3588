from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time

import cv2
import numpy as np

try:
    from .models import FramePacket
except ImportError:
    from models import FramePacket


class VideoSource:
    def __init__(
        self,
        source: str,
        camera_width: int = 640,
        camera_height: int = 480,
        camera_fps: int = 30,
        camera_fourcc: str = "MJPG",
        latest_frame: bool = False,
    ) -> None:
        self.source = source
        self.camera_width = camera_width
        self.camera_height = camera_height
        self.camera_fps = camera_fps
        self.camera_fourcc = camera_fourcc
        self.frame_id = 0
        self.cap: cv2.VideoCapture | None = None
        self.udp_process: subprocess.Popen | None = None
        self.udp_frame_shape: tuple[int, int, int] | None = None
        self.latest_frame = latest_frame and source.startswith("/dev/video")
        self.condition = threading.Condition()
        self.camera_frame = None
        self.camera_timestamp = 0.0
        self.camera_sequence = 0
        self.consumed_sequence = 0
        self.stopped = False
        self.reader_thread: threading.Thread | None = None

        if source.isdigit():
            self._open_udp_port_source(int(source))
        else:
            self.cap = self._open_capture(source)
            if not self.cap.isOpened():
                raise RuntimeError(f"failed to open video source: {source}")
            if self.latest_frame:
                self.reader_thread = threading.Thread(target=self._camera_reader, daemon=True)
                self.reader_thread.start()

    def read(self) -> FramePacket | None:
        timestamp = time.time()
        if self.latest_frame:
            frame, timestamp = self._read_latest_frame()
            if frame is None:
                return None
        elif self.udp_process is not None:
            frame = self._read_udp_frame()
            if frame is None:
                return None
        else:
            if self.cap is None:
                return None
            ok, frame = self.cap.read()
            if not ok or frame is None:
                return None

        packet = FramePacket(frame=frame, frame_id=self.frame_id, timestamp=timestamp)
        self.frame_id += 1
        return packet

    def release(self) -> None:
        self.stopped = True
        if self.cap is not None:
            self.cap.release()
        with self.condition:
            self.condition.notify_all()
        if self.reader_thread is not None:
            self.reader_thread.join(timeout=1.0)
        if self.udp_process is not None:
            self.udp_process.terminate()
            try:
                self.udp_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.udp_process.kill()

    def _open_capture(self, capture_source: str) -> cv2.VideoCapture:
        if self._looks_like_gstreamer_pipeline(capture_source):
            if not self._opencv_has_gstreamer():
                raise RuntimeError(
                    "source looks like a GStreamer pipeline, but this OpenCV build has no GStreamer support. "
                    "Please use /dev/videoX, RTSP, file input, or plain UDP port mode instead."
                )
            cap = cv2.VideoCapture(capture_source, cv2.CAP_GSTREAMER)
            if cap.isOpened():
                return cap
            cap.release()
            raise RuntimeError(
                "failed to open GStreamer pipeline. Please check the pipeline string and required plugins."
            )
        if capture_source.startswith("/dev/video"):
            cap = cv2.VideoCapture(capture_source, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.camera_fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
            cap.set(cv2.CAP_PROP_FPS, self.camera_fps)
            return cap
        return cv2.VideoCapture(capture_source)

    def _camera_reader(self) -> None:
        while not self.stopped and self.cap is not None:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                continue
            with self.condition:
                self.camera_frame = frame
                self.camera_timestamp = time.time()
                self.camera_sequence += 1
                self.condition.notify_all()

    def _read_latest_frame(self):
        with self.condition:
            while not self.stopped and (
                self.camera_frame is None or self.camera_sequence <= self.consumed_sequence
            ):
                self.condition.wait(timeout=1.0)
            if self.camera_frame is None:
                return None, time.time()
            self.consumed_sequence = self.camera_sequence
            return self.camera_frame.copy(), self.camera_timestamp

    def _open_udp_port_source(self, udp_port: int) -> None:
        helper_path = Path(__file__).with_name("udp_gst_bridge_helper.py")
        cmd = ["/usr/bin/python3", "-u", str(helper_path), "--port", str(udp_port)]
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        self.udp_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        if self.udp_process.stdout is None:
            raise RuntimeError("failed to create UDP bridge stdout pipe")

        header_line = self.udp_process.stdout.readline()
        if not header_line:
            error_text = ""
            if self.udp_process.stderr is not None:
                error_text = self.udp_process.stderr.read(1024).decode("utf-8", errors="ignore")
            raise RuntimeError(f"failed to start UDP bridge on port {udp_port}: {error_text.strip()}")

        header = json.loads(header_line.decode("utf-8"))
        if "error" in header:
            raise RuntimeError(header["error"])

        self.udp_frame_shape = (
            int(header["height"]),
            int(header["width"]),
            int(header.get("channels", 3)),
        )

    def _read_udp_frame(self):
        if self.udp_process is None or self.udp_process.stdout is None or self.udp_frame_shape is None:
            return None
        height, width, channels = self.udp_frame_shape
        frame_size = height * width * channels
        raw = self.udp_process.stdout.read(frame_size)
        if raw is None or len(raw) != frame_size:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape((height, width, channels))

    def _looks_like_gstreamer_pipeline(self, source: str) -> bool:
        pipeline_markers = (
            " ! ",
            "appsink",
            "udpsrc",
            "rtspsrc",
            "rtph264depay",
            "avdec_h264",
            "videoconvert",
        )
        lowered = source.lower()
        return any(marker in lowered for marker in pipeline_markers)

    def _opencv_has_gstreamer(self) -> bool:
        info = cv2.getBuildInformation()
        for line in info.splitlines():
            if "GStreamer" in line:
                return "YES" in line.upper()
        return False
