from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
import uuid
from typing import Literal, TypeAlias

from .common import ResourceVersion, SchemaVersion, SourceId
from .field import ReferenceVersion


class AckPolicy(str, Enum):
    DISABLED = "DISABLED"
    RECORD_ONLY = "RECORD_ONLY"
    REQUIRED = "REQUIRED"


class CompletionPolicy(str, Enum):
    TRANSPORT_ONLY = "TRANSPORT_ONLY"
    STATE_OBSERVED = "STATE_OBSERVED"


class SubmissionState(str, Enum):
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


class QueueState(str, Enum):
    NOT_QUEUED = "NOT_QUEUED"
    QUEUED = "QUEUED"
    DEQUEUED = "DEQUEUED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class TransportState(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    TRANSMITTED = "TRANSMITTED"
    WRITE_FAILED = "WRITE_FAILED"


class AckState(str, Enum):
    NOT_EXPECTED = "NOT_EXPECTED"
    WAITING = "WAITING"
    IN_PROGRESS = "IN_PROGRESS"
    ACKED = "ACKED"
    NACKED = "NACKED"
    TIMED_OUT = "TIMED_OUT"
    SESSION_LOST = "SESSION_LOST"


class CompletionState(str, Enum):
    NOT_OBSERVED = "NOT_OBSERVED"
    OBSERVED = "OBSERVED"
    GOAL_TIMEOUT = "GOAL_TIMEOUT"
    SESSION_LOST = "SESSION_LOST"


@dataclass(frozen=True, slots=True)
class SetMode:
    mode: str
    kind: Literal["set_mode"] = "set_mode"


@dataclass(frozen=True, slots=True)
class Arm:
    arm: bool = True
    kind: Literal["arm"] = "arm"


@dataclass(frozen=True, slots=True)
class Takeoff:
    altitude_m: float
    kind: Literal["takeoff"] = "takeoff"


@dataclass(frozen=True, slots=True)
class Land:
    kind: Literal["land"] = "land"


@dataclass(frozen=True, slots=True)
class LocalPositionTarget:
    north_m: float
    east_m: float
    down_m: float
    yaw_rad: float | None = None
    kind: Literal["local_position"] = "local_position"


@dataclass(frozen=True, slots=True)
class GlobalPositionTarget:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    kind: Literal["global_position"] = "global_position"


@dataclass(frozen=True, slots=True)
class BodyVelocity:
    forward_mps: float
    right_mps: float
    down_mps: float
    yaw_rate_rad_s: float | None = None
    yaw_rad: float | None = None
    kind: Literal["body_velocity"] = "body_velocity"

    def __post_init__(self) -> None:
        if self.yaw_rad is not None and self.yaw_rate_rad_s is not None:
            raise ValueError("body velocity cannot set yaw and yaw rate together")


@dataclass(frozen=True, slots=True)
class ConditionYaw:
    yaw_deg: float
    relative: bool = False
    kind: Literal["condition_yaw"] = "condition_yaw"


@dataclass(frozen=True, slots=True)
class ChangeSpeed:
    speed_mps: float
    kind: Literal["change_speed"] = "change_speed"


@dataclass(frozen=True, slots=True)
class SetServo:
    channel: int
    pwm: int
    kind: Literal["set_servo"] = "set_servo"


@dataclass(frozen=True, slots=True)
class GimbalAngle:
    yaw_rad: float
    pitch_rad: float
    kind: Literal["gimbal_angle"] = "gimbal_angle"


@dataclass(frozen=True, slots=True)
class GimbalRate:
    yaw_rate_rad_s: float
    pitch_rate_rad_s: float
    kind: Literal["gimbal_rate"] = "gimbal_rate"


@dataclass(frozen=True, slots=True)
class StopMotion:
    kind: Literal["stop_motion"] = "stop_motion"


VehicleCommand: TypeAlias = (
    SetMode | Arm | Takeoff | Land | LocalPositionTarget | GlobalPositionTarget |
    BodyVelocity | ConditionYaw | ChangeSpeed | SetServo | GimbalAngle | GimbalRate | StopMotion
)


@dataclass(frozen=True, slots=True)
class VehicleCommandEnvelope:
    schema: SchemaVersion
    command_id: str
    run_id: str
    execution_lease_id: str
    authorization_generation: int
    send_generation: int
    source: SourceId
    expected_link_session_id: str
    created_at_monotonic_ns: int
    deadline_monotonic_ns: int
    priority: int
    idempotency_key: str
    ack_policy: AckPolicy
    completion_policy: CompletionPolicy
    ack_timeout_ms: int
    payload: VehicleCommand
    field_reference_version: ReferenceVersion | None = None
    run_execution_generation: int = 0
    lease_generation: int = 0

    def __post_init__(self) -> None:
        if not all((self.command_id, self.run_id, self.execution_lease_id,
                    self.expected_link_session_id, self.idempotency_key)):
            raise ValueError("command identity fields must not be empty")
        if self.deadline_monotonic_ns <= self.created_at_monotonic_ns:
            raise ValueError("command deadline must follow creation")
        if min(self.run_execution_generation, self.authorization_generation,
               self.lease_generation, self.send_generation, self.ack_timeout_ms) < 0:
            raise ValueError("generation and timeout values must be non-negative")
        if isinstance(self.payload, SetServo) and not 1 <= self.payload.channel <= 16:
            raise ValueError("servo channel outside allowlisted MAVLink range")


