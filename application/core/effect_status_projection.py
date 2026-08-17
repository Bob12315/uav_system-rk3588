from __future__ import annotations

from typing import Protocol

from contracts.core.action import (
    EffectAckFeedbackState,
    EffectAdmissionFeedbackState,
    EffectCompletionFeedbackState,
    EffectLifecycleFeedback,
    EffectTransportFeedbackState,
)
from contracts.core.effects import EffectKind
from contracts.core.time import CoreTime
from contracts.platform.common import ResourceVersion
from contracts.platform.perception import VisionResultState
from contracts.platform.vehicle_commands import (
    AckState,
    CompletionState,
    SubmissionState,
    TransportState,
)
from execution.effect_registry import EFFECT_REGISTRY, EffectRoute

from .effect_delivery import EffectStatusObservation, EffectStatusQuery


class EffectStatusProjectionPort(Protocol):
    def observe(
        self, queries: tuple[EffectStatusQuery, ...], now: CoreTime
    ) -> tuple[EffectStatusObservation, ...]: ...


class PlatformEffectStatusProjection(EffectStatusProjectionPort):
    """Stateless route DTO normalizer.  It owns no retry or Action state."""

    def __init__(self, vehicle_status: object, vision_status: object) -> None:
        self._vehicle_status = vehicle_status
        self._vision_status = vision_status

    def observe(self, queries, now):
        observations = []
        for query in queries:
            try:
                route = EFFECT_REGISTRY[query.effect_kind].route
                observation = (
                    self._vehicle(query, now)
                    if route is EffectRoute.VEHICLE
                    else self._vision(query, now)
                )
            except Exception:
                continue
            if query.last_seen_revision is None or observation.resource_revision > query.last_seen_revision:
                observations.append(observation)
        return tuple(observations)

    def _vehicle(self, query: EffectStatusQuery, now: CoreTime) -> EffectStatusObservation:
        status = self._vehicle_status.status(query.platform_command_id)
        admission = (
            EffectAdmissionFeedbackState.ACCEPTED
            if status.submission_state is SubmissionState.ACCEPTED
            else EffectAdmissionFeedbackState.REJECTED
        )
        transport = {
            TransportState.NOT_ATTEMPTED: EffectTransportFeedbackState.NOT_ATTEMPTED,
            TransportState.TRANSMITTED: EffectTransportFeedbackState.TRANSMITTED,
            TransportState.WRITE_FAILED: EffectTransportFeedbackState.FAILED,
        }[status.transport_state]
        ack = {
            AckState.WAITING: EffectAckFeedbackState.WAITING,
            AckState.IN_PROGRESS: EffectAckFeedbackState.WAITING,
            AckState.ACKED: EffectAckFeedbackState.ACKNOWLEDGED,
            AckState.NACKED: EffectAckFeedbackState.REJECTED,
            AckState.NOT_EXPECTED: EffectAckFeedbackState.NOT_EXPECTED,
            AckState.TIMED_OUT: EffectAckFeedbackState.REJECTED,
            AckState.SESSION_LOST: EffectAckFeedbackState.REJECTED,
        }[status.ack_state]
        completion = {
            CompletionState.NOT_OBSERVED: EffectCompletionFeedbackState.NOT_OBSERVED,
            CompletionState.OBSERVED: EffectCompletionFeedbackState.COMPLETED,
            CompletionState.GOAL_TIMEOUT: EffectCompletionFeedbackState.FAILED,
            CompletionState.SESSION_LOST: EffectCompletionFeedbackState.FAILED,
        }[status.completion_state]
        version = status.resource_version or ResourceVersion("vehicle-command-status", status.revision)
        revision = {
            VisionResultState.ACCEPTED: 1,
            VisionResultState.IN_PROGRESS: 2,
            VisionResultState.APPLIED: 3,
            VisionResultState.REJECTED: 3,
            VisionResultState.EXPIRED: 3,
        }[status.state]
        lifecycle = EffectLifecycleFeedback(
            admission, transport, ack, completion, status.ack_progress, version, now,
        )
        return EffectStatusObservation(query.effect_id, lifecycle, status.revision, status.reason_code)

    def _vision(self, query: EffectStatusQuery, now: CoreTime) -> EffectStatusObservation:
        status = self._vision_status.status(query.platform_command_id)
        failed = status.state in {VisionResultState.REJECTED, VisionResultState.EXPIRED}
        completed = status.state is VisionResultState.APPLIED
        lifecycle = EffectLifecycleFeedback(
            EffectAdmissionFeedbackState.REJECTED if failed else EffectAdmissionFeedbackState.ACCEPTED,
            EffectTransportFeedbackState.NOT_APPLICABLE,
            (EffectAckFeedbackState.REJECTED if failed else
             EffectAckFeedbackState.ACKNOWLEDGED if completed else EffectAckFeedbackState.WAITING),
            (EffectCompletionFeedbackState.FAILED if failed else
             EffectCompletionFeedbackState.COMPLETED if completed else EffectCompletionFeedbackState.PENDING),
            None,
            ResourceVersion("vision-command-status", revision),
            now,
        )
        return EffectStatusObservation(query.effect_id, lifecycle, revision, status.reason_code)
