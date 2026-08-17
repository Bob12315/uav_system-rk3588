from contracts.core.action import ActionContractRef, ExitBarrier
from contracts.core.common import (
    ActionContractFingerprint,
    ActionDefinitionId,
    InputSnapshotId,
    MissionDefinitionId,
    MissionId,
    StepId,
    freeze_json,
)
from contracts.core.input_state import InputSnapshotRef
from contracts.core.mission import (
    CompleteMission,
    FailureMode,
    FailurePolicy,
    MissionDefinition,
    MissionReduceContext,
    MissionState,
    RequestExitBarrier,
    ScheduleRetryDelay,
    StartChildAction,
    StepDefinition,
)
from contracts.platform.common import ActionInstanceId, ResourceVersion, SchemaVersion
from missions.core.mission_orchestrator import MissionOrchestrator


def _context(cycle: str = "cycle") -> MissionReduceContext:
    return MissionReduceContext(
        cycle,
        InputSnapshotRef(InputSnapshotId("input"), ResourceVersion("input", 1)),
    )


def _definition(policy: FailurePolicy = FailurePolicy(FailureMode.FAIL)) -> MissionDefinition:
    ref = ActionContractRef(ActionDefinitionId("dummy"), "v1", ActionContractFingerprint("fp"))
    step = StepDefinition(StepId("step"), "step", ref, freeze_json({}), None, policy, ExitBarrier.NONE)
    return MissionDefinition(SchemaVersion(3, 0), MissionDefinitionId("mission"), "r1", "Mission",
                             (step,), 8, 8, 4)


def test_even_none_exit_barrier_revokes_child_lease_before_mission_completion() -> None:
    orchestrator = MissionOrchestrator(MissionId("mission-run"), _definition())
    start = orchestrator.start(_context(), freeze_json({}))
    assert isinstance(start[0], StartChildAction)
    token = start[0].step_token
    action_id = ActionInstanceId("action")
    orchestrator.child_started(_context(), token, action_id)
    intents = orchestrator.child_terminal(
        _context(), action_id, succeeded=True, output=None, reason_code=None,
    )
    assert isinstance(intents[0], RequestExitBarrier)
    assert intents[0].barrier is ExitBarrier.NONE
    assert orchestrator.snapshot.state is MissionState.WAITING_BARRIER
    completed = orchestrator.barrier_completed(_context(), token, succeeded=True)
    assert isinstance(completed[0], CompleteMission)
    assert completed[0].succeeded


def test_retry_is_bounded_and_uses_typed_timer_intent() -> None:
    orchestrator = MissionOrchestrator(
        MissionId("mission-run"),
        _definition(FailurePolicy(FailureMode.RETRY, max_retries=1, retry_delay_ms=25)),
    )
    start = orchestrator.start(_context("c1"), freeze_json({}))
    action_id = ActionInstanceId("action-1")
    orchestrator.child_started(_context("c1"), start[0].step_token, action_id)
    barrier = orchestrator.child_terminal(
        _context("c1"), action_id, succeeded=False, output=None, reason_code="failed",
    )[0]
    retry = orchestrator.barrier_completed(_context("c1"), barrier.step_token, succeeded=True)
    assert isinstance(retry[0], ScheduleRetryDelay)
    restarted = orchestrator.retry_delay_elapsed(_context("c2"), retry[0].step_token)
    assert isinstance(restarted[0], StartChildAction)
