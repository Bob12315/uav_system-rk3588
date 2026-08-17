from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol

from .common import JsonValue, SchemaVersion


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    schema: SchemaVersion
    event_id: str
    occurred_at_utc: datetime
    occurred_at_monotonic_ns: int
    component: str
    event_type: str
    severity: str
    reason_code: str
    run_id: str | None
    correlation_id: str | None
    source: str
    payload_schema: SchemaVersion
    payload: Mapping[str, JsonValue]


class SinkDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    PERSISTED = "PERSISTED"
    DROPPED = "DROPPED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SinkPublishReceipt:
    sink: str
    disposition: SinkDisposition
    reason_code: str


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    event_id: str
    sinks: tuple[SinkPublishReceipt, ...]


@dataclass(frozen=True, slots=True)
class OperationalEventPage:
    items: tuple[OperationalEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    schema: SchemaVersion
    audit_id: str
    timestamp_utc: datetime
    actor_id: str
    actor_role: str
    source_address: str
    request_id: str | None
    correlation_id: str | None
    operation: str
    resource: str
    decision: str
    reason_code: str
    run_id: str | None
    target_source: str | None
    sanitized_detail: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class AuditAppendReceipt:
    audit_id: str
    disposition: SinkDisposition
    reason_code: str


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: tuple[AuditEntry, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class FrozenJson:
    canonical_json: str
    sha256: str

    @classmethod
    def from_value(cls, value: JsonValue) -> "FrozenJson":
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return cls(encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest())

    def value(self) -> JsonValue:
        return json.loads(self.canonical_json)


@dataclass(frozen=True, slots=True)
class CycleRecordEnvelope:
    schema: SchemaVersion
    recorder_session_id: str
    sequence: int
    sampled_at_utc: datetime
    sampled_at_monotonic_ns: int
    core_cycle_id: str
    correlation_id: str | None
    source_snapshot_ref: str
    run_id: str | None
    payload_schema: SchemaVersion
    payload: FrozenJson
    payload_hash: str
    referenced_event_ids: tuple[str, ...] = ()
    debug_digest: str | None = None

    def __post_init__(self) -> None:
        if self.payload_hash != self.payload.sha256:
            raise ValueError("cycle payload hash mismatch")
        if self.sequence < 0 or not all((self.recorder_session_id, self.core_cycle_id, self.source_snapshot_ref)):
            raise ValueError("invalid cycle record identity")


class RecordDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DROPPED_OLDEST = "DROPPED_OLDEST"


@dataclass(frozen=True, slots=True)
class RecordReceipt:
    disposition: RecordDisposition
    sequence: int
    reason_code: str


class DrainState(str, Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    DRAINED = "DRAINED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RecorderStatus:
    state: DrainState
    recorder_session_id: str | None
    queued: int
    persisted: int
    dropped: int
    dropped_sequence_ranges: tuple[tuple[int, int], ...]
    write_failures: int
    last_error: str | None
    current_segment: str | None


@dataclass(frozen=True, slots=True)
class RecorderStart:
    reason: str
    sample_hz: float


@dataclass(frozen=True, slots=True)
class RecorderSegmentMetadata:
    recorder_session_id: str
    created_at_utc: datetime
    reason: str
    sample_hz: float


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    keep_files: int


@dataclass(frozen=True, slots=True)
class PruneReceipt:
    removed: tuple[str, ...]
    failures: tuple[str, ...]


class EventPublisherPort(Protocol):
    def publish(self, event: OperationalEvent) -> PublishReceipt: ...


class EventQueryPort(Protocol):
    def latest(self, limit: int, cursor: str | None = None) -> OperationalEventPage: ...


class AuditSinkPort(Protocol):
    def append(self, entry: AuditEntry) -> AuditAppendReceipt: ...


class AuditQueryPort(Protocol):
    def latest(self, limit: int, cursor: str | None = None) -> AuditPage: ...


class CycleRecorderPort(Protocol):
    def start_session(self, request: RecorderStart) -> RecorderStatus: ...
    def record(self, record: CycleRecordEnvelope) -> RecordReceipt: ...
    def stop_session(self, reason: str) -> RecorderStatus: ...
    def status(self) -> RecorderStatus: ...
