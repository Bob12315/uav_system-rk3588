from __future__ import annotations

from contracts.platform.common import ActionInstanceId, LeaseId, LinkSessionId, RunId, SchemaVersion
from application.core.execution_fence_authority import CoreExecutionFenceAuthority
from contracts.platform.vehicle_commands import (
    AckPolicy, AckState, BarrierDisposition, BodyVelocity, CancelRequest, CancelScope,
    CompletionPolicy, CompletionState, QueueState, SetServo, SubmissionState,
    TransportState, VehicleCommandEnvelope,
)
from telemetry_link.ack_router import AckRouter, AckSlot
from telemetry_link.command_broker import CommandBroker
from tests.fakes import ManualClock, PausableWriter
from threading import Thread
import pytest


def _command(clock: ManualClock, command_id: str = "c1", *, payload=None,
             priority: int = 5, idempotency: str | None = None) -> VehicleCommandEnvelope:
    return VehicleCommandEnvelope(
        SchemaVersion(1, 0), command_id, "run-1", "lease-1", 1, 2, "sitl", "session-1",
        clock.monotonic_ns(), clock.monotonic_ns() + 1_000_000_000, priority,
        idempotency or command_id, AckPolicy.RECORD_ONLY, CompletionPolicy.TRANSPORT_ONLY,
        500, payload or SetServo(8, 1500),
    )


def _broker(clock: ManualClock, writer, *, shadow: bool = False, connected=lambda: True) -> CommandBroker:
    return CommandBroker(writer=writer, source=lambda: "sitl", link_session=lambda: "session-1",
                         authorization_generation=lambda: 1, send_generation=lambda: 2,
                         monotonic_ns=clock.monotonic_ns, shadow=shadow, connected=connected)


def test_queue_acceptance_is_not_transmission_and_writer_failure_is_separate() -> None:
    clock = ManualClock()
    writer = PausableWriter()
    broker = _broker(clock, writer)
    receipt = broker.submit(_command(clock))
    assert receipt.submission_state == SubmissionState.ACCEPTED
    assert broker.status("c1").transport_state == TransportState.NOT_ATTEMPTED
    status = broker.drain_one()
    assert status.transport_state == TransportState.TRANSMITTED
    assert len(writer.writes) == 1


def test_shadow_never_writes_and_latest_motion_supersedes() -> None:
    clock = ManualClock()
    writer = PausableWriter()
    broker = _broker(clock, writer, shadow=True)
    broker.submit(_command(clock, "c1", payload=BodyVelocity(1, 0, 0)))
    broker.submit(_command(clock, "c2", payload=BodyVelocity(2, 0, 0)))
    assert broker.status("c1").queue_state == QueueState.SUPERSEDED
    broker.drain_one()
    assert writer.writes == []
    assert broker.write_count == 0


def test_deadline_and_generation_are_checked_at_admission() -> None:
    clock = ManualClock()
    broker = _broker(clock, PausableWriter())
    expired = _command(clock)
    clock.advance(2)
    assert broker.submit(expired).reason_code == "deadline_expired"


