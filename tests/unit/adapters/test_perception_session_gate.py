from __future__ import annotations

import json

from application.perception_session import PerceptionSessionGate


def _packet(message_type: str, session: str, sequence: int = 0, *, sent_ns: int = 0,
            producer_id: str = "yolo", clock_domain: str | None = None, **payload):
    if message_type == "perception":
        payload.setdefault("image_width_px", 640)
        payload.setdefault("image_height_px", 480)
        payload.setdefault("captured_at_monotonic_ns", max(0, sent_ns))
    data = {
        "schema_major": 2, "schema_minor": 0, "message_type": message_type,
        "sequence": sequence, "sent_at_utc": "2026-08-16T00:00:00+00:00", "ttl_ms": 1000,
        "sent_at_monotonic_ns": sent_ns,
        "producer_id": producer_id, "yolo_process_session_id": session,
        "producer_clock_domain_id": clock_domain or f"clock-{session}", "payload": payload,
    }
    return json.dumps(data).encode()


def test_unknown_frame_cannot_activate_and_late_sessions_stay_retired() -> None:
    gate = PerceptionSessionGate(tombstone_capacity=2)
    assert gate.ingest(_packet("perception", "A", 1), received_at_monotonic_ns=1)[0] == "session_mismatch"
    assert gate.ingest(_packet("hello", "A"), received_at_monotonic_ns=2)[0] == "hello"
    assert gate.ingest(_packet("hello", "B"), received_at_monotonic_ns=3)[0] == "hello"
    assert gate.ingest(_packet("perception", "A", 2), received_at_monotonic_ns=4)[0] == "session_mismatch"
    assert gate.ingest(_packet("hello", "A"), received_at_monotonic_ns=5)[0] == "retired_session"
    assert gate.tombstones == ("A",)


def test_frame_is_atomic_and_sequence_may_restart_after_hello() -> None:
    gate = PerceptionSessionGate(max_detections=2)
    gate.ingest(_packet("hello", "A"), received_at_monotonic_ns=1)
    status, frame = gate.ingest(_packet("perception", "A", 0, frame_id=9, image_width_px=640,
        image_height_px=480, target={"track_id": 7, "cx": 10, "cy": 20},
        detections=[{"track_id": 7, "class_id": 1, "x1": 1, "y1": 2, "x2": 3, "y2": 4}],
        original_detection_count=1, truncated=False), received_at_monotonic_ns=2)
    assert status == "perception"
    assert frame.target.track_id == frame.detections[0].track_id == 7
    gate.ingest(_packet("hello", "B"), received_at_monotonic_ns=3)
    assert gate.ingest(_packet("perception", "B", 0, detections=[]), received_at_monotonic_ns=4)[0] == "perception"


def test_size_schema_and_detection_limits_fail_before_unbounded_state() -> None:
    gate = PerceptionSessionGate(max_datagram_bytes=20, max_detections=1)
    assert gate.ingest(b"x" * 21, received_at_monotonic_ns=1)[0] == "oversize"
    gate = PerceptionSessionGate(max_detections=1)
    gate.ingest(_packet("hello", "A"), received_at_monotonic_ns=1)
    assert gate.ingest(_packet("perception", "A", 1, detections=[{}, {}]), received_at_monotonic_ns=2)[0] == "detections_limit"


def test_v1_is_still_recognized_during_dual_read() -> None:
    gate = PerceptionSessionGate()
    assert gate.ingest(json.dumps({"schema_version": 1}).encode(), received_at_monotonic_ns=1)[0] == "v1"


def test_receiver_local_ttl_and_clock_identity_are_enforced() -> None:
    gate = PerceptionSessionGate()
    gate.ingest(_packet("hello", "A"), received_at_monotonic_ns=10)
    assert gate.ingest(_packet("perception", "A", 1, sent_ns=0),
                       received_at_monotonic_ns=2_000_000_000)[0] == "perception"
    assert gate.ingest(_packet("perception", "A", 1, sent_ns=20,
                               clock_domain="wrong"), received_at_monotonic_ns=21)[0] == "identity_mismatch"


def test_tombstone_lru_is_bounded_across_three_sessions() -> None:
    gate = PerceptionSessionGate(tombstone_capacity=2)
    for index, session in enumerate(("A", "B", "C"), 1):
        assert gate.ingest(_packet("hello", session), received_at_monotonic_ns=index)[0] == "hello"
    assert gate.tombstones == ("A", "B")
    assert gate.ingest(_packet("perception", "B", 0), received_at_monotonic_ns=5)[0] == "session_mismatch"


def test_malformed_and_repeated_hello_cannot_reset_active_sequence() -> None:
    gate = PerceptionSessionGate()
    assert gate.ingest(_packet("hello", "A"), received_at_monotonic_ns=1)[0] == "hello"
    assert gate.ingest(_packet("perception", "A", 5), received_at_monotonic_ns=2)[0] == "perception"
    malformed = json.loads(_packet("hello", "B")); malformed["payload"] = {"capabilities": [1]}
    assert gate.ingest(json.dumps(malformed).encode(), received_at_monotonic_ns=3)[0] == "malformed"
    assert gate.active_session_id == "A" and gate.last_sequence == 5
    assert gate.ingest(_packet("hello", "A"), received_at_monotonic_ns=4)[0] == "hello_heartbeat"
    assert gate.last_sequence == 5
    assert gate.ingest(_packet("perception", "A", 4), received_at_monotonic_ns=5)[0] == "out_of_order"


def test_exact_datagram_limit_is_accepted_and_one_byte_more_is_rejected() -> None:
    base = _packet("hello", "A")
    limit = len(base) + 8
    gate = PerceptionSessionGate(max_datagram_bytes=limit)
    exact = base + b" " * (limit - len(base))
    assert len(exact) == limit and gate.ingest(exact, received_at_monotonic_ns=1)[0] == "hello"
    assert gate.ingest(exact + b" ", received_at_monotonic_ns=2)[0] == "oversize"
