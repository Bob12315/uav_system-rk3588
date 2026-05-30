from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.health_monitor import HealthStatus
from missions.common.control.types import MissionStageInput
from fusion.models import PerceptionTarget, SceneDetections
from telemetry_link.models import DroneState, GimbalState, LinkStatus


@dataclass(slots=True)
class MissionContext:
    timestamp: float
    inputs: MissionStageInput
    health: HealthStatus
    perception: PerceptionTarget
    drone: DroneState
    gimbal: GimbalState
    link: LinkStatus | None
    scene: SceneDetections | None = None
    actions_enabled: bool = False


@dataclass(slots=True)
class MissionAction:
    action_type: str
    params: dict[str, object] = field(default_factory=dict)
    key: str = ""
    once: bool = True
    priority: int = 5


@dataclass(slots=True)
class MissionOutput:
    active_mode: str
    actions: list[MissionAction] = field(default_factory=list)
    stage: str = ""
    previous_stage: str | None = None
    hold_reason: str = ""
    done: bool = False
    aborted: bool = False
    detail: dict[str, object] = field(default_factory=dict)


class Mission(Protocol):
    name: str

    def reset(self) -> None:
        ...

    def update(self, context: MissionContext) -> MissionOutput:
        ...
