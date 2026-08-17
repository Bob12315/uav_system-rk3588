from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from contracts.platform.common import ClockStamp, SchemaVersion
from contracts.platform.perception import (
    SetTargetLock, VisionCommandEnvelope, VisionResultState,
    VisionSubmissionReceipt,
)


def test_vision_command_envelope_has_explicit_session_clock_and_ttl() -> None:
    envelope = VisionCommandEnvelope(
        SchemaVersion(2, 0), "app", "app-session", "yolo-session", "cmd-1",
        7, 1000, ClockStamp(datetime.now(timezone.utc), 100, "app-clock"),
        SetTargetLock(42),
    )
    assert envelope.target_yolo_process_session_id == "yolo-session"
    assert envelope.sent_at.clock_domain_id == "app-clock"
    with pytest.raises(FrozenInstanceError):
        envelope.ttl_ms = 1  # type: ignore[misc]


def test_vision_submission_receipt_has_typed_replay_semantics() -> None:
    original = VisionSubmissionReceipt("receipt-1", "cmd-1", VisionResultState.ACCEPTED,
                                       "accepted")
    replay = VisionSubmissionReceipt(original.receipt_id, original.command_id,
                                     original.result_state, original.reason_code, True)
    assert replay.receipt_id == original.receipt_id
    assert replay.result_state == original.result_state
    assert replay.reason_code == original.reason_code and replay.replayed is True