@dataclass(frozen=True, slots=True)
class CommandSubmissionReceipt:
    command_id: str
    submission_state: SubmissionState
    reason_code: str
    receipt_id: str = ""
    replayed: bool = False
    original_receipt_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommandStatusSnapshot:
    command_id: str
    submission_state: SubmissionState
    queue_state: QueueState
    transport_state: TransportState
    ack_state: AckState
    completion_state: CompletionState
    revision: int
    reason_code: str
    transmitted_at_monotonic_ns: int | None = None
    ack_progress: int | None = None
    resource_version: ResourceVersion | None = None


class CancelScope(str, Enum):
    COMMAND = "COMMAND"
    RUN = "RUN"
    EXECUTION_LEASE = "EXECUTION_LEASE"
    SOURCE = "SOURCE"
    CONTINUOUS_STREAM = "CONTINUOUS_STREAM"


@dataclass(frozen=True, slots=True)
class CancelRequest:
    schema: SchemaVersion
    cancellation_id: str
    scope: CancelScope
    command_id: str | None = None
    execution_lease_id: str | None = None
    run_id: str | None = None
    stream_id: str | None = None
    source: SourceId | None = None
    expected_link_session_id: str | None = None
    expected_authorization_generation: int | None = None
    expected_send_generation: int | None = None
    emit_stop_barrier: bool = False
    reason_code: str = "cancelled"
    deadline_monotonic_ns: int = 0
    created_at_monotonic_ns: int = 0
    target_run_execution_generation: int | None = None
    target_lease_generation: int | None = None
    cancellation_generation: int = 0

    def __post_init__(self) -> None:
        identifiers = {
            CancelScope.COMMAND: self.command_id,
            CancelScope.RUN: self.run_id,
            CancelScope.EXECUTION_LEASE: self.execution_lease_id,
            CancelScope.SOURCE: self.source,
            CancelScope.CONTINUOUS_STREAM: self.stream_id,
        }
        required = identifiers[self.scope]
        if not required:
            raise ValueError(f"{self.scope.value} cancel requires its matching identifier")
        if any(
            value is not None
            for scope, value in identifiers.items()
            if scope != self.scope and scope is not CancelScope.SOURCE
        ):
            raise ValueError(f"{self.scope.value} cancel forbids unrelated identifiers")
        if self.schema.major != 2 or not self.cancellation_id:
            raise ValueError("canonical cancel schema and identity are required")
        if self.deadline_monotonic_ns <= self.created_at_monotonic_ns:
            raise ValueError("canonical cancel deadline is required")
        if self.cancellation_generation < 0:
            raise ValueError("cancellation generation must be non-negative")

    @classmethod
    def create(cls, scope: CancelScope, *, reason: str, timeout_ms: int = 1000,
               command_id: str | None = None, run_id: str | None = None,
               execution_lease_id: str | None = None, source: SourceId | None = None,
               stream_id: str | None = None, emit_stop_barrier: bool = False,
               expected_authorization_generation: int | None = None,
               expected_send_generation: int | None = None,
               expected_link_session_id: str | None = None,
               now_ns: int | None = None, cancellation_id: str | None = None) -> "CancelRequest":
        now_ns = time.monotonic_ns() if now_ns is None else now_ns
        return cls(SchemaVersion(2, 0), cancellation_id or uuid.uuid4().hex, scope,
            command_id, execution_lease_id, run_id, stream_id, source,
            expected_link_session_id, expected_authorization_generation,
            expected_send_generation, emit_stop_barrier, reason,
            now_ns + timeout_ms * 1_000_000, now_ns)


class BarrierDisposition(str, Enum):
    TRANSMITTED = "TRANSMITTED"
    STOP_UNDELIVERABLE = "STOP_UNDELIVERABLE"
    NOT_REQUIRED = "NOT_REQUIRED"


@dataclass(frozen=True, slots=True)
class CancellationReceipt:
    schema: SchemaVersion
    cancellation_id: str
    matched_pending_ids: tuple[str, ...]
    already_transmitted_ids: tuple[str, ...]
    not_found_ids: tuple[str, ...]
    barrier_id: str | None
    barrier_disposition: BarrierDisposition
    source: SourceId | None
    link_session_id: str | None
    completed_monotonic_ns: int
    reason_code: str = "cancelled"
    receipt_id: str = ""
    replayed: bool = False

    @property
    def found(self) -> bool:
        return not self.not_found_ids


COMMAND_POLICY: dict[str, tuple[AckPolicy, CompletionPolicy]] = {
    "set_mode": (AckPolicy.DISABLED, CompletionPolicy.STATE_OBSERVED),
    "arm": (AckPolicy.RECORD_ONLY, CompletionPolicy.STATE_OBSERVED),
    "takeoff": (AckPolicy.RECORD_ONLY, CompletionPolicy.STATE_OBSERVED),
    "land": (AckPolicy.RECORD_ONLY, CompletionPolicy.STATE_OBSERVED),
    "local_position": (AckPolicy.DISABLED, CompletionPolicy.STATE_OBSERVED),
    "global_position": (AckPolicy.DISABLED, CompletionPolicy.STATE_OBSERVED),
    "body_velocity": (AckPolicy.DISABLED, CompletionPolicy.TRANSPORT_ONLY),
    "condition_yaw": (AckPolicy.RECORD_ONLY, CompletionPolicy.TRANSPORT_ONLY),
    "change_speed": (AckPolicy.RECORD_ONLY, CompletionPolicy.TRANSPORT_ONLY),
    "set_servo": (AckPolicy.RECORD_ONLY, CompletionPolicy.TRANSPORT_ONLY),
    "gimbal_angle": (AckPolicy.RECORD_ONLY, CompletionPolicy.TRANSPORT_ONLY),
    "gimbal_rate": (AckPolicy.DISABLED, CompletionPolicy.TRANSPORT_ONLY),
    "stop_motion": (AckPolicy.DISABLED, CompletionPolicy.TRANSPORT_ONLY),
}
