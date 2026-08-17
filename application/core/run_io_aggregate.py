from __future__ import annotations

from dataclasses import replace
import uuid

from contracts.core.common import IdempotencyKey, OperationId
from contracts.core.run_io import (
    ResultProjectionPolicy,
    RunIoKind,
    RunIoObservation,
    RunIoRequest,
    RunIoSnapshot,
    RunIoState,
    RunIoSubmissionReceipt,
    RunRecordingPolicy,
)
from contracts.platform.common import RunId


_TERMINAL = {RunIoState.RELEASED, RunIoState.PERSISTED, RunIoState.FAILED, RunIoState.TIMED_OUT}


class RunIoAggregate:
    """Pure run-level recording/result state machine; it never calls a Port."""

    def __init__(self, recording: RunRecordingPolicy, result: ResultProjectionPolicy) -> None:
        self.snapshot = RunIoSnapshot(recording, result, None, None, None, None, None, None)

    def plan_start(self, run_id: RunId, generation: int, deadline_ns: int) -> tuple[RunIoRequest, ...]:
        if not self.snapshot.recording_policy.enabled or self.snapshot.recording_operation_id is not None:
            return ()
        request = self._request(RunIoKind.ACQUIRE_RECORDING, run_id, generation, deadline_ns)
        self.snapshot = replace(
            self.snapshot,
            recording_state=RunIoState.PENDING,
            recording_operation_id=request.operation_id,
        )
        return (request,)

    def plan_success(self, run_id: RunId, generation: int, deadline_ns: int) -> tuple[RunIoRequest, ...]:
        if not self.snapshot.result_policy.enabled or self.snapshot.result_operation_id is not None:
            return ()
        request = self._request(RunIoKind.PROJECT_RESULT, run_id, generation, deadline_ns)
        self.snapshot = replace(
            self.snapshot,
            result_state=RunIoState.PENDING,
            result_operation_id=request.operation_id,
        )
        return (request,)

    def plan_release(self, run_id: RunId, generation: int, deadline_ns: int) -> tuple[RunIoRequest, ...]:
        if self.snapshot.recording_state is not RunIoState.ACTIVE or self.snapshot.release_operation_id is not None:
            return ()
        request = self._request(RunIoKind.RELEASE_RECORDING, run_id, generation, deadline_ns)
        self.snapshot = replace(
            self.snapshot,
            release_state=RunIoState.PENDING,
            release_operation_id=request.operation_id,
        )
        return (request,)

    def submitted(self, receipt: RunIoSubmissionReceipt) -> RunIoSnapshot:
        field = self._field_for(receipt.operation_id)
        if field is None:
            return self.snapshot
        state = RunIoState.ACCEPTED if receipt.accepted else RunIoState.FAILED
        self.snapshot = replace(self.snapshot, **{field: state})
        return self.snapshot

    def observed(self, observation: RunIoObservation) -> RunIoSnapshot:
        field = self._field_for(observation.operation_id)
        if field is None:
            return self.snapshot
        current = {
            "recording_state": self.snapshot.recording_state,
            "result_state": self.snapshot.result_state,
            "release_state": self.snapshot.release_state,
        }[field]
        if current in _TERMINAL:
            return self.snapshot
        self.snapshot = replace(self.snapshot, **{field: observation.state})
        return self.snapshot

    @property
    def start_ready(self) -> bool:
        policy = self.snapshot.recording_policy
        return not policy.required or self.snapshot.recording_state is RunIoState.ACTIVE

    @property
    def required_start_failed(self) -> bool:
        return self.snapshot.recording_policy.required and self.snapshot.recording_state in {
            RunIoState.FAILED, RunIoState.TIMED_OUT, RunIoState.RELEASED,
        }

    @property
    def success_ready(self) -> bool:
        policy = self.snapshot.result_policy
        return not policy.required or self.snapshot.result_state is RunIoState.PERSISTED

    @property
    def required_result_failed(self) -> bool:
        return self.snapshot.result_policy.required and self.snapshot.result_state in {
            RunIoState.FAILED, RunIoState.TIMED_OUT,
        }

    @property
    def release_done(self) -> bool:
        if self.snapshot.recording_state is not RunIoState.ACTIVE:
            return True
        return self.snapshot.release_state in _TERMINAL

    def _field_for(self, operation_id: OperationId) -> str | None:
        if operation_id == self.snapshot.recording_operation_id:
            return "recording_state"
        if operation_id == self.snapshot.result_operation_id:
            return "result_state"
        if operation_id == self.snapshot.release_operation_id:
            return "release_state"
        return None

    @staticmethod
    def _request(kind: RunIoKind, run_id: RunId, generation: int, deadline_ns: int) -> RunIoRequest:
        operation_id = OperationId(uuid.uuid4().hex)
        return RunIoRequest(
            operation_id,
            kind,
            run_id,
            generation,
            IdempotencyKey(f"{run_id}:{generation}:{kind.value}"),
            deadline_ns,
        )


class DetachedRunIoTracker:
    """Bounded owner for optional terminal result operations and cleanup observations."""

    def __init__(self, capacity: int = 128) -> None:
        if capacity < 1:
            raise ValueError("detached tracker capacity must be positive")
        self._capacity = capacity
        self._operations: dict[OperationId, int] = {}

    def attach(self, operation_id: OperationId, deadline_ns: int) -> None:
        if len(self._operations) >= self._capacity and operation_id not in self._operations:
            raise OverflowError("detached run I/O tracker is full")
        self._operations[operation_id] = deadline_ns

    def pending(self, now_ns: int) -> tuple[OperationId, ...]:
        expired = [operation for operation, deadline in self._operations.items() if deadline <= now_ns]
        for operation in expired:
            del self._operations[operation]
        return tuple(self._operations)

    def complete(self, observation: RunIoObservation) -> None:
        if observation.state in _TERMINAL:
            self._operations.pop(observation.operation_id, None)
