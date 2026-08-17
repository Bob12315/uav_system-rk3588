from __future__ import annotations

from dataclasses import dataclass

from contracts.core.action import (
    EffectAckFeedbackState,
    EffectAdmissionFeedbackState,
    EffectCompletionFeedbackState,
    EffectFeedback,
    EffectLifecycleFeedback,
    EffectTransportFeedbackState,
)
from contracts.core.common import EffectId
from contracts.core.effects import EffectKind
from contracts.core.effects import BodyVelocityTarget
from contracts.core.execution import DispatchReceipt, DispatchState, EffectDispatchAttempt
from contracts.core.time import CoreTime
from contracts.platform.common import LeaseGeneration, ResourceVersion, RunExecutionGeneration


@dataclass(frozen=True, slots=True)
class EffectStatusQuery:
    effect_id: EffectId
    platform_command_id: str
    effect_kind: EffectKind
    local_token: str
    emission_sequence: int
    run_execution_generation: RunExecutionGeneration
    lease_generation: LeaseGeneration
    last_seen_revision: int | None


@dataclass(frozen=True, slots=True)
class EffectStatusObservation:
    effect_id: EffectId
    lifecycle: EffectLifecycleFeedback
    resource_revision: int
    reason_code: str | None


@dataclass(slots=True)
class _Delivery:
    attempt: EffectDispatchAttempt
    receipt: DispatchReceipt
    next_attempt_ns: int | None = None
    last_seen_revision: int | None = None
    observation: EffectStatusObservation | None = None


class EffectDeliveryTracker:
    """Minimal effect-to-platform-handle owner; accepted effects are never resubmitted."""

    def __init__(self, *, retry_backoff_ns: int = 100_000_000, max_attempts: int = 3) -> None:
        self._deliveries: dict[EffectId, _Delivery] = {}
        self._retry_backoff_ns = retry_backoff_ns
        self._max_attempts = max_attempts

    def record(self, attempt: EffectDispatchAttempt, receipt: DispatchReceipt) -> None:
        delivery = _Delivery(attempt, receipt)
        if (receipt.state is DispatchState.FAILED_TO_SUBMIT
                and not isinstance(attempt.envelope.effect, BodyVelocityTarget)
                and attempt.attempt_number < self._max_attempts):
            delivery.next_attempt_ns = attempt.now.monotonic_ns + self._retry_backoff_ns
        self._deliveries[attempt.envelope.effect_id] = delivery

    def status_queries(self) -> tuple[EffectStatusQuery, ...]:
        return tuple(
            EffectStatusQuery(
                effect_id,
                delivery.receipt.platform_command_id,
                delivery.attempt.envelope.effect.kind,
                delivery.attempt.envelope.local_token,
                delivery.attempt.envelope.emission_sequence,
                delivery.attempt.envelope.run_execution_generation,
                delivery.attempt.lease.generation,
                delivery.last_seen_revision,
            )
            for effect_id, delivery in self._deliveries.items()
            if delivery.receipt.state is DispatchState.ACCEPTED and delivery.receipt.platform_command_id is not None
        )

    def due_retries(self, now: CoreTime, evaluation_input_ref) -> tuple[EffectDispatchAttempt, ...]:
        due: list[EffectDispatchAttempt] = []
        for delivery in self._deliveries.values():
            if delivery.next_attempt_ns is None or delivery.next_attempt_ns > now.monotonic_ns:
                continue
            attempt = delivery.attempt
            due.append(EffectDispatchAttempt(
                attempt.envelope,
                attempt.attempt_number + 1,
                evaluation_input_ref,
                attempt.lease,
                attempt.grant,
                attempt.send_generation,
                now,
            ))
            delivery.next_attempt_ns = None
        return tuple(due)

    def apply_observation(self, observation: EffectStatusObservation) -> None:
        delivery = self._deliveries.get(observation.effect_id)
        if delivery is None:
            return
        if delivery.last_seen_revision is None or observation.resource_revision > delivery.last_seen_revision:
            delivery.last_seen_revision = observation.resource_revision
            delivery.observation = observation

    def feedback(self, now: CoreTime) -> tuple[EffectFeedback, ...]:
        output: list[EffectFeedback] = []
        for delivery in self._deliveries.values():
            attempt = delivery.attempt
            observation = delivery.observation
            if observation is not None:
                lifecycle = observation.lifecycle
                reason = observation.reason_code
            else:
                state = delivery.receipt.state
                admission = {
                    DispatchState.ACCEPTED: EffectAdmissionFeedbackState.ACCEPTED,
                    DispatchState.REJECTED: EffectAdmissionFeedbackState.REJECTED,
                    DispatchState.FAILED_TO_SUBMIT: EffectAdmissionFeedbackState.FAILED_TO_SUBMIT,
                }[state]
                lifecycle = EffectLifecycleFeedback(
                    admission,
                    EffectTransportFeedbackState.NOT_ATTEMPTED,
                    EffectAckFeedbackState.UNKNOWN,
                    EffectCompletionFeedbackState.NOT_OBSERVED,
                    None,
                    None,
                    now,
                )
                reason = delivery.receipt.reason_code
            output.append(EffectFeedback(
                attempt.envelope.effect_id,
                attempt.envelope.local_token,
                attempt.envelope.emission_sequence,
                lifecycle,
                reason,
            ))
        return tuple(output)

    def clear(self) -> None:
        self._deliveries.clear()
