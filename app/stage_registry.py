from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass

from missions.base_stage import MissionStage
from missions.visual_tracking.stages.approach_track import ApproachTrackConfig, ApproachTrackMode
from missions.visual_tracking.stages.corridor_follow import CorridorFollowMode
from missions.visual_tracking.stages.overhead_hold import OverheadHoldConfig, OverheadHoldMode
from missions.rescue_competition.stages.fixed_downward_hold import (
    FixedDownwardHoldConfig,
    FixedDownwardHoldMode,
)


@dataclass(slots=True)
class StageRegistry:
    approach_config: ApproachTrackConfig
    overhead_config: OverheadHoldConfig
    fixed_downward_config: FixedDownwardHoldConfig = field(
        default_factory=FixedDownwardHoldConfig
    )
    _stages: dict[str, MissionStage] = field(init=False)

    def __post_init__(self) -> None:
        self._stages = {
            ApproachTrackMode.name: ApproachTrackMode(config=self.approach_config),
            OverheadHoldMode.name: OverheadHoldMode(config=self.overhead_config),
            FixedDownwardHoldMode.name: FixedDownwardHoldMode(
                config=self.fixed_downward_config
            ),
            CorridorFollowMode.name: CorridorFollowMode(),
        }

    def get(self, name: str) -> MissionStage:
        try:
            return self._stages[name]
        except KeyError as exc:
            raise KeyError(f"unknown mission stage controller: {name}") from exc

    def reset_all(self) -> None:
        for stage in self._stages.values():
            stage.reset()

    def apply_configs(
        self,
        *,
        approach_config: ApproachTrackConfig,
        overhead_config: OverheadHoldConfig,
        fixed_downward_config: FixedDownwardHoldConfig | None = None,
        reset: bool = True,
    ) -> None:
        copy_dataclass_values(self.approach_config, approach_config)
        copy_dataclass_values(self.overhead_config, overhead_config)
        if fixed_downward_config is not None:
            copy_dataclass_values(self.fixed_downward_config, fixed_downward_config)
        if reset:
            self.reset_all()


def copy_dataclass_values(target: object, source: object) -> None:
    if not (is_dataclass(target) and is_dataclass(source)):
        raise TypeError("runtime config updates require dataclass instances")
    for item in fields(target):
        next_value = getattr(source, item.name)
        current_value = getattr(target, item.name)
        if is_dataclass(current_value) and is_dataclass(next_value):
            copy_dataclass_values(current_value, next_value)
        else:
            setattr(target, item.name, next_value)
