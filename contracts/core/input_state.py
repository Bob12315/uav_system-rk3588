from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from contracts.platform.common import (
    LinkSessionId,
    ResourceVersion,
    SchemaVersion,
    SendGeneration,
    SourceId,
)
from contracts.platform.field import FieldReferenceSnapshot, ReferenceVersion
from contracts.platform.perception import PerceptionFrameSnapshot
from contracts.platform.vehicle_state import VehicleStateSnapshot

from .common import CoreCycleId, FrozenJson, InputSnapshotId, SchedulerSessionId
from .time import CoreTime


class FreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ComponentFreshness:
    state: FreshnessState
    age_ns: int | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.age_ns is not None and self.age_ns < 0:
            raise ValueError("component age must be non-negative")


@dataclass(frozen=True, slots=True)
class InputSnapshotRef:
    snapshot_id: InputSnapshotId
    publication_version: ResourceVersion


@dataclass(frozen=True, slots=True)
class VehicleSnapshotRef:
    source: SourceId
    link_session_id: LinkSessionId
    sequence: int


@dataclass(frozen=True, slots=True)
class PerceptionFrameRef:
    process_session_id: str
    sequence: int
    frame_id: int


@dataclass(frozen=True, slots=True)
class SendGateSnapshot:
    enabled: bool
    generation: SendGeneration
    version: ResourceVersion

    @property
    def send_commands(self) -> bool:
        return self.enabled


class FusionState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FusionSnapshot:
    state: FusionState
    vehicle_ref: VehicleSnapshotRef | None
    perception_ref: PerceptionFrameRef | None
    field_reference_version: ReferenceVersion | None
    payload: FrozenJson
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeInputSnapshot:
    schema_version: SchemaVersion
    ref: InputSnapshotRef
    captured_at: CoreTime
    vehicle: VehicleStateSnapshot | None
    vehicle_freshness: ComponentFreshness
    perception: PerceptionFrameSnapshot | None
    perception_freshness: ComponentFreshness
    field: FieldReferenceSnapshot | None
    field_freshness: ComponentFreshness
    fusion: FusionSnapshot
    send_gate: SendGateSnapshot


@dataclass(frozen=True, slots=True)
class CycleCorrelation:
    scheduler_session_id: SchedulerSessionId
    cycle_id: CoreCycleId
    tick_sequence: int
    input_ref: InputSnapshotRef

    def __post_init__(self) -> None:
        if self.tick_sequence < 0:
            raise ValueError("tick sequence must be non-negative")


class FusionComputePort(Protocol):
    def compute(
        self,
        vehicle: VehicleStateSnapshot | None,
        perception: PerceptionFrameSnapshot | None,
        field: FieldReferenceSnapshot | None,
    ) -> FusionSnapshot: ...


class RuntimeInputPublisherPort(Protocol):
    def capture_and_publish(self, now: CoreTime) -> RuntimeInputSnapshot: ...


class RuntimeInputQueryPort(Protocol):
    def current(self) -> RuntimeInputSnapshot | None: ...
