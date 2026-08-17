from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

from contracts.platform.common import ExecutionFenceSnapshot, ResourceVersion, SourceId

from .common import IdempotencyKey, OperationId, RequestId
from .input_state import SendGateSnapshot
from .time import CoreTime


@dataclass(frozen=True, slots=True)
class SetSendGateCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    enabled: bool
    expected_version: ResourceVersion
    reason_code: str
    requested_at: CoreTime


@dataclass(frozen=True, slots=True)
class SwitchSourceCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    source: SourceId
    expected_version: ResourceVersion
    requested_at: CoreTime


@dataclass(frozen=True, slots=True)
class ReconnectSourceCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    source: SourceId | None
    requested_at: CoreTime


@dataclass(frozen=True, slots=True)
class ShutdownCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    deadline_monotonic_ns: int
    requested_at: CoreTime


@dataclass(frozen=True, slots=True)
class BeginMaintenanceCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    deadline_monotonic_ns: int
    requested_at: CoreTime


@dataclass(frozen=True, slots=True)
class EndMaintenanceCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    operation_id: OperationId
    succeeded: bool
    requested_at: CoreTime


SystemControlCommand: TypeAlias = (
    SetSendGateCommand | SwitchSourceCommand | ReconnectSourceCommand |
    ShutdownCommand | BeginMaintenanceCommand | EndMaintenanceCommand
)


class SystemCommandDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFLICT = "conflict"


class SystemOperationState(str, Enum):
    PENDING = "pending"
    QUIESCING = "quiescing"
    READY_FOR_EXTERNAL = "ready_for_external"
    SUBMITTED = "submitted"
    APPLIED = "applied"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class SystemControlReceipt:
    request_id: RequestId
    disposition: SystemCommandDisposition
    replayed: bool
    resource_version: ResourceVersion | None
    operation_id: OperationId | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class SystemOperationSnapshot:
    operation_id: OperationId
    request_id: RequestId
    kind: str
    state: SystemOperationState
    version: ResourceVersion
    requested_at: CoreTime
    updated_at: CoreTime
    finished_at: CoreTime | None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class CoreSystemSnapshot:
    version: ResourceVersion
    send_gate: SendGateSnapshot
    execution_fence: ExecutionFenceSnapshot
    quiescing: bool
    shutdown_requested: bool
    active_operation_id: OperationId | None
    latest_operation: SystemOperationSnapshot | None


class CoreSystemIntentPort(Protocol):
    def request(self, command: SystemControlCommand) -> SystemControlReceipt: ...


class CoreSystemQueryPort(Protocol):
    def current(self) -> CoreSystemSnapshot: ...
    def operation(self, operation_id: OperationId) -> SystemOperationSnapshot | None: ...
