from __future__ import annotations

from typing import Protocol

from missions.common.control.types import FlightCommand, MissionStageInput, MissionStageStatus


class MissionStage(Protocol):
    name: str

    def reset(self) -> None:
        ...

    def update(self, inputs: MissionStageInput) -> tuple[FlightCommand, MissionStageStatus]:
        ...
