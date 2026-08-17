from __future__ import annotations

from dataclasses import dataclass
import threading
import uuid

from contracts.core.action import ActionState, ActionTickContext, EffectEmission, ExitBarrier
from contracts.core.common import EffectId, IdempotencyKey, freeze_json, thaw_json
from contracts.core.execution import (
    DispatchReceipt,
    EffectDispatchAttempt,
    EffectEnvelope,
    ExecutionLease,
    RunAuthorizationGrant,
)
from contracts.core.effects import EffectKind
from contracts.core.input_state import CycleCorrelation, RuntimeInputSnapshot
from contracts.core.mission import (
    CompleteMission,
    MissionReduceContext,
    MissionState,
    RequestExitBarrier,
    ScheduleRetryDelay,
    StartChildAction,
)
from contracts.core.run import (
    ActionRunTarget,
    ClearTerminalCommand,
    MissionRunTarget,
    RunCommandDisposition,
    RunCommandReceipt,
    RunSnapshot,
    RunState,
    RunToken,
    SkipStepCommand,
    StartRunCommand,
    StopRunCommand,
)
from contracts.core.time import CoreTime
from contracts.platform.common import (
    ActionInstanceId,
    AuthorizationGeneration,
    LeaseGeneration,
    LeaseId,
    LinkSessionId,
    ResourceVersion,
    RunId,
    RunResourceGenerationId,
    SchemaVersion,
)
from contracts.platform.vehicle_commands import CancelRequest, CancelScope, CancellationReceipt

from missions.core.action_catalog import ActionRegistrationCatalog
from missions.core.action_runner import ActionRunner
from missions.core.blackboard import BlackboardEntry, BlackboardSnapshot, resolve_compiled_parameters
from missions.core.mission_orchestrator import MissionOrchestrator

from .effect_delivery import EffectDeliveryTracker
from .execution_fence_authority import CoreExecutionFenceAuthority
from .run_aggregate import RunAggregate


@dataclass(frozen=True, slots=True)
class CoreAdvancePlan:
    correlation: CycleCorrelation
    run_token: RunToken | None
    dispatch_attempts: tuple[EffectDispatchAttempt, ...]
    cancellations: tuple[CancelRequest, ...]
    run_snapshot: RunSnapshot | None


