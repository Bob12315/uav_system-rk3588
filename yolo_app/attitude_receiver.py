from __future__ import annotations

import json
import logging
import math
import socket
import threading
from collections import deque

try:
    from .attitude_history import AttitudeHistory, AttitudeSample
except ImportError:  # pragma: no cover - supports direct script execution
    from attitude_history import AttitudeHistory, AttitudeSample


class AttitudeReceiver(threading.Thread):
    """Receive the localhost-only Virtual Nadir attitude stream."""

    def __init__(
        self,
        ip: str,
        port: int,
        history: AttitudeHistory,
        *,
        expected_source: str,
        max_datagram_bytes: int = 4096,
        tombstone_capacity: int = 8,
    ) -> None:
        super().__init__(name="YoloAttitudeReceiver", daemon=True)
        if ip not in {"127.0.0.1", "localhost"}:
            raise ValueError("attitude receiver must bind to localhost")
        self.history = history
        self.expected_source = expected_source
        self.max_datagram_bytes = int(max_datagram_bytes)
        self._stop_event = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((ip, int(port)))
        self._sock.settimeout(0.2)
        self._active_session: tuple[str, str, str] | None = None
        self._last_sequence = -1
        self._tombstones: deque[tuple[str, str, str]] = deque(maxlen=tombstone_capacity)
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def active_session(self) -> tuple[str, str, str] | None:
        return self._active_session

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                payload, addr = self._sock.recvfrom(self.max_datagram_bytes + 1)
            except TimeoutError:
                continue
            except OSError:
                break
            if addr[0] not in {"127.0.0.1", "::1"}:
                continue
            reason = self.ingest(payload)
            if reason not in {"accepted", "out_of_order", "retired_session"}:
                self.logger.warning("drop attitude UDP payload reason=%s", reason)

    def close(self) -> None:
        self._stop_event.set()
        self._sock.close()
        if self.is_alive():
            self.join(timeout=1.0)

    def ingest(self, payload: bytes) -> str:
        if len(payload) > self.max_datagram_bytes:
            return "oversize"
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "malformed"
        if not isinstance(data, dict):
            return "malformed"
        if data.get("schema_version") != 1 or data.get("message_type") != "attitude":
            return "unsupported_schema"
        try:
            publisher_session_id = str(data["publisher_session_id"])
            link_session_id = str(data["link_session_id"])
            source = str(data["source"])
            sequence = int(data["sequence"])
            received_ns = int(data["received_at_monotonic_ns"])
            values = tuple(float(data[name]) for name in (
                "roll_rad", "pitch_rad", "yaw_rad", "roll_rate_rad_s",
                "pitch_rate_rad_s", "yaw_rate_rad_s",
            ))
        except (KeyError, TypeError, ValueError, OverflowError):
            return "malformed"
        if (
            not publisher_session_id
            or not link_session_id
            or source != self.expected_source
            or sequence < 1
            or received_ns <= 0
            or not all(math.isfinite(value) for value in values)
        ):
            return "invalid_fields"
        session = publisher_session_id, link_session_id, source
        if session in self._tombstones:
            return "retired_session"
        if session != self._active_session:
            if self._active_session is not None:
                self._tombstones.append(self._active_session)
            self._active_session = session
            self._last_sequence = -1
        if sequence <= self._last_sequence:
            return "out_of_order"
        sample = AttitudeSample(
            publisher_session_id,
            link_session_id,
            source,
            sequence,
            received_ns,
            *values,
        )
        if not self.history.append(sample):
            return "history_rejected"
        self._last_sequence = sequence
        return "accepted"