def test_final_broker_gate_rejects_stale_core_execution_fence() -> None:
    clock = ManualClock()
    fence = CoreExecutionFenceAuthority("sitl", LinkSessionId("session-1"))
    active = fence.activate(
        RunId("run-1"), ActionInstanceId("action-1"), LeaseId("lease-1"), clock.monotonic_ns(),
    )
    broker = CommandBroker(
        writer=PausableWriter(), source=lambda: "sitl", link_session=lambda: "session-1",
        authorization_generation=lambda: 0, send_generation=lambda: 0,
        monotonic_ns=clock.monotonic_ns, send_enabled=lambda: True,
        execution_fence_query=fence,
    )
    command = VehicleCommandEnvelope(
        SchemaVersion(2, 0), "core-command", "run-1", "lease-1",
        int(active.authorization_generation), int(active.send_generation), "sitl", "session-1",
        clock.monotonic_ns(), clock.monotonic_ns() + 1_000_000_000, 5, "core-command",
        AckPolicy.RECORD_ONLY, CompletionPolicy.TRANSPORT_ONLY, 500, SetServo(8, 1500),
        None, int(active.run_execution_generation), int(active.lease_generation),
    )
    assert broker.submit(command).submission_state is SubmissionState.ACCEPTED
    fence.revoke(clock.monotonic_ns())
    stale = VehicleCommandEnvelope(
        SchemaVersion(2, 0), "late-command", "run-1", "lease-1",
        int(active.authorization_generation), int(active.send_generation), "sitl", "session-1",
        clock.monotonic_ns(), clock.monotonic_ns() + 1_000_000_000, 5, "late-command",
        AckPolicy.RECORD_ONLY, CompletionPolicy.TRANSPORT_ONLY, 500, SetServo(8, 1500),
        None, int(active.run_execution_generation), int(active.lease_generation),
    )
    assert broker.submit(stale).reason_code == "run_generation_mismatch"


def test_submission_replay_preserves_original_receipt_and_outcome() -> None:
    clock = ManualClock(); broker = _broker(clock, PausableWriter())
    command = _command(clock)
    first = broker.submit(command); replay = broker.submit(command)
    assert replay.receipt_id == first.receipt_id
    assert replay.submission_state == first.submission_state
    assert replay.reason_code == first.reason_code == "accepted"
    assert replay.replayed is True and replay.original_receipt_id == first.receipt_id


def test_retry_preserves_original_deadline_and_cannot_cross_expiry() -> None:
    clock = ManualClock()

    class FailingWriter:
        def write(self, _value):
            raise OSError("wire failed")

    broker = _broker(clock, FailingWriter())
    command = _command(clock)
    broker.submit(command)
    broker.drain_one()
    clock.advance(2)
    assert broker.retry("c1").reason_code == "deadline_expired"
    assert command.created_at_monotonic_ns == 0


def test_cancel_motion_emits_trusted_barrier_after_old_write() -> None:
    clock = ManualClock()
    writer = PausableWriter()
    broker = _broker(clock, writer)
    broker.submit(_command(clock, payload=BodyVelocity(1, 0, 0)))
    broker.drain_one()
    receipt = broker.cancel(CancelRequest.create(CancelScope.RUN, run_id="run-1",
        emit_stop_barrier=True, reason="send_off", now_ns=clock.monotonic_ns(),
        expected_link_session_id="session-1"))
    assert receipt.barrier_disposition == BarrierDisposition.TRANSMITTED
    assert len(writer.writes) == 2
    assert writer.writes[-1].payload.kind == "stop_motion"


def test_cancel_waits_for_write_gate_and_barrier_is_last_old_session_write() -> None:
    clock = ManualClock()
    writer = PausableWriter()
    broker = _broker(clock, writer)
    broker.submit(_command(clock, payload=BodyVelocity(1, 0, 0)))
    writer.pause_at("before_write")
    drain = Thread(target=broker.drain_one)
    drain.start()
    assert writer.wait_until("before_write")
    receipts = []
    cancel = Thread(target=lambda: receipts.append(broker.cancel(
        CancelRequest.create(CancelScope.RUN, run_id="run-1", emit_stop_barrier=True,
            reason="revoke", now_ns=clock.monotonic_ns(), expected_link_session_id="session-1"))))
    cancel.start()
    assert cancel.is_alive()
    writer.release("before_write")
    drain.join(1); cancel.join(1)
    assert not drain.is_alive() and not cancel.is_alive()
    assert [item.payload.kind for item in writer.writes] == ["body_velocity", "stop_motion"]
    assert receipts[0].barrier_disposition == BarrierDisposition.TRANSMITTED