class RunCoordinator:
    """The sole top-level Run and cancel-policy owner."""

    def __init__(
        self,
        registrations: ActionRegistrationCatalog,
        fence: CoreExecutionFenceAuthority,
        delivery: EffectDeliveryTracker,
    ) -> None:
        self._registrations = registrations
        self._fence = fence
        self._delivery = delivery
        self._lock = threading.RLock()
        self._intents: list[object] = []
        self._receipts: dict[IdempotencyKey, tuple[object, RunCommandReceipt]] = {}
        self._run: RunAggregate | None = None
        self._target: ActionRunTarget | MissionRunTarget | None = None
        self._runner = ActionRunner()
        self._mission: MissionOrchestrator | None = None
        self._grant: RunAuthorizationGrant | None = None
        self._lease: ExecutionLease | None = None
        self._lease_send_generation = None
        self._emission_sequence = 0
        self._pending_cancel = False
        self._pending_terminal_state: RunState | None = None
        self._pending_mission_barrier = None
        self._pending_retry: tuple[object, int] | None = None
        self._last_input_snapshot: RuntimeInputSnapshot | None = None
        self._deferred_attempts: list[EffectDispatchAttempt] = []
        self._deferred_cancellations: list[CancelRequest] = []
        self._actor_id = "operator"
        self._mission_blackboard = BlackboardSnapshot(ResourceVersion(uuid.uuid4().hex, 0))

    def request_start(self, command: StartRunCommand) -> RunCommandReceipt:
        return self._request(command.idempotency_key, command)

    def request_stop(self, command: StopRunCommand) -> RunCommandReceipt:
        return self._request(command.idempotency_key, command)

    def request_skip(self, command: SkipStepCommand) -> RunCommandReceipt:
        return self._request(command.idempotency_key, command)

    def request_clear_terminal(self, command: ClearTerminalCommand) -> RunCommandReceipt:
        return self._request(command.idempotency_key, command)

    def current(self) -> RunSnapshot | None:
        with self._lock:
            return None if self._run is None else self._run.snapshot

    def effect_status_queries(self):
        with self._lock:
            return self._delivery.status_queries()

    def apply_effect_observations(self, observations) -> None:
        with self._lock:
            for observation in observations:
                self._delivery.apply_observation(observation)

    def advance(self, snapshot: RuntimeInputSnapshot, correlation: CycleCorrelation, now: CoreTime) -> CoreAdvancePlan:
        with self._lock:
            self._last_input_snapshot = snapshot
            cancellations, self._deferred_cancellations = self._deferred_cancellations, []
            attempts, self._deferred_attempts = self._deferred_attempts, []
            attempts.extend(self._delivery.due_retries(now, snapshot.ref))
            feedback = self._delivery.feedback(now)
            previous_token = None if self._run is None else self._run.snapshot.token
            self._drain_intents(snapshot, correlation, now, cancellations, attempts)
            newly_started = self._run is not None and self._run.snapshot.token != previous_token
            if (self._pending_retry is not None and self._mission is not None
                    and now.monotonic_ns >= self._pending_retry[1]):
                token, _deadline = self._pending_retry
                self._pending_retry = None
                retry_intents = self._mission.retry_delay_elapsed(
                    MissionReduceContext(str(correlation.cycle_id), snapshot.ref), token,
                )
                self._process_mission_intents(
                    retry_intents, snapshot, correlation, now, attempts, cancellations,
                )
            if (self._run is not None and self._run.snapshot.state is RunState.RUNNING
                    and self._lease is not None and not self._pending_cancel
                    and self._execution_context_changed(snapshot)):
                cancellations.extend(self._begin_stop(
                    snapshot, correlation, now, "execution_context_changed",
                ))
            if (self._run is not None and self._run.snapshot.state is RunState.RUNNING
                    and not self._pending_cancel and not newly_started):
                attempts.extend(self._advance_active(snapshot, correlation, now, cancellations, feedback))
            if self._run is not None and not self._run.snapshot.state.terminal:
                self._run.project(
                    now,
                    input_ref=snapshot.ref,
                    tick_sequence=correlation.tick_sequence,
                )
            return CoreAdvancePlan(
                correlation,
                None if self._run is None else self._run.snapshot.token,
                tuple(attempts),
                tuple(cancellations),
                None if self._run is None else self._run.snapshot,
            )

    def commit(
        self,
        plan: CoreAdvancePlan,
        dispatch_receipts: tuple[DispatchReceipt, ...],
        cancellation_receipts: tuple[CancellationReceipt, ...],
        now: CoreTime,
    ) -> RunSnapshot | None:
        with self._lock:
            for attempt, receipt in zip(plan.dispatch_attempts, dispatch_receipts, strict=False):
                self._delivery.record(attempt, receipt)
            if self._pending_cancel and cancellation_receipts and self._run is not None:
                receipt = cancellation_receipts[-1]
                if receipt.barrier_disposition.value == "STOP_UNDELIVERABLE":
                    self._run.transition(RunState.FAILED, now, reason_code="stop_undeliverable")
                else:
                    outcome = self._pending_terminal_state or RunState.CANCELLED
                    reason = self._run.snapshot.reason_code
                    self._run.transition(outcome, now, reason_code=reason or outcome.value)
                self._pending_cancel = False
                self._pending_terminal_state = None
                self._delivery.clear()
            elif self._pending_mission_barrier is not None and cancellation_receipts and self._mission is not None:
                receipt = cancellation_receipts[-1]
                context = MissionReduceContext(str(plan.correlation.cycle_id), plan.correlation.input_ref)
                intents = self._mission.barrier_completed(
                    context,
                    self._pending_mission_barrier,
                    succeeded=receipt.barrier_disposition.value != "STOP_UNDELIVERABLE",
                )
                self._pending_mission_barrier = None
                if self._last_input_snapshot is not None:
                    self._process_mission_intents(
                        intents, self._last_input_snapshot, plan.correlation, now,
                        self._deferred_attempts, self._deferred_cancellations,
                    )
            return None if self._run is None else self._run.snapshot

    def _request(self, key: IdempotencyKey, command: object) -> RunCommandReceipt:
        with self._lock:
            previous = self._receipts.get(key)
            if previous is not None:
                payload, receipt = previous
                if payload != command:
                    return RunCommandReceipt(
                        command.request_id, RunCommandDisposition.CONFLICT, False,
                        receipt.run_id, receipt.resource_version, "idempotency_key_reused",
                    )
                return RunCommandReceipt(
                    receipt.request_id, receipt.disposition, True, receipt.run_id,
                    receipt.resource_version, receipt.reason_code,
                )
            current = None if self._run is None else self._run.snapshot
            if isinstance(command, StartRunCommand) and current is not None and not current.state.terminal:
                receipt = RunCommandReceipt(command.request_id, RunCommandDisposition.CONFLICT, False,
                                            current.token.run_id, current.version, "active_run_conflict")
            else:
                self._intents.append(command)
                receipt = RunCommandReceipt(
                    command.request_id, RunCommandDisposition.ACCEPTED, False,
                    None if current is None else current.token.run_id,
                    None if current is None else current.version,
                    None,
                )
            self._receipts[key] = (command, receipt)
            return receipt

    def _drain_intents(self, snapshot, correlation, now, cancellations, attempts) -> None:
        intents, self._intents = self._intents, []
        # Stop dominates all other commands admitted in the same cycle.
        intents.sort(key=lambda item: 0 if isinstance(item, StopRunCommand) else 1)
        for command in intents:
            if isinstance(command, StopRunCommand):
                if self._run is not None and command.run_token == self._run.snapshot.token and not self._run.snapshot.state.terminal:
                    cancellations.extend(self._begin_stop(snapshot, correlation, now, command.reason_code))
            elif isinstance(command, ClearTerminalCommand):
                if self._run is not None and self._run.snapshot.state.terminal and command.run_token == self._run.snapshot.token:
                    self._run = None
                    self._target = None
                    self._mission = None
                    self._pending_retry = None
                    self._runner.clear_terminal()
            elif isinstance(command, SkipStepCommand):
                if self._mission is not None:
                    context = MissionReduceContext(str(correlation.cycle_id), snapshot.ref)
                    self._process_mission_intents(self._mission.skip(context, command.expected_step), snapshot,
                                                  correlation, now, attempts, cancellations)
            elif isinstance(command, StartRunCommand):
                if self._run is None or self._run.snapshot.state.terminal:
                    attempts.extend(self._start(command, snapshot, correlation, now, cancellations))

    def _start(self, command, snapshot, correlation, now, cancellations) -> list[EffectDispatchAttempt]:
        token = RunToken(RunId(uuid.uuid4().hex), RunResourceGenerationId(uuid.uuid4().hex))
        self._run = RunAggregate(token, command.target_source, now)
        self._target = command.target
        self._actor_id = command.authorization_request.actor_id
        self._run.transition(RunState.VALIDATING, now)
        if command.target_source not in {"real", "sitl"}:
            self._run.transition(RunState.FAILED, now, reason_code="invalid_target_source")
            return []
        if not command.authorization_request.operator_confirmed:
            self._run.transition(RunState.FAILED, now, reason_code="operator_confirmation_required")
            return []
        self._run.transition(RunState.STARTING, now)
        if isinstance(command.target, ActionRunTarget):
            registration = self._registrations.resolve(command.target.action_contract_ref)
            if registration is None:
                self._run.transition(RunState.FAILED, now, reason_code="action_contract_not_found")
                return []
            preflight_reason = self._registration_preflight_reason(
                registration, snapshot, command.target_source,
            )
            if preflight_reason is not None:
                self._run.transition(RunState.FAILED, now, reason_code=preflight_reason)
                return []
            action_id = ActionInstanceId(uuid.uuid4().hex)
            self._issue_authority(token.run_id, action_id, registration, snapshot, now)
            context = ActionTickContext(correlation, now, snapshot)
            action_snapshot, emissions = self._runner.start(
                action_id, registration, command.target.encoded_parameters, context,
            )
            if action_snapshot.state is ActionState.FAILED:
                self._run.transition(RunState.RUNNING, now, action=action_snapshot)
                cancellations.extend(self._begin_terminal_cleanup(
                    snapshot, correlation, now, RunState.FAILED,
                    action_snapshot.reason_code or "action_start_failed",
                ))
                return []
            if action_snapshot.state is ActionState.SUCCEEDED:
                self._run.transition(RunState.RUNNING, now, action=action_snapshot)
                cancellations.extend(self._begin_terminal_cleanup(
                    snapshot, correlation, now, RunState.SUCCEEDED, "action_succeeded",
                ))
                return []
            self._run.transition(RunState.RUNNING, now, action=action_snapshot)
            return self._attempts(emissions, snapshot, now)
        self._mission = MissionOrchestrator(token.run_id, command.target.definition)
        raw_inputs = thaw_json(command.target.inputs)
        self._mission_blackboard = BlackboardSnapshot(ResourceVersion(uuid.uuid4().hex, 0))
        if isinstance(raw_inputs, dict):
            for key, value in sorted(raw_inputs.items()):
                self._mission_blackboard = self._mission_blackboard.put(
                    key,
                    BlackboardEntry(freeze_json(value), "run_input", "run_input", "run.input.v1", now),
                )
        self._run.transition(RunState.RUNNING, now, mission=self._mission.snapshot)
        context = MissionReduceContext(str(correlation.cycle_id), snapshot.ref)
        intents = self._mission.start(context, command.target.inputs)
        output: list[EffectDispatchAttempt] = []
        self._process_mission_intents(intents, snapshot, correlation, now, output, cancellations)
        return output

    def _advance_active(self, snapshot, correlation, now, cancellations, feedback) -> list[EffectDispatchAttempt]:
        action = self._runner.snapshot
        if action is None or action.state is not ActionState.RUNNING:
            return []
        action_snapshot, emissions = self._runner.step(ActionTickContext(correlation, now, snapshot, feedback))
        self._run.project(now, action=action_snapshot,
                          mission=None if self._mission is None else self._mission.snapshot)
        if action_snapshot.state is ActionState.RUNNING:
            return self._attempts(emissions, snapshot, now)
        if self._mission is not None:
            context = MissionReduceContext(str(correlation.cycle_id), snapshot.ref)
            current_token = self._mission.snapshot.current_step_token
            if current_token is not None and action_snapshot.output is not None:
                for step in self._mission.definition.steps:
                    if step.step_id == current_token.step_id and step.save_as:
                        self._mission_blackboard = self._mission_blackboard.put(
                            step.save_as,
                            BlackboardEntry(
                                action_snapshot.output.payload,
                                str(step.step_id),
                                str(action_snapshot.contract_ref.fingerprint),
                                action_snapshot.output.output_schema.schema_id,
                                now,
                            ),
                        )
                        break
            intents = self._mission.child_terminal(
                context, action_snapshot.instance_id,
                succeeded=action_snapshot.state is ActionState.SUCCEEDED,
                output=action_snapshot.output,
                reason_code=action_snapshot.reason_code,
            )
            output: list[EffectDispatchAttempt] = []
            self._process_mission_intents(intents, snapshot, correlation, now, output, cancellations)
            self._run.project(now, action=action_snapshot, mission=self._mission.snapshot)
            return output
        if action_snapshot.state is ActionState.SUCCEEDED:
            cancellations.extend(self._begin_terminal_cleanup(
                snapshot, correlation, now, RunState.SUCCEEDED, "action_succeeded",
            ))
        else:
            cancellations.extend(self._begin_terminal_cleanup(
                snapshot, correlation, now, RunState.FAILED,
                action_snapshot.reason_code or "action_failed",
            ))
        return []

    def _process_mission_intents(self, intents, snapshot, correlation, now, attempts, cancellations) -> None:
        context = MissionReduceContext(str(correlation.cycle_id), snapshot.ref)
        for intent in intents:
            if isinstance(intent, StartChildAction):
                registration = self._registrations.resolve(intent.step.action_contract_ref)
                if registration is None:
                    self._run.transition(RunState.FAILED, now, reason_code="child_contract_not_found")
                    continue
                preflight_reason = self._registration_preflight_reason(
                    registration, snapshot, self._run.snapshot.target_source,
                )
                if preflight_reason is not None:
                    self._run.transition(RunState.FAILED, now, reason_code=preflight_reason)
                    continue
                self._runner.clear_terminal()
                action_id = ActionInstanceId(uuid.uuid4().hex)
                self._issue_authority(self._run.snapshot.token.run_id, action_id, registration, snapshot, now)
                action_snapshot, emissions = self._runner.start(
                    action_id, registration,
                    resolve_compiled_parameters(intent.resolved_parameters, self._mission_blackboard),
                    ActionTickContext(correlation, now, snapshot),
                )
                self._mission.child_started(context, intent.step_token, action_id)
                attempts.extend(self._attempts(emissions, snapshot, now))
                self._run.project(now, action=action_snapshot, mission=self._mission.snapshot)
                if action_snapshot.state is not ActionState.RUNNING:
                    terminal_intents = self._mission.child_terminal(
                        context,
                        action_id,
                        succeeded=action_snapshot.state is ActionState.SUCCEEDED,
                        output=action_snapshot.output,
                        reason_code=action_snapshot.reason_code,
                    )
                    self._process_mission_intents(
                        terminal_intents, snapshot, correlation, now, attempts, cancellations,
                    )
            elif isinstance(intent, RequestExitBarrier):
                self._pending_mission_barrier = intent.step_token
                cancellations.extend(self._begin_stop(snapshot, correlation, now, "mission_exit_barrier",
                                                       terminalize_run=False,
                                                       emit_stop_barrier=intent.barrier is not ExitBarrier.NONE))
            elif isinstance(intent, ScheduleRetryDelay):
                self._pending_retry = (
                    intent.step_token,
                    now.monotonic_ns + intent.delay_ms * 1_000_000,
                )
            elif isinstance(intent, CompleteMission):
                self._run.project(now, mission=self._mission.snapshot)
                outcome = RunState.SUCCEEDED if intent.succeeded else RunState.FAILED
                cancellations.extend(self._begin_terminal_cleanup(
                    snapshot, correlation, now, outcome, intent.reason_code,
                ))

    def _issue_authority(self, run_id, action_id, registration, snapshot, now) -> None:
        lease_id = LeaseId(uuid.uuid4().hex)
        fence = self._fence.activate(run_id, action_id, lease_id, now.monotonic_ns)
        expires = now.monotonic_ns + 60_000_000_000
        kinds = registration.definition.allowed_effect_kinds
        self._grant = RunAuthorizationGrant(
            self._actor_id, run_id, self._run.snapshot.target_source,
            AuthorizationGeneration(fence.authorization_generation), kinds, expires, "v1",
        )
        self._lease = ExecutionLease(
            lease_id, LeaseGeneration(fence.lease_generation), run_id,
            fence.run_execution_generation, action_id, registration.definition.contract_ref,
            self._run.snapshot.target_source, LinkSessionId(fence.link_session_id),
            AuthorizationGeneration(fence.authorization_generation), kinds, expires,
        )
        self._lease_send_generation = fence.send_generation

    def _attempts(self, emissions: tuple[EffectEmission, ...], snapshot, now) -> list[EffectDispatchAttempt]:
        if self._grant is None or self._lease is None:
            return []
        output = []
        for emission in emissions:
            self._emission_sequence += 1
            effect_id = EffectId(uuid.uuid4().hex)
            envelope = EffectEnvelope(
                effect_id, IdempotencyKey(str(effect_id)), self._run.snapshot.token.run_id,
                self._lease.run_execution_generation, self._lease.action_instance_id,
                self._emission_sequence, emission.local_token, emission.effect, snapshot.ref,
            )
            output.append(EffectDispatchAttempt(
                envelope, 1, snapshot.ref, self._lease, self._grant,
                snapshot.send_gate.generation, now,
            ))
        return output

    def _begin_stop(self, snapshot, correlation, now, reason, *, terminalize_run=True,
                    emit_stop_barrier=True) -> list[CancelRequest]:
        if self._run is None or self._pending_cancel:
            return []
        if terminalize_run:
            self._run.transition(RunState.STOPPING, now, reason_code=reason)
            self._pending_retry = None
        self._runner.stop(ActionTickContext(correlation, now, snapshot), reason)
        target, current = self._fence.revoke(now.monotonic_ns)
        request = CancelRequest(
            schema=SchemaVersion(2, 0),
            cancellation_id=uuid.uuid4().hex,
            scope=CancelScope.RUN,
            run_id=str(self._run.snapshot.token.run_id),
            source=target.source,
            expected_link_session_id=str(target.link_session_id),
            expected_authorization_generation=None if target.authorization_generation is None else int(target.authorization_generation),
            expected_send_generation=int(target.send_generation),
            emit_stop_barrier=emit_stop_barrier,
            reason_code=reason,
            deadline_monotonic_ns=now.monotonic_ns + 1_000_000_000,
            created_at_monotonic_ns=now.monotonic_ns,
            target_run_execution_generation=None if target.run_execution_generation is None else int(target.run_execution_generation),
            target_lease_generation=None if target.lease_generation is None else int(target.lease_generation),
            cancellation_generation=int(current.cancellation_generation),
        )
        if terminalize_run:
            self._pending_cancel = True
            self._pending_terminal_state = RunState.CANCELLED
        return [request]

    def _begin_terminal_cleanup(self, snapshot, correlation, now, outcome, reason):
        if self._run is None or self._pending_cancel:
            return []
        self._run.transition(RunState.FINALIZING, now, reason_code=reason)
        if self._fence.snapshot().run_id is None:
            self._run.transition(outcome, now, reason_code=reason)
            self._delivery.clear()
            return []
        requests = self._begin_stop(
            snapshot, correlation, now, reason, terminalize_run=False,
        )
        self._pending_cancel = True
        self._pending_terminal_state = outcome
        return requests

    def _execution_context_changed(self, snapshot) -> bool:
        if self._lease is None:
            return False
        vehicle = snapshot.vehicle
        if vehicle is not None:
            if vehicle.source != self._lease.source:
                return True
            if vehicle.link_session_id != self._lease.link_session_id:
                return True
        return snapshot.send_gate.generation != self._lease_send_generation

    @staticmethod
    def _registration_preflight_reason(registration, snapshot, target_source):
        kinds = registration.definition.allowed_effect_kinds
        vehicle_effect = any(kind is not EffectKind.SET_VISION_TARGET for kind in kinds)
        if vehicle_effect and not snapshot.send_gate.enabled:
            return "send_disabled"
        vehicle = snapshot.vehicle
        if vehicle_effect and (
            vehicle is None or vehicle.source != target_source
            or not vehicle.connected or vehicle.stale or not vehicle.control_allowed
        ):
            return "vehicle_source_unavailable"
        if EffectKind.SET_VISION_TARGET in kinds and snapshot.perception is None:
            return "perception_unavailable"
        return None
