from __future__ import annotations

from types import SimpleNamespace

from application.command_observer import CommandCompletionObserver
from contracts.platform.common import SchemaVersion
from contracts.platform.vehicle_commands import (
    AckPolicy, AckState, CommandStatusSnapshot, CompletionPolicy, CompletionState,
    QueueState, SetMode, SubmissionState, TransportState, VehicleCommandEnvelope,
)


def _command():
    return VehicleCommandEnvelope(SchemaVersion(1, 0), "c", "r", "l", 1, 1, "sitl", "s",
        10, 100, 1, "i", AckPolicy.RECORD_ONLY, CompletionPolicy.STATE_OBSERVED, 10, SetMode("GUIDED"))


def _status(ack=AckState.WAITING):
    return CommandStatusSnapshot("c", SubmissionState.ACCEPTED, QueueState.DEQUEUED,
        TransportState.TRANSMITTED, ack, CompletionState.NOT_OBSERVED, 2, "transmitted", 20)


def _vehicle(monotonic_ns=30, session="s", mode="GUIDED"):
    return SimpleNamespace(link_session_id=session, captured_at=SimpleNamespace(monotonic_ns=monotonic_ns),
        mode=mode, armed=False, in_air=False, landed=True, relative_altitude_m=0.0,
        local_valid=False, global_valid=False)


def test_pretransmission_cache_is_not_completion() -> None:
    calls = []
    observer = CommandCompletionObserver(lambda *args: calls.append(args), monotonic_ns=lambda: 30)
    assert not observer.observe(_command(), _status(), _vehicle(monotonic_ns=20))
    assert calls == []


def test_ack_timeout_can_later_observe_but_nack_cannot() -> None:
    calls = []
    observer = CommandCompletionObserver(lambda *args: calls.append(args), monotonic_ns=lambda: 30)
    assert observer.observe(_command(), _status(AckState.TIMED_OUT), _vehicle())
    assert calls[-1][1] == CompletionState.OBSERVED
    calls.clear()
    assert not observer.observe(_command(), _status(AckState.NACKED), _vehicle())
    assert calls == []


def test_session_loss_and_goal_timeout_are_explicit() -> None:
    calls = []
    observer = CommandCompletionObserver(lambda *args: calls.append(args), monotonic_ns=lambda: 100)
    observer.observe(_command(), _status(), _vehicle(session="new"))
    assert calls[-1][1] == CompletionState.SESSION_LOST
    calls.clear()
    observer.observe(_command(), _status(), _vehicle(monotonic_ns=100, mode="LOITER"))
    assert calls[-1][1] == CompletionState.GOAL_TIMEOUT


def test_goal_timeout_does_not_require_a_new_vehicle_sample() -> None:
    calls = []
    observer = CommandCompletionObserver(lambda *args: calls.append(args), monotonic_ns=lambda: 101)
    assert not observer.observe(_command(), _status(), _vehicle(monotonic_ns=20, mode="LOITER"))
    assert calls[-1][1] == CompletionState.GOAL_TIMEOUT