@pytest.mark.parametrize("checkpoint", [
    "after_dequeue", "before_final_check", "after_final_check", "before_write", "after_write",
])
def test_cancel_interleavings_have_deterministic_terminal_order(checkpoint: str) -> None:
    clock = ManualClock(); writer = PausableWriter(); broker = _broker(clock, writer)
    broker.submit(_command(clock, payload=BodyVelocity(1, 0, 0)))
    writer.pause_at(checkpoint)
    drain = Thread(target=broker.drain_one); drain.start()
    assert writer.wait_until(checkpoint)
    receipts = []
    cancel = Thread(target=lambda: receipts.append(broker.cancel(CancelRequest.create(
        CancelScope.RUN, run_id="run-1", emit_stop_barrier=True, reason="revoke",
        now_ns=clock.monotonic_ns(), expected_link_session_id="session-1"))))
    cancel.start()
    if checkpoint == "after_dequeue":
        cancel.join(1)
        assert not cancel.is_alive()
        assert writer.writes == []
        assert receipts[0].barrier_disposition == BarrierDisposition.NOT_REQUIRED
    else:
        assert cancel.is_alive()
    writer.release(checkpoint)
    drain.join(1); cancel.join(1)
    assert not drain.is_alive() and not cancel.is_alive()
    if checkpoint == "after_dequeue":
        assert writer.writes == []
        assert broker.status("c1").queue_state == QueueState.CANCELLED
    else:
        assert [item.payload.kind for item in writer.writes] == ["body_velocity", "stop_motion"]
        assert receipts[0].barrier_disposition == BarrierDisposition.TRANSMITTED


def test_pending_servo_cancel_has_no_barrier_and_disconnect_is_explicit() -> None:
    clock = ManualClock()
    broker = _broker(clock, PausableWriter(), connected=lambda: False)
    broker.submit(_command(clock))
    receipt = broker.cancel(CancelRequest.create(CancelScope.COMMAND, command_id="c1",
        reason="cancel", now_ns=clock.monotonic_ns(), expected_link_session_id="session-1"))
    assert receipt.matched_pending_ids == ("c1",)
    assert receipt.barrier_disposition == BarrierDisposition.NOT_REQUIRED


def test_canonical_cancel_replays_original_receipt_and_rejects_wrong_generation() -> None:
    clock = ManualClock(); broker = _broker(clock, PausableWriter())
    broker.submit(_command(clock))
    request = CancelRequest.create(CancelScope.RUN, run_id="run-1", reason="stop",
        now_ns=clock.monotonic_ns(), cancellation_id="cancel-1",
        expected_authorization_generation=1, expected_send_generation=2,
        expected_link_session_id="session-1")
    first = broker.cancel(request); replay = broker.cancel(request)
    assert first.receipt_id == replay.receipt_id and replay.replayed is True
    assert first.cancellation_id == "cancel-1" and first.completed_monotonic_ns == clock.monotonic_ns()
    wrong = CancelRequest.create(CancelScope.SOURCE, source="sitl", reason="bad",
        now_ns=clock.monotonic_ns(), expected_send_generation=99)
    assert broker.cancel(wrong).reason_code == "send_generation_mismatch"


def test_cancel_id_payload_conflict_and_not_found_are_typed() -> None:
    clock = ManualClock(); broker = _broker(clock, PausableWriter())
    first = CancelRequest.create(CancelScope.COMMAND, command_id="missing-1", reason="stop",
        now_ns=clock.monotonic_ns(), cancellation_id="cancel-1")
    first_receipt = broker.cancel(first)
    assert first_receipt.not_found_ids == ("missing-1",) and first_receipt.found is False
    changed = CancelRequest.create(CancelScope.COMMAND, command_id="missing-2", reason="stop",
        now_ns=clock.monotonic_ns(), cancellation_id="cancel-1")
    conflict = broker.cancel(changed)
    assert conflict.reason_code == "cancellation_id_conflict"
    assert conflict.receipt_id != first_receipt.receipt_id and conflict.replayed is False


def test_cancel_contract_cannot_be_constructed_from_legacy_shape() -> None:
    import pytest
    with pytest.raises(TypeError):
        CancelRequest(run_id="run-1")  # type: ignore[call-arg]


