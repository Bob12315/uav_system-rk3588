from datetime import datetime, timezone

from application.core.execution_fence_authority import CoreExecutionFenceAuthority
from application.core.system_control_aggregate import SystemControlAggregate
from contracts.core.common import IdempotencyKey, RequestId
from contracts.core.input_state import SendGateSnapshot
from contracts.core.system import (
    BeginMaintenanceCommand,
    EndMaintenanceCommand,
    SetSendGateCommand,
    SystemCommandDisposition,
)
from contracts.core.time import CoreTime
from contracts.platform.common import LinkSessionId, ResourceVersion


def _now(value: int = 1) -> CoreTime:
    return CoreTime(value, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")


def test_send_gate_uses_full_version_cas_and_idempotency_payload_conflict() -> None:
    fence = CoreExecutionFenceAuthority("sitl", LinkSessionId("session"))
    send = SendGateSnapshot(False, 0, ResourceVersion("send", 0))
    aggregate = SystemControlAggregate(send, fence.snapshot(), _now())
    stale = SetSendGateCommand(RequestId("r1"), IdempotencyKey("k1"), True,
                               ResourceVersion("send", 1), "test", _now())
    assert aggregate.request(stale).disposition is SystemCommandDisposition.CONFLICT
    accepted = SetSendGateCommand(RequestId("r2"), IdempotencyKey("k2"), True,
                                  send.version, "test", _now())
    receipt = aggregate.request(accepted)
    assert receipt.disposition is SystemCommandDisposition.ACCEPTED
    assert aggregate.request(accepted).replayed
    conflict = SetSendGateCommand(RequestId("r3"), IdempotencyKey("k2"), False,
                                  send.version, "different", _now())
    assert aggregate.request(conflict).disposition is SystemCommandDisposition.CONFLICT


def test_maintenance_reserves_exclusive_operation_until_matching_end() -> None:
    fence = CoreExecutionFenceAuthority("sitl", LinkSessionId("session"))
    aggregate = SystemControlAggregate(
        SendGateSnapshot(False, 0, ResourceVersion("send", 0)), fence.snapshot(), _now(),
    )
    begin = BeginMaintenanceCommand(RequestId("begin"), IdempotencyKey("begin"), 100, _now())
    receipt = aggregate.request(begin)
    assert receipt.operation_id is not None
    other = BeginMaintenanceCommand(RequestId("other"), IdempotencyKey("other"), 100, _now())
    assert aggregate.request(other).disposition is SystemCommandDisposition.CONFLICT
    aggregate.apply_pre_capture(_now(2), fence.snapshot())
    end = EndMaintenanceCommand(RequestId("end"), IdempotencyKey("end"),
                                receipt.operation_id, True, _now(3))
    assert aggregate.request(end).disposition is SystemCommandDisposition.ACCEPTED
    aggregate.apply_pre_capture(_now(3), fence.snapshot())
    assert aggregate.current().active_operation_id is None
    assert aggregate.current().quiescing is False
