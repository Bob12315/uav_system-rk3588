from datetime import datetime, timezone

from contracts.core.common import InputSnapshotId
from contracts.core.effects import BodyVelocityTarget, SetServo
from contracts.core.execution import SafetyContext, SafetyDisposition
from contracts.core.input_state import InputSnapshotRef
from contracts.core.time import CoreTime
from contracts.platform.common import ResourceVersion
from execution.safety_policy import SafetyPolicy, SafetyPolicyConfig


def context(send: bool) -> SafetyContext:
    return SafetyContext(
        InputSnapshotRef(InputSnapshotId("s"), ResourceVersion("g", 1)), send,
        "sitl", "link", "v1",
        CoreTime(1, datetime(2026, 1, 1, tzinfo=timezone.utc), "test"),
    )


def test_send_gate_and_payload_profile_fail_closed() -> None:
    policy = SafetyPolicy(SafetyPolicyConfig())
    assert policy.evaluate(BodyVelocityTarget(0.1, 0, 0), context(False)).disposition is SafetyDisposition.REJECT
    assert policy.evaluate(SetServo(8, 1900), context(True)).disposition is SafetyDisposition.REJECT
    assert policy.evaluate(SetServo(9, 1900), context(True)).disposition is SafetyDisposition.ALLOW


def test_body_velocity_is_clamped_without_mutating_original() -> None:
    policy = SafetyPolicy(SafetyPolicyConfig(max_body_velocity_mps=1.0))
    effect = BodyVelocityTarget(2.0, -2.0, 0.0)
    decision = policy.evaluate(effect, context(True))
    assert decision.disposition is SafetyDisposition.MODIFY
    assert decision.effective == BodyVelocityTarget(1.0, -1.0, 0.0)
    assert effect.forward_mps == 2.0
