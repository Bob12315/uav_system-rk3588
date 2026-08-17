from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

from contracts.platform.common import RunId

from .common import IdempotencyKey, OperationId
from .time import CoreTime


@dataclass(frozen=True, slots=True)
class RunRecordingPolicy:
    required: bool = False
    enabled: bool = False


@dataclass(frozen=True, slots=True)
class ResultProjectionPolicy:
    required: bool = False
    enabled: bool = True


class RunIoKind(str, Enum):
    ACQUIRE_RECORDING = "acquire_recording"
    RELEASE_RECORDING = "release_recording"
    PROJECT_RESULT = "project_result"


@dataclass(frozen=True, slots=True)
class RunIoRequest:
    operation_id: OperationId
    kind: RunIoKind
    run_id: RunId
    run_generation: int
    idempotency_key: IdempotencyKey
    deadline_monotonic_ns: int


class RunIoState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    ACTIVE = "active"
    RELEASED = "released"
    PERSISTED = "persisted"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class RunIoSubmissionReceipt:
    operation_id: OperationId
    accepted: bool
    replayed: bool
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RunIoObservation:
    operation_id: OperationId
    state: RunIoState
    observed_at: CoreTime
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RunIoSnapshot:
    recording_policy: RunRecordingPolicy
    result_policy: ResultProjectionPolicy
    recording_state: RunIoState | None
    recording_operation_id: OperationId | None
    result_state: RunIoState | None
    result_operation_id: OperationId | None
    release_state: RunIoState | None
    release_operation_id: OperationId | None


class RunIoPort(Protocol):
    def submit(self, request: RunIoRequest) -> RunIoSubmissionReceipt: ...
    def status(self, operation_id: OperationId) -> RunIoObservation: ...
