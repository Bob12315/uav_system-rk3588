from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Mapping, NewType, Protocol, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
SourceId: TypeAlias = Literal["real", "sitl", "test"]

# Canonical cross-layer identities.  Adapters transport these values; the
# active run/fence authority is the only component allowed to allocate or
# advance them.
RunId = NewType("RunId", str)
RunResourceGenerationId = NewType("RunResourceGenerationId", str)
ActionInstanceId = NewType("ActionInstanceId", str)
LeaseId = NewType("LeaseId", str)
LinkSessionId = NewType("LinkSessionId", str)
CommandId = NewType("CommandId", str)
CancellationId = NewType("CancellationId", str)
SubmissionReceiptId = NewType("SubmissionReceiptId", str)

RunExecutionGeneration = NewType("RunExecutionGeneration", int)
AuthorizationGeneration = NewType("AuthorizationGeneration", int)
LeaseGeneration = NewType("LeaseGeneration", int)
SendGeneration = NewType("SendGeneration", int)
CancellationGeneration = NewType("CancellationGeneration", int)


@dataclass(frozen=True, slots=True, order=True)
class ResourceVersion:
    generation_id: str
    revision: int

    def __post_init__(self) -> None:
        if not self.generation_id:
            raise ValueError("resource generation_id must not be empty")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("resource revision must be a non-negative integer")

    def next(self) -> "ResourceVersion":
        return ResourceVersion(self.generation_id, self.revision + 1)


@dataclass(frozen=True, slots=True)
class ExecutionFenceSnapshot:
    resource_version: ResourceVersion
    source: SourceId
    link_session_id: LinkSessionId
    run_id: RunId | None
    run_execution_generation: RunExecutionGeneration | None
    authorization_generation: AuthorizationGeneration | None
    action_instance_id: ActionInstanceId | None
    execution_lease_id: LeaseId | None
    lease_generation: LeaseGeneration | None
    send_generation: SendGeneration
    cancellation_generation: CancellationGeneration
    published_at_monotonic_ns: int

    def __post_init__(self) -> None:
        if self.published_at_monotonic_ns < 0:
            raise ValueError("fence publication time must be non-negative")
        active = (
            self.run_id,
            self.run_execution_generation,
            self.authorization_generation,
            self.action_instance_id,
            self.execution_lease_id,
            self.lease_generation,
        )
        if any(value is None for value in active) and any(value is not None for value in active):
            raise ValueError("active execution fence identity must be all-present or all-absent")


class ExecutionFenceQueryPort(Protocol):
    def snapshot(self) -> ExecutionFenceSnapshot: ...


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    major: int
    minor: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.major, bool) or isinstance(self.minor, bool):
            raise TypeError("schema version components must be integers")
        if self.major < 1 or self.minor < 0:
            raise ValueError("schema version must be major >= 1 and minor >= 0")

    def supports(self, other: "SchemaVersion") -> bool:
        return self.major == other.major and self.minor >= other.minor

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"

    @classmethod
    def parse(cls, value: str) -> "SchemaVersion":
        parts = value.split(".")
        if len(parts) != 2:
            raise ValueError("schema version must use MAJOR.MINOR")
        return cls(int(parts[0]), int(parts[1]))


@dataclass(frozen=True, slots=True)
class ClockStamp:
    utc: datetime
    monotonic_ns: int
    clock_domain_id: str

    def __post_init__(self) -> None:
        if self.utc.tzinfo is None or self.utc.utcoffset() is None:
            raise ValueError("utc must be timezone-aware")
        if self.monotonic_ns < 0:
            raise ValueError("monotonic_ns must be non-negative")
        if not self.clock_domain_id:
            raise ValueError("clock_domain_id must not be empty")

    @classmethod
    def now(cls, *, monotonic_ns: int, clock_domain_id: str) -> "ClockStamp":
        return cls(datetime.now(timezone.utc), monotonic_ns, clock_domain_id)


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    correlation_id: str
    actor: str
    source: SourceId
    created_at: ClockStamp
    schema_version: SchemaVersion = SchemaVersion(1, 0)

    def __post_init__(self) -> None:
        for name in ("request_id", "correlation_id", "actor"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")


class ApplicationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, JsonValue] | None = None,
    ) -> None:
        if not code:
            raise ValueError("error code must not be empty")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": to_json_value(self.details),
        }


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    operation_id: str
    accepted: bool
    status: str
    observed_at: ClockStamp
    schema_version: SchemaVersion = SchemaVersion(1, 0)
    detail: Mapping[str, JsonValue] | None = None

    def __post_init__(self) -> None:
        if not self.operation_id or not self.status:
            raise ValueError("operation_id and status must not be empty")
        object.__setattr__(self, "detail", dict(self.detail or {}))


def to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetimes are not serializable platform timestamps")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, SchemaVersion):
        return str(value)
    if is_dataclass(value):
        return {
            field.name: to_json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    raise TypeError(f"not JSON serializable: {type(value).__name__}")
