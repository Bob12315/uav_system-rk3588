from datetime import datetime, timezone

import pytest

from application.core.run_aggregate import RunAggregate
from contracts.core.common import RunId, RunResourceGenerationId, freeze_json
from contracts.core.run import RunState, RunToken
from contracts.core.time import CoreTime, ManualCoreClock


def now(ns: int = 1) -> CoreTime:
    return CoreTime(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")


def test_run_terminalizes_once_and_never_returns_to_running() -> None:
    aggregate = RunAggregate(RunToken(RunId("r"), RunResourceGenerationId("g")), "sitl", now())
    for state in (RunState.VALIDATING, RunState.STARTING, RunState.RUNNING,
                  RunState.FINALIZING, RunState.SUCCEEDED):
        aggregate.transition(state, now(aggregate.snapshot.version.revision + 2))
    terminal = aggregate.snapshot
    with pytest.raises(ValueError):
        aggregate.transition(RunState.RUNNING, now(99))
    assert aggregate.snapshot == terminal


def test_manual_clock_rejects_backward_time() -> None:
    clock = ManualCoreClock(now(10))
    assert clock.advance_ns(5).monotonic_ns == 15
    with pytest.raises(ValueError):
        clock.advance_ns(-1)
