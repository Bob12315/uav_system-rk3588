from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from missions.common.control.types import FlightCommand, MissionStageInput, MissionStageStatus
from missions.visual_tracking.stages.corridor_follow.config import CorridorFollowConfig


@dataclass(slots=True)
class CorridorFollowMode:
    name: ClassVar[str] = "CORRIDOR_FOLLOW"
    config: CorridorFollowConfig = field(default_factory=CorridorFollowConfig)

    def reset(self) -> None:
        pass

    def update(self, inputs: MissionStageInput) -> tuple[FlightCommand, MissionStageStatus]:
        command = FlightCommand(valid=True)
        status = MissionStageStatus(
            mode_name=self.name,
            active=False,
            valid=True,
            hold_reason="not_implemented",
            detail={"enabled": self.config.enabled},
        )
        return command, status
