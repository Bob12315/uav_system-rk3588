from __future__ import annotations

import json
import math
import socket
import threading
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttitudeSample:
    source: str
    link_session_id: str
    received_at_monotonic_ns: int
    roll_rad: float
    pitch_rad: float
    yaw_rad: float
    roll_rate_rad_s: float
    pitch_rate_rad_s: float
    yaw_rate_rad_s: float

    def __post_init__(self) -> None:
        values = (
            self.roll_rad,
            self.pitch_rad,
            self.yaw_rad,
            self.roll_rate_rad_s,
            self.pitch_rate_rad_s,
            self.yaw_rate_rad_s,
        )
        if not self.source or not self.link_session_id:
            raise ValueError("attitude sample identity must not be empty")
        if self.received_at_monotonic_ns < 0 or not all(math.isfinite(value) for value in values):
            raise ValueError("attitude sample values must be finite")


class AttitudeUdpPublisher:
    """Single-slot, non-blocking localhost attitude publisher.

    ``offer`` only replaces the pending sample and never performs socket I/O,
    so MAVLink reception cannot wait behind the UDP consumer.
    """

    def __init__(
        self,
        udp_ip: str,
        udp_port: int,
        *,
        source: str,
        stop_event: threading.Event,
    ) -> None:
        self.addr = (udp_ip, int(udp_port))
        self.source = source
        self.stop_event = stop_event
        self.publisher_session_id = uuid.uuid4().hex
        self._closed = threading.Event()
        self._condition = threading.Condition()
        self._latest: AttitudeSample | None = None
        self._sequence = 0
        self._thread = threading.Thread(
            name=f"AttitudeUdpPublisher-{source}", target=self._run, daemon=True
        )
        self._sock: socket.socket | None = None

    def start(self) -> None:
        self._thread.start()

    def offer(self, sample: AttitudeSample) -> None:
        if sample.source != self.source:
            return
        with self._condition:
            self._latest = sample
            self._condition.notify()

    def close(self) -> None:
        self._closed.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock = sock
        try:
            while not self.stop_event.is_set() and not self._closed.is_set():
                with self._condition:
                    if self._latest is None:
                        self._condition.wait(timeout=0.2)
                    sample = self._latest
                    self._latest = None
                if sample is None:
                    continue
                self._sequence += 1
                payload = {
                    "schema_version": 1,
                    "message_type": "attitude",
                    "publisher_session_id": self.publisher_session_id,
                    "sequence": self._sequence,
                    "source": sample.source,
                    "link_session_id": sample.link_session_id,
                    "received_at_monotonic_ns": sample.received_at_monotonic_ns,
                    "sent_at_monotonic_ns": time.monotonic_ns(),
                    "roll_rad": sample.roll_rad,
                    "pitch_rad": sample.pitch_rad,
                    "yaw_rad": sample.yaw_rad,
                    "roll_rate_rad_s": sample.roll_rate_rad_s,
                    "pitch_rate_rad_s": sample.pitch_rate_rad_s,
                    "yaw_rate_rad_s": sample.yaw_rate_rad_s,
                }
                try:
                    sock.sendto(
                        json.dumps(payload, separators=(",", ":")).encode("utf-8"), self.addr
                    )
                except OSError:
                    if self.stop_event.is_set() or self._closed.is_set():
                        break
        finally:
            sock.close()
            self._sock = None
