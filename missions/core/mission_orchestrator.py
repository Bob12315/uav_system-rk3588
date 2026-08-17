from __future__ import annotations

from dataclasses import replace

from contracts.core.action import ActionOutputEnvelope, ExitBarrier
from contracts.core.common import FrozenObject, MissionId
from contracts.core.mission import (
    CompleteMission,
    FailureMode,
    MissionDefinition,
    MissionIntent,
    MissionReduceContext,
    MissionSnapshot,
    MissionState,
    PendingMissionTransition,
    RequestExitBarrier,
    ScheduleRetryDelay,
    StartChildAction,
    StepDefinition,
    StepExecutionToken,
)
from contracts.platform.common import ActionInstanceId, ResourceVersion


class MissionOrchestrator:
    """Pure event reducer.  It returns intents and never calls Action/runtime Ports."""

    def __init__(self, mission_id: MissionId, definition: MissionDefinition) -> None:
        self.definition = definition
        self._index = 0
        self._step_generation = 0
        self._attempts: dict[str, int] = {}
        self._transitions_this_cycle = 0
        self._last_cycle_id: str | None = None
        self.snapshot = MissionSnapshot(
            mission_id,
            definition.definition_id,
            MissionState.IDLE,
            None,
            None,
            None,
            ResourceVersion(str(mission_id), 0),
            0,
            0,
            None,
        )

    def start(self, context: MissionReduceContext, inputs: FrozenObject) -> tuple[MissionIntent, ...]:
        if self.snapshot.state is not MissionState.IDLE:
            return ()
        return self._start_step(context, self.definition.steps[0], inputs)

    def child_started(
        self,
        context: MissionReduceContext,
        token: StepExecutionToken,
        instance_id: ActionInstanceId,
    ) -> tuple[MissionIntent, ...]:
        if token != self.snapshot.current_step_token or self.snapshot.state is not MissionState.STARTING_CHILD:
            return ()
        self._mutate(context, state=MissionState.RUNNING_CHILD, child_instance_id=instance_id)
        return ()

    def child_terminal(
        self,
        context: MissionReduceContext,
        instance_id: ActionInstanceId,
        *,
        succeeded: bool,
        output: ActionOutputEnvelope | None,
        reason_code: str | None,
    ) -> tuple[MissionIntent, ...]:
        if self.snapshot.state is not MissionState.RUNNING_CHILD or instance_id != self.snapshot.child_instance_id:
            return ()
        step = self.definition.steps[self._index]
        destination = self._destination(step, succeeded)
        pending = PendingMissionTransition(
            self.snapshot.current_step_token,
            instance_id,
            succeeded,
            output,
            reason_code,
            destination.step_id if destination is not None else None,
            step.exit_barrier,
        )
        # Every child exit crosses a lease/cancel boundary.  NONE means no
        # physical stop barrier is required, not that the old lease may stay
        # live while the next child is admitted.
        self._mutate(context, state=MissionState.WAITING_BARRIER, pending_transition=pending)
        return (RequestExitBarrier(pending.step_token, step.exit_barrier),)

    def barrier_completed(
        self, context: MissionReduceContext, token: StepExecutionToken, *, succeeded: bool
    ) -> tuple[MissionIntent, ...]:
        pending = self.snapshot.pending_transition
        if self.snapshot.state is not MissionState.WAITING_BARRIER or pending is None or token != pending.step_token:
            return ()
        if not succeeded:
            self._mutate(context, state=MissionState.FAILED, reason_code="exit_barrier_failed")
            return (CompleteMission(False, "exit_barrier_failed"),)
        self._mutate(context, state=MissionState.FINALIZING_CHILD)
        return self._finish_transition(context)

    def retry_delay_elapsed(self, context: MissionReduceContext, token: StepExecutionToken) -> tuple[MissionIntent, ...]:
        if self.snapshot.state is not MissionState.WAITING_RETRY or token != self.snapshot.current_step_token:
            return ()
        return self._start_step(context, self.definition.steps[self._index], FrozenObject(()))

    def skip(self, context: MissionReduceContext, token: StepExecutionToken) -> tuple[MissionIntent, ...]:
        if token != self.snapshot.current_step_token or self.snapshot.state not in {
            MissionState.STARTING_CHILD, MissionState.RUNNING_CHILD, MissionState.WAITING_RETRY,
        }:
            return ()
        if self._index + 1 >= len(self.definition.steps):
            self._mutate(context, state=MissionState.SUCCEEDED, reason_code="skipped_last_step")
            return (CompleteMission(True, "skipped_last_step"),)
        self._index += 1
        return self._start_step(context, self.definition.steps[self._index], FrozenObject(()))

    def stop(self, context: MissionReduceContext) -> tuple[MissionIntent, ...]:
        if self.snapshot.state in {MissionState.SUCCEEDED, MissionState.FAILED, MissionState.STOPPED}:
            return ()
        self._mutate(context, state=MissionState.STOPPED, reason_code="stopped")
        return (CompleteMission(False, "stopped"),)

    def _finish_transition(self, context: MissionReduceContext) -> tuple[MissionIntent, ...]:
        self._consume_transition_budget(context)
        pending = self.snapshot.pending_transition
        assert pending is not None
        step = self.definition.steps[self._index]
        if pending.succeeded or step.failure_policy.mode is FailureMode.CONTINUE:
            if pending.destination_step_id is None:
                self._mutate(context, state=MissionState.SUCCEEDED, pending_transition=None, reason_code="mission_done")
                return (CompleteMission(True, "mission_done"),)
            self._index = self._index_for(pending.destination_step_id)
            return self._start_step(context, self.definition.steps[self._index], FrozenObject(()))
        if step.failure_policy.mode is FailureMode.RETRY:
            attempts = self._attempts.get(str(step.step_id), 0)
            if attempts <= step.failure_policy.max_retries:
                self._mutate(context, state=MissionState.WAITING_RETRY, pending_transition=None)
                return (ScheduleRetryDelay(self.snapshot.current_step_token, step.failure_policy.retry_delay_ms),)
            if step.failure_policy.jump_target is not None:
                self._index = self._index_for(step.failure_policy.jump_target)
                return self._start_step(context, self.definition.steps[self._index], FrozenObject(()))
        if step.failure_policy.mode is FailureMode.JUMP and pending.destination_step_id is not None:
            self._index = self._index_for(pending.destination_step_id)
            return self._start_step(context, self.definition.steps[self._index], FrozenObject(()))
        self._mutate(context, state=MissionState.FAILED, pending_transition=None,
                     reason_code=pending.reason_code or "child_failed")
        return (CompleteMission(False, self.snapshot.reason_code or "child_failed"),)

    def _destination(self, step: StepDefinition, succeeded: bool) -> StepDefinition | None:
        if not succeeded and step.failure_policy.mode is FailureMode.JUMP:
            return self.definition.steps[self._index_for(step.failure_policy.jump_target)]
        if not succeeded and step.failure_policy.mode not in {FailureMode.CONTINUE}:
            return None
        return self.definition.steps[self._index + 1] if self._index + 1 < len(self.definition.steps) else None

    def _start_step(
        self, context: MissionReduceContext, step: StepDefinition, resolved_parameters: FrozenObject
    ) -> tuple[MissionIntent, ...]:
        if self.snapshot.total_starts >= self.definition.max_total_starts:
            self._mutate(context, state=MissionState.FAILED, reason_code="start_budget_exhausted")
            return (CompleteMission(False, "start_budget_exhausted"),)
        self._step_generation += 1
        token = StepExecutionToken(self.snapshot.mission_id, step.step_id, self._step_generation)
        self._attempts[str(step.step_id)] = self._attempts.get(str(step.step_id), 0) + 1
        self._mutate(
            context,
            state=MissionState.STARTING_CHILD,
            current_step_token=token,
            child_instance_id=None,
            pending_transition=None,
            total_starts=self.snapshot.total_starts + 1,
        )
        params = step.parameters if not resolved_parameters else resolved_parameters
        return (StartChildAction(step, token, params),)

    def _consume_transition_budget(self, context: MissionReduceContext) -> None:
        if context.cycle_id != self._last_cycle_id:
            self._last_cycle_id = context.cycle_id
            self._transitions_this_cycle = 0
        self._transitions_this_cycle += 1
        if self._transitions_this_cycle > self.definition.max_transitions_per_cycle:
            raise RuntimeError("mission per-cycle transition budget exhausted")
        if self.snapshot.total_transitions >= self.definition.max_total_transitions:
            raise RuntimeError("mission total transition budget exhausted")
        self.snapshot = replace(
            self.snapshot,
            total_transitions=self.snapshot.total_transitions + 1,
            version=self.snapshot.version.next(),
        )

    def _mutate(self, context: MissionReduceContext, **changes: object) -> None:
        self.snapshot = replace(
            self.snapshot,
            last_consumed_input_ref=context.input_ref,
            version=self.snapshot.version.next(),
            **changes,
        )

    def _index_for(self, step_id) -> int:
        for index, step in enumerate(self.definition.steps):
            if step.step_id == step_id:
                return index
        raise KeyError(step_id)
