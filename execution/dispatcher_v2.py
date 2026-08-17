from __future__ import annotations

import uuid

from contracts.core.common import DispatchReceiptId
from contracts.core.effects import GlobalPositionTarget, LocalPositionTarget, SetVisionTarget
from contracts.core.execution import (
    DispatchReceipt,
    DispatchState,
    EffectDispatchAttempt,
    SafetyContext,
    SafetyDisposition,
)
from contracts.platform.common import ClockStamp, ExecutionFenceQueryPort, SchemaVersion
from contracts.platform.ports import VehicleCommandPort, VisionCommandPort
from contracts.platform.perception import SetTargetLock, VisionCommandEnvelope, VisionResultState
from contracts.platform.vehicle_commands import COMMAND_POLICY, VehicleCommandEnvelope

from .capability_policy import authorize_effect
from .effect_registry import EFFECT_REGISTRY, EffectRoute
from .safety_policy import SafetyPolicy
from .translators import translate_vehicle_effect


class EffectDispatcher:
    """The single typed submit pipeline: gate -> safety -> translate -> Port."""

    def __init__(self, vehicle_commands: VehicleCommandPort, vision_commands: VisionCommandPort,
                 safety: SafetyPolicy, fence_query: ExecutionFenceQueryPort | None = None) -> None:
        self._vehicle_commands = vehicle_commands
        self._vision_commands = vision_commands
        self._safety = safety
        self._fence_query = fence_query

    def dispatch(
        self,
        attempt: EffectDispatchAttempt,
        context: SafetyContext,
        *,
        yolo_process_session_id: str | None = None,
    ) -> DispatchReceipt:
        reason = authorize_effect(attempt)
        if reason is not None:
            return self._receipt(attempt, DispatchState.REJECTED, reason)
        if self._fence_query is not None:
            fence = self._fence_query.snapshot()
            expected = (
                fence.run_id == attempt.envelope.run_id,
                fence.run_execution_generation == attempt.envelope.run_execution_generation,
                fence.action_instance_id == attempt.envelope.action_instance_id,
                fence.execution_lease_id == attempt.lease.lease_id,
                fence.lease_generation == attempt.lease.generation,
                fence.authorization_generation == attempt.grant.generation,
                fence.send_generation == attempt.send_generation,
            )
            if not all(expected):
                return self._receipt(attempt, DispatchState.REJECTED, "execution_fence_stale")
        if attempt.lease.source != context.source or attempt.lease.link_session_id != context.link_session_id:
            return self._receipt(attempt, DispatchState.REJECTED, "source_or_session_mismatch")
        decision = self._safety.evaluate(attempt.envelope.effect, context)
        if decision.disposition is SafetyDisposition.REJECT or decision.effective is None:
            return self._receipt(attempt, DispatchState.REJECTED, decision.reason_code or "safety_rejected")
        rule = EFFECT_REGISTRY[decision.effective.kind]
        try:
            if rule.route is EffectRoute.VEHICLE:
                payload = translate_vehicle_effect(decision.effective)
                ack_policy, completion_policy = COMMAND_POLICY[payload.kind]
                now_ns = attempt.now.monotonic_ns
                command_id = str(attempt.envelope.effect_id)
                reference_version = (
                    decision.effective.reference_version
                    if isinstance(decision.effective, (LocalPositionTarget, GlobalPositionTarget))
                    else None
                )
                envelope = VehicleCommandEnvelope(
                    SchemaVersion(2, 0), command_id, str(attempt.envelope.run_id),
                    str(attempt.lease.lease_id), int(attempt.grant.generation),
                    int(attempt.send_generation), attempt.lease.source,
                    str(attempt.lease.link_session_id), now_ns, now_ns + 1_000_000_000,
                    5, str(attempt.envelope.idempotency_key), ack_policy,
                    completion_policy, 750, payload,
                    reference_version,
                    int(attempt.envelope.run_execution_generation),
                    int(attempt.lease.generation),
                )
                platform_receipt = self._vehicle_commands.submit(envelope)
                if platform_receipt.submission_state.value != "ACCEPTED":
                    return self._receipt(attempt, DispatchState.REJECTED,
                                         platform_receipt.reason_code, command_id)
                return self._receipt(attempt, DispatchState.ACCEPTED, None, command_id,
                                     platform_receipt.replayed)
            if yolo_process_session_id is None:
                return self._receipt(attempt, DispatchState.REJECTED, "vision_session_unavailable")
            effect = decision.effective
            if not isinstance(effect, SetVisionTarget):
                return self._receipt(attempt, DispatchState.REJECTED, "invalid_vision_effect")
            command_id = str(attempt.envelope.effect_id)
            envelope = VisionCommandEnvelope(
                SchemaVersion(2, 0), "uav-app", str(attempt.envelope.run_id),
                yolo_process_session_id, command_id, attempt.envelope.emission_sequence,
                1000, ClockStamp(attempt.now.utc, attempt.now.monotonic_ns, attempt.now.clock_domain_id),
                SetTargetLock(effect.track_id),
            )
            platform_receipt = self._vision_commands.submit(envelope)
            if platform_receipt.result_state is VisionResultState.REJECTED:
                return self._receipt(attempt, DispatchState.REJECTED, platform_receipt.reason_code, command_id)
            return self._receipt(attempt, DispatchState.ACCEPTED, None, command_id, platform_receipt.replayed)
        except Exception:
            return self._receipt(attempt, DispatchState.FAILED_TO_SUBMIT, "platform_submit_failed")

    @staticmethod
    def _receipt(
        attempt: EffectDispatchAttempt,
        state: DispatchState,
        reason: str | None,
        command_id: str | None = None,
        replayed: bool = False,
    ) -> DispatchReceipt:
        return DispatchReceipt(
            DispatchReceiptId(uuid.uuid4().hex), attempt.envelope.effect_id,
            state, replayed, command_id, reason,
        )
