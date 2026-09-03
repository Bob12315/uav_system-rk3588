from __future__ import annotations

import json
import math
import socket
import threading
import time
import uuid
from collections import deque
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
    """Bounded, non-blocking localhost attitude publisher.

    ``offer`` only appends to a small bounded FIFO and never performs socket
    I/O, so MAVLink reception cannot wait behind the UDP consumer.  Keeping a
    short burst prevents scheduler jitter from collapsing a 30+ Hz attitude
    stream into a much lower latest-only stream.
    """

    def __init__(
        self,
        udp_ip: str,
        udp_port: int,
        *,
        source: str,
        stop_event: threading.Event,
        max_pending_samples: int = 32,
    ) -> None:
        if max_pending_samples < 2:
            raise ValueError("max_pending_samples must be at least 2")
        self.addr = (udp_ip, int(udp_port))
        self.source = source
        self.stop_event = stop_event
        self.publisher_session_id = uuid.uuid4().hex
        self._closed = threading.Event()
        self._condition = threading.Condition()
        self._pending: deque[AttitudeSample] = deque(maxlen=int(max_pending_samples))
        self._sequence = 0
        self._reset_pending = False
        self._generation = 0
        self._thread = threading.Thread(
            name=f"AttitudeUdpPublisher-{source}", target=self._run, daemon=True
        )
        self._sock: socket.socket | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread.ident is not None:
                return
            self._thread.start()

    def offer(self, sample: AttitudeSample) -> None:
        with self._condition:
            if sample.source != self.source:
                return
            self._pending.append(sample)
            self._condition.notify()

    def switch_source(self, source: str) -> None:
        """Atomically retire the old source/session and notify the consumer."""
        if not source:
            raise ValueError("attitude source must not be empty")
        with self._condition:
            if source == self.source:
                return
            self.source = source
            self.publisher_session_id = uuid.uuid4().hex
            self._sequence = 0
            self._generation += 1
            self._pending.clear()
            self._reset_pending = True
            self._condition.notify_all()

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
                    if not self._pending and not self._reset_pending:
                        self._condition.wait(timeout=0.2)
                    reset_pending = self._reset_pending
                    self._reset_pending = False
                    sample = self._pending.popleft() if self._pending else None
                    source = self.source
                    publisher_session_id = self.publisher_session_id
                    generation = self._generation
                if reset_pending:
                    reset_payload = {
                        "schema_version": 1,
                        "message_type": "attitude_reset",
                        "publisher_session_id": publisher_session_id,
                        "sequence": 0,
                        "source": source,
                        "sent_at_monotonic_ns": time.monotonic_ns(),
                    }
                    try:
                        with self._condition:
                            if generation != self._generation:
                                continue
                            sock.sendto(
                                json.dumps(reset_payload, separators=(",", ":")).encode("utf-8"),
                                self.addr,
                            )
                    except OSError:
                        if self.stop_event.is_set() or self._closed.is_set():
                            break
                if sample is None or sample.source != source:
                    continue
                try:
                    with self._condition:
                        if generation != self._generation:
                            continue
                        self._sequence += 1
                        payload = {
                            "schema_version": 1,
                            "message_type": "attitude",
                            "publisher_session_id": publisher_session_id,
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
                        sock.sendto(
                            json.dumps(payload, separators=(",", ":")).encode("utf-8"), self.addr
                        )
                except OSError:
                    if self.stop_event.is_set() or self._closed.is_set():
                        break
        finally:
            sock.close()
            self._sock = None
