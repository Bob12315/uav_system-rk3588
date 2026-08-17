from __future__ import annotations

import json
import math
import time
from collections import deque
from datetime import datetime, timezone

from contracts.platform.common import ClockStamp, SchemaVersion
from contracts.platform.perception import Detection, PerceptionFrameSnapshot, PerceptionTarget, RecordingState


class PerceptionSessionGate:
    """Bounded v2 receiver state; only HELLO may activate a new producer session."""

    def __init__(self, *, max_datagram_bytes: int = 60_000, max_detections: int = 128,
                 tombstone_capacity: int = 8) -> None:
        self.max_datagram_bytes = max_datagram_bytes
        self.max_detections = max_detections
        self._tombstones: deque[str] = deque(maxlen=tombstone_capacity)
        self.active_session_id: str | None = None
        self.producer_id: str | None = None
        self.clock_domain_id: str | None = None
        self.last_sequence = -1
        self.latest: PerceptionFrameSnapshot | None = None
        self.latest_ttl_ms = 0
        self.revision = 0
        self.capabilities: tuple[str, ...] = ()

    @property
    def tombstones(self) -> tuple[str, ...]:
        return tuple(self._tombstones)

    def ingest(self, payload: bytes, *, received_at_monotonic_ns: int) -> tuple[str, object | None]:
        if len(payload) > self.max_datagram_bytes:
            return "oversize", None
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "malformed", None
        if not isinstance(data, dict):
            return "malformed", None
        if "schema_version" in data:
            return "v1", data
        if data.get("schema_major") != 2:
            return "unsupported_schema", None
        session = str(data.get("yolo_process_session_id") or "")
        message_type = str(data.get("message_type") or "")
        if message_type == "hello":
            producer_id = str(data.get("producer_id") or "")
            clock_domain_id = str(data.get("producer_clock_domain_id") or "")
            try:
                ttl_ms = int(data["ttl_ms"])
                sequence = int(data["sequence"])
            except (KeyError, TypeError, ValueError):
                return "malformed", None
            if not session or not producer_id or not clock_domain_id or ttl_ms <= 0 or sequence < 0:
                return "malformed", None
            hello_payload = data.get("payload")
            raw_capabilities = hello_payload.get("capabilities", []) if isinstance(hello_payload, dict) else []
            if (not isinstance(raw_capabilities, list) or len(raw_capabilities) > 32
                    or not all(isinstance(item, str) and item for item in raw_capabilities)):
                return "malformed", None
            if session in self._tombstones:
                return "retired_session", None
            if self.active_session_id == session:
                if producer_id != self.producer_id or clock_domain_id != self.clock_domain_id:
                    return "identity_mismatch", None
                self.capabilities = tuple(raw_capabilities)
                return "hello_heartbeat", None
            if self.active_session_id:
                self._tombstones.append(self.active_session_id)
            self.active_session_id = session
            self.producer_id = producer_id
            self.clock_domain_id = clock_domain_id
            self.capabilities = tuple(raw_capabilities)
            self.last_sequence = -1
            self.latest = None
            self.latest_ttl_ms = 0
            self.revision += 1
            return "hello", None
        if message_type != "perception" or session != self.active_session_id:
            return "session_mismatch", None
        if (str(data.get("producer_id") or "") != self.producer_id
                or str(data.get("producer_clock_domain_id") or "") != self.clock_domain_id):
            return "identity_mismatch", None
        try:
            sequence = int(data["sequence"])
            ttl_ms = int(data["ttl_ms"])
            sent_at_monotonic_ns = int(data["sent_at_monotonic_ns"])
        except (KeyError, TypeError, ValueError):
            return "malformed", None
        if ttl_ms <= 0 or sent_at_monotonic_ns < 0:
            return "malformed", None
        if sequence < 0 or sequence <= self.last_sequence:
            return "out_of_order", None
        body = data.get("payload")
        if not isinstance(body, dict):
            return "malformed", None
        detections_data = body.get("detections", [])
        if not isinstance(detections_data, list) or len(detections_data) > self.max_detections:
            return "detections_limit", None
        try:
            detections = tuple(self._detection(item) for item in detections_data)
            target_data = body.get("target")
            target = self._target(target_data) if isinstance(target_data, dict) else None
            captured_utc = datetime.fromisoformat(str(data["sent_at_utc"]).replace("Z", "+00:00"))
            if captured_utc.tzinfo is None:
                return "malformed", None
            captured_monotonic_ns = int(body.get("captured_at_monotonic_ns", 0))
            image_width_px = int(body.get("image_width_px", 0))
            image_height_px = int(body.get("image_height_px", 0))
            original_count = int(body.get("original_detection_count", len(detections)))
            truncated = bool(body.get("truncated", False))
            if captured_monotonic_ns < 0 or image_width_px <= 0 or image_height_px <= 0:
                return "malformed", None
            if original_count < len(detections) or truncated != (original_count > len(detections)):
                return "malformed", None
            frame = PerceptionFrameSnapshot(
                SchemaVersion(2, int(data.get("schema_minor", 0))), str(data.get("producer_id") or ""), session,
                sequence, int(body.get("frame_id", sequence)),
                ClockStamp(captured_utc, captured_monotonic_ns, str(data.get("producer_clock_domain_id") or "unknown")),
                str(data.get("producer_clock_domain_id") or "unknown"), received_at_monotonic_ns,
                image_width_px, image_height_px, target, detections,
                truncated, original_count,
                str(body.get("producer_status", "ok")),
                RecordingState(str(body.get("recording_state", "UNKNOWN"))),
                None if body.get("recorder_boot_id") is None else str(body["recorder_boot_id"]),
                None if body.get("recorder_session_id") is None else str(body["recorder_session_id"]),
                None if body.get("recording_path") is None else str(body["recording_path"]),
                int(body.get("recording_frames", 0)),
                None if body.get("recording_error") is None else str(body["recording_error"]),
                None if body.get("recording_expires_at_monotonic_ns") is None else int(body["recording_expires_at_monotonic_ns"]),
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return "malformed", None
        self.last_sequence = sequence
        self.latest = frame
        self.latest_ttl_ms = ttl_ms
        self.revision += 1
        return "perception", frame

    @staticmethod
    def _detection(item: object) -> Detection:
        if not isinstance(item, dict): raise TypeError
        track_id = None if item.get("track_id") is None else int(item["track_id"])
        class_id = int(item.get("class_id", -1)); confidence = float(item.get("confidence", 0.0))
        coords = tuple(float(item.get(name, 0.0)) for name in ("x1", "y1", "x2", "y2"))
        if (track_id is not None and track_id < 0) or class_id < -1:
            raise ValueError
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError
        if not all(math.isfinite(value) for value in coords) or coords[2] < coords[0] or coords[3] < coords[1]:
            raise ValueError
        return Detection(track_id, class_id, str(item.get("class_name", "")), confidence, *coords)

    @staticmethod
    def _target(item: dict[str, object]) -> PerceptionTarget:
        track_id = int(item["track_id"]); confidence = float(item.get("confidence", 0.0))
        cx = float(item.get("cx", 0.0)); cy = float(item.get("cy", 0.0))
        if track_id < 0 or not all(math.isfinite(value) for value in (confidence, cx, cy)):
            raise ValueError
        if not 0.0 <= confidence <= 1.0:
            raise ValueError
        return PerceptionTarget(track_id, str(item.get("class_name", "")), confidence, cx, cy)
