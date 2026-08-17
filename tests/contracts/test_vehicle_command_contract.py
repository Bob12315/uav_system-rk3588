from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from contracts.platform.common import SchemaVersion
from contracts.platform.vehicle_commands import (
    COMMAND_POLICY, AckPolicy, Arm, BodyVelocity, CancelRequest, CancelScope,
    CompletionPolicy, QueueState, SetServo, VehicleCommandEnvelope,
)


def _envelope(payload=Arm()) -> VehicleCommandEnvelope:
    return VehicleCommandEnvelope(
        SchemaVersion(1, 0), "cmd-1", "run-1", "lease-1", 1, 2, "sitl", "session-1",
        10, 100, 5, "idem-1", AckPolicy.RECORD_ONLY,
        CompletionPolicy.STATE_OBSERVED, 500, payload,
    )


def test_command_contract_is_immutable_and_has_independent_policy_axes() -> None:
    command = _envelope()
    with pytest.raises(FrozenInstanceError):
        command.priority = 1  # type: ignore[misc]
    assert command.ack_policy == AckPolicy.RECORD_ONLY
    assert command.completion_policy == CompletionPolicy.STATE_OBSERVED
    assert QueueState.SUPERSEDED.value == "SUPERSEDED"


def test_policy_table_covers_entire_public_union() -> None:
    assert set(COMMAND_POLICY) == {
        "set_mode", "arm", "takeoff", "land", "local_position", "global_position",
        "body_velocity", "condition_yaw", "change_speed", "set_servo", "gimbal_angle",
        "gimbal_rate", "stop_motion",
    }
    assert COMMAND_POLICY["body_velocity"] == (AckPolicy.DISABLED, CompletionPolicy.TRANSPORT_ONLY)


def test_invalid_deadline_and_servo_are_rejected() -> None:
    with pytest.raises(ValueError, match="deadline"):
        VehicleCommandEnvelope(SchemaVersion(1, 0), "c", "r", "l", 0, 0, "sitl", "s",
                               10, 10, 1, "i", AckPolicy.DISABLED,
                               CompletionPolicy.TRANSPORT_ONLY, 0, BodyVelocity(0, 0, 0))
    with pytest.raises(ValueError, match="servo"):
        _envelope(SetServo(17, 1500))


def test_canonical_cancel_has_one_scope_identity_and_immutable_deadline() -> None:
    request = CancelRequest.create(CancelScope.RUN, run_id="run-1", reason="operator_stop",
                                   now_ns=100, timeout_ms=25, cancellation_id="cancel-1",
                                   expected_authorization_generation=3,
                                   expected_send_generation=4,
                                   expected_link_session_id="session-1")
    assert request.cancellation_id == "cancel-1"
    assert request.deadline_monotonic_ns == 25_000_100
    assert request.run_id == "run-1" and request.command_id is None
    with pytest.raises(FrozenInstanceError):
        request.reason_code = "changed"  # type: ignore[misc]


def test_canonical_cancel_rejects_missing_or_unrelated_scope_identity() -> None:
    with pytest.raises(ValueError, match="matching identifier"):
        CancelRequest.create(CancelScope.COMMAND, reason="bad", now_ns=1)
    with pytest.raises(ValueError, match="unrelated identifiers"):
        CancelRequest.create(CancelScope.RUN, run_id="run-1", command_id="cmd-1",
                             reason="bad", now_ns=1)
