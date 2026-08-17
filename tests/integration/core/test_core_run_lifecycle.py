from datetime import datetime, timezone

from application.core.effect_delivery import EffectDeliveryTracker
from application.core.execution_fence_authority import CoreExecutionFenceAuthority
from application.core.run_coordinator import RunCoordinator
from contracts.core.action import (
    ActionContractRef,
    ActionDefinition,
    ActionRegistration,
    ActionStepResult,
    ActionStepState,
    ActionTickContext,
    SchemaRef,
)
from contracts.core.common import (
    ActionContractFingerprint,
    ActionDefinitionId,
    CoreCycleId,
    IdempotencyKey,
    InputSnapshotId,
    RequestId,
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
from contracts.core.run import (
    ActionRunTarget,
    RunAuthorizationRequest,
    RunState,
    StartRunCommand,
)
from contracts.core.run_io import ResultProjectionPolicy, RunRecordingPolicy
from contracts.core.time import CoreTime
from contracts.platform.common import LinkSessionId, ResourceVersion, SchemaVersion
from contracts.platform.vehicle_commands import BarrierDisposition, CancellationReceipt
from missions.core.action_catalog import ActionRegistrationCatalog
from missions.core.codecs import FrozenJsonCodec


class TwoTickAction:
    def start(self, params, context: ActionTickContext):
        return ActionStepResult(ActionStepState.RUNNING)

    def step(self, context: ActionTickContext):
        return ActionStepResult(ActionStepState.SUCCEEDED, output={"ok": True})

    def stop(self, context: ActionTickContext):
        return None


def test_standalone_action_is_advanced_only_by_coordinator_cycle() -> None:
    ref = ActionContractRef(ActionDefinitionId("dummy"), "v1", ActionContractFingerprint("fp"))
    definition = ActionDefinition(
        ref, "dummy", "Dummy", "test", SchemaRef("params", SchemaVersion(1, 0)),
        SchemaRef("output", SchemaVersion(1, 0)), frozenset(), frozenset(), (),
    )
    catalog = ActionRegistrationCatalog((ActionRegistration(
        definition, TwoTickAction, FrozenJsonCodec(require_object=True), FrozenJsonCodec(),
    ),))
    fence = CoreExecutionFenceAuthority("sitl", LinkSessionId("link"))
    coordinator = RunCoordinator(catalog, fence, EffectDeliveryTracker())
    now = CoreTime(10, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")
    snapshot_ref = InputSnapshotRef(InputSnapshotId("input"), ResourceVersion("input-generation", 1))
    snapshot = RuntimeInputSnapshot(
        SchemaVersion(1, 0), snapshot_ref, now,
        None, ComponentFreshness(FreshnessState.UNAVAILABLE, None),
        None, ComponentFreshness(FreshnessState.UNAVAILABLE, None),
        None, ComponentFreshness(FreshnessState.UNAVAILABLE, None),
        FusionSnapshot(FusionState.UNAVAILABLE, None, None, None, freeze_json({})),
        SendGateSnapshot(False, 0, ResourceVersion("send", 0)),
    )
    command = StartRunCommand(
        RequestId("request"), IdempotencyKey("key"), ActionRunTarget(ref, freeze_json({})),
        "sitl", RunAuthorizationRequest("operator", "request", True),
        RunRecordingPolicy(), ResultProjectionPolicy(), now,
    )
    receipt = coordinator.request_start(command)
    assert receipt.disposition.value == "accepted"
    assert coordinator.current() is None  # request threads never advance
    correlation = CycleCorrelation(SchedulerSessionId("scheduler"), CoreCycleId("cycle-1"), 1, snapshot_ref)
    first = coordinator.advance(snapshot, correlation, now)
    coordinator.commit(first, (), (), now)
    assert coordinator.current().state is RunState.RUNNING
    second = coordinator.advance(snapshot, correlation, now)
    assert coordinator.current().state is RunState.FINALIZING
    request = second.cancellations[0]
    cancellation = CancellationReceipt(
        request.schema, request.cancellation_id, (), (), (str(command.request_id),),
        None, BarrierDisposition.NOT_REQUIRED, "sitl", "link", now.monotonic_ns,
        "action_succeeded", "receipt",
    )
    coordinator.commit(second, (), (cancellation,), now)
    assert coordinator.current().state is RunState.SUCCEEDED
