from datetime import datetime, timezone

import pytest

from application.core.run_aggregate import RunAggregate
from contracts.core.run import RunState, RunToken
from contracts.core.time import CoreTime
from contracts.platform.common import RunId, RunResourceGenerationId


def test_terminal_run_is_irreversible_and_terminalizes_once() -> None:
    now = CoreTime(1, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")
    run = RunAggregate(RunToken(RunId("run"), RunResourceGenerationId("generation")), "sitl", now)
    for state in (RunState.VALIDATING, RunState.STARTING, RunState.RUNNING,
                  RunState.FINALIZING, RunState.SUCCEEDED):
        run.transition(state, now)
    terminal = run.snapshot
    assert run.transition(RunState.SUCCEEDED, now) is terminal
    with pytest.raises(ValueError):
        run.transition(RunState.RUNNING, now)
