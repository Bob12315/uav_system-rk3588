from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.platform.common import SchemaVersion

from .action import ActionSnapshot
from .common import FrozenJson
from .input_state import CycleCorrelation, RuntimeInputSnapshot
from .mission import MissionSnapshot
from .run import RunSnapshot
from .time import CoreTime


@dataclass(frozen=True, slots=True)
class SchedulerHealth:
    cadence_ns: int
    duration_ns: int
    overrun_ns: int
    skipped_catch_up_ticks: int


@dataclass(frozen=True, slots=True)
class CoreCycleSnapshot:
    schema_version: SchemaVersion
    correlation: CycleCorrelation
    started_at: CoreTime
    finished_at: CoreTime
    input_snapshot: RuntimeInputSnapshot
    run: RunSnapshot | None
    action: ActionSnapshot | None
    mission: MissionSnapshot | None
    system: FrozenJson
    scheduler_health: SchedulerHealth
    final: bool = False


class CoreCyclePublisherPort(Protocol):
    def publish(self, snapshot: CoreCycleSnapshot) -> None: ...


class CoreCycleQueryPort(Protocol):
    def current(self) -> CoreCycleSnapshot | None: ...
