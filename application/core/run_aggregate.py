from __future__ import annotations

from dataclasses import replace

from contracts.core.run import RunSnapshot, RunState, RunToken
from contracts.core.time import CoreTime
from contracts.platform.common import ResourceVersion, SourceId


_ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.PENDING: frozenset({RunState.VALIDATING, RunState.STOPPING}),
    RunState.VALIDATING: frozenset({RunState.STARTING, RunState.STOPPING, RunState.FAILED}),
    RunState.STARTING: frozenset({RunState.RUNNING, RunState.STOPPING, RunState.FAILED}),
    RunState.RUNNING: frozenset({RunState.FINALIZING, RunState.STOPPING, RunState.FAILED}),
    RunState.FINALIZING: frozenset({RunState.SUCCEEDED, RunState.STOPPING, RunState.FAILED}),
    RunState.STOPPING: frozenset({RunState.CANCELLED, RunState.FAILED}),
    RunState.SUCCEEDED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


class RunAggregate:
    def __init__(self, token: RunToken, source: SourceId, now: CoreTime) -> None:
        self.snapshot = RunSnapshot(
            token, RunState.PENDING, source,
            ResourceVersion(str(token.generation_id), 0),
            now, None, now, None, None, None, None,
        )
        self._terminalized = False

    def transition(self, state: RunState, now: CoreTime, *, reason_code: str | None = None,
                   action=None, mission=None) -> RunSnapshot:
        current = self.snapshot.state
        if current == state:
            return self.snapshot
        if state not in _ALLOWED[current]:
            raise ValueError(f"illegal Run transition: {current.value} -> {state.value}")
        if state.terminal:
            if self._terminalized:
                return self.snapshot
            self._terminalized = True
        started_at = self.snapshot.started_at
        if state is RunState.RUNNING and started_at is None:
            started_at = now
        self.snapshot = replace(
            self.snapshot,
            state=state,
            version=self.snapshot.version.next(),
            started_at=started_at,
            updated_at=now,
            finished_at=now if state.terminal else None,
            action=action if action is not None else self.snapshot.action,
            mission=mission if mission is not None else self.snapshot.mission,
            reason_code=reason_code,
        )
        return self.snapshot

    def project(self, now: CoreTime, *, action=None, mission=None, reason_code: str | None = None,
                input_ref=None, tick_sequence: int | None = None) -> RunSnapshot:
        if self.snapshot.state.terminal:
            return self.snapshot
        projected_action = action if action is not None else self.snapshot.action
        projected_mission = mission if mission is not None else self.snapshot.mission
        projected_input = input_ref if input_ref is not None else self.snapshot.last_consumed_input_ref
        projected_tick = tick_sequence if tick_sequence is not None else self.snapshot.last_advanced_tick_sequence
        if (projected_action == self.snapshot.action and projected_mission == self.snapshot.mission
                and reason_code == self.snapshot.reason_code
                and projected_input == self.snapshot.last_consumed_input_ref
                and projected_tick == self.snapshot.last_advanced_tick_sequence):
            return self.snapshot
        self.snapshot = replace(
            self.snapshot,
            version=self.snapshot.version.next(),
            updated_at=now,
            action=projected_action,
            mission=projected_mission,
            reason_code=reason_code,
            last_consumed_input_ref=projected_input,
            last_advanced_tick_sequence=projected_tick,
        )
        return self.snapshot