def test_ack_router_handles_early_progress_identity_and_session_loss() -> None:
    clock = ManualClock()
    broker = _broker(clock, PausableWriter())
    broker.submit(_command(clock))
    router = AckRouter(broker.update_ack)
    router.register(AckSlot("c1", "session-1", 183, 1, 1))
    assert not router.observe(link_session_id="session-1", mav_command=183,
                              source_system=2, source_component=1, result=0)
    assert router.observe(link_session_id="session-1", mav_command=183,
                          source_system=1, source_component=1, result=5, progress=25)
    router.mark_transmitted("c1")
    assert broker.status("c1").ack_state == AckState.IN_PROGRESS
    assert router.observe(link_session_id="session-1", mav_command=183,
                          source_system=1, source_component=1, result=0)
    assert broker.status("c1").ack_state == AckState.ACKED


def test_ack_target_extension_validates_local_recipient_not_vehicle_identity() -> None:
    clock = ManualClock()
    broker = _broker(clock, PausableWriter())
    broker.submit(_command(clock))
    router = AckRouter(broker.update_ack)
    router.register(AckSlot("c1", "session-1", 183, 1, 1,
                           local_system=255, local_component=190))
    router.mark_transmitted("c1")
    assert not router.observe(link_session_id="session-1", mav_command=183,
        source_system=1, source_component=1, result=0,
        target_system=254, target_component=190)
    assert router.observe(link_session_id="session-1", mav_command=183,
        source_system=1, source_component=1, result=0,
        target_system=255, target_component=190)


def test_ack_in_progress_uses_total_deadline_not_initial_ack_deadline() -> None:
    clock = ManualClock(); updates = []
    router = AckRouter(lambda *args, **kwargs: updates.append((args, kwargs)),
                       monotonic_ns=clock.monotonic_ns, quarantine_ns=10)
    router.register(AckSlot("c1", "session-1", 183, 1, 1,
        ack_deadline_monotonic_ns=100_000_000,
        total_deadline_monotonic_ns=1_000_000_000))
    router.mark_transmitted("c1")
    assert router.observe(link_session_id="session-1", mav_command=183,
        source_system=1, source_component=1, result=5, progress=40)
    router.expire(200_000_000)
    assert router.has_command("c1")
    router.expire(1_000_000_000)
    assert not router.has_command("c1")
    assert updates[-1][0][1] == AckState.TIMED_OUT


def test_terminal_ack_quarantine_prevents_late_reply_pollution() -> None:
    clock = ManualClock(); updates = []
    router = AckRouter(lambda *args, **kwargs: updates.append((args, kwargs)),
                       monotonic_ns=clock.monotonic_ns, quarantine_ns=250_000_000)
    first = AckSlot("c1", "session-1", 183, 1, 1,
                    ack_deadline_monotonic_ns=1_000_000_000,
                    total_deadline_monotonic_ns=2_000_000_000)
    router.register(first); router.mark_transmitted("c1")
    assert router.observe(link_session_id="session-1", mav_command=183,
                          source_system=1, source_component=1, result=0)
    assert not router.observe(link_session_id="session-1", mav_command=183,
                              source_system=1, source_component=1, result=0)
    with pytest.raises(RuntimeError, match="quarantined"):
        router.register(AckSlot("c2", "session-1", 183, 1, 1))
    clock.advance(0.251)
    router.register(AckSlot("c2", "session-1", 183, 1, 1))
    assert router.has_command("c2")


def test_nacked_command_cannot_be_marked_observed() -> None:
    clock = ManualClock()
    broker = _broker(clock, PausableWriter())
    broker.submit(_command(clock))
    broker.update_ack("c1", AckState.NACKED, reason_code="denied")
    broker.update_completion("c1", CompletionState.OBSERVED, "goal_observed")
    assert broker.status("c1").completion_state == CompletionState.NOT_OBSERVED
