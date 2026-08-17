from datetime import datetime, timezone

from contracts.core.action import (
    ActionState,
    ActionTickContext,
    EffectAckFeedbackState,
    EffectAdmissionFeedbackState,
    EffectCompletionFeedbackState,
    EffectFeedback,
    EffectLifecycleFeedback,
    EffectTransportFeedbackState,
)
from contracts.core.common import (
    CoreCycleId,
    EffectId,
    InputSnapshotId,
    SchedulerSessionId,
    freeze_json,
)
from contracts.core.input_state import (
    ComponentFreshness,
    CycleCorrelation,
    FreshnessState,
    FusionSnapshot,
    FusionState,
    InputSnapshotRef,
    RuntimeInputSnapshot,
    SendGateSnapshot,
)
from contracts.core.time import CoreTime
from contracts.platform.common import ActionInstanceId, ResourceVersion, SchemaVersion
from missions.core.action_runner import ActionRunner
from missions.core.production_catalog import create_production_catalog


def _context(feedback=()):
    now = CoreTime(1, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")
    ref = InputSnapshotRef(InputSnapshotId("input"), ResourceVersion("input", 1))
    snapshot = RuntimeInputSnapshot(
        SchemaVersion(1, 0), ref, now,
        None, ComponentFreshness(FreshnessState.UNAVAILABLE, None),
        None, ComponentFreshness(FreshnessState.UNAVAILABLE, None),
        None, ComponentFreshness(FreshnessState.UNAVAILABLE, None),
        FusionSnapshot(FusionState.UNAVAILABLE, None, None, None, freeze_json({})),
        SendGateSnapshot(True, 1, ResourceVersion("send", 1)),
    )
    correlation = CycleCorrelation(SchedulerSessionId("scheduler"), CoreCycleId("cycle"), 1, ref)
    return ActionTickContext(correlation, now, snapshot, feedback)


def test_native_land_waits_for_normalized_feedback_before_success() -> None:
    registration = next(
        item for item in create_production_catalog().all()
        if item.definition.name == "land"
    )
    runner = ActionRunner()
    snapshot, effects = runner.start(
        ActionInstanceId("action"), registration, freeze_json({}), _context(),
    )
    assert snapshot.state is ActionState.RUNNING
    assert effects == ()
    snapshot, effects = runner.step(_context())
    assert snapshot.state is ActionState.RUNNING
    assert len(effects) == 1

    lifecycle = EffectLifecycleFeedback(
        EffectAdmissionFeedbackState.ACCEPTED,
        EffectTransportFeedbackState.TRANSMITTED,
        EffectAckFeedbackState.NOT_EXPECTED,
        EffectCompletionFeedbackState.NOT_OBSERVED,
        None, ResourceVersion("status", 1), _context().now,
    )
    feedback = EffectFeedback(EffectId("effect"), effects[0].local_token, 1, lifecycle, None)
    snapshot, effects = runner.step(_context((feedback,)))
    assert snapshot.state is ActionState.SUCCEEDED
    assert effects == ()
