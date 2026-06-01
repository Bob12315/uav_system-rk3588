from __future__ import annotations

from dataclasses import dataclass, replace
from missions.base import MissionOutput
from missions.common.control.debug_config import StageDebugConfig
from missions.common.control.types import FlightCommand


@dataclass(slots=True)
class DebugRuntime:
    config: StageDebugConfig

    def apply_mission_override(self, mission: MissionOutput) -> MissionOutput:
        if not self.config.force_mode:
            return mission
        return replace(
            mission,
            active_mode=self.config.force_mode,
            previous_stage=mission.active_mode,
            hold_reason="debug_force_mode",
            detail=dict(mission.detail),
        )

    def apply_command_override(self, command: FlightCommand) -> FlightCommand:
        if self.config.enable_gimbal is not None:
            command.enable_gimbal = bool(self.config.enable_gimbal)
            if not command.enable_gimbal:
                command.gimbal_yaw_rate_cmd = 0.0
                command.gimbal_pitch_rate_cmd = 0.0
        if self.config.enable_body is not None:
            command.enable_body = bool(self.config.enable_body)
            if not command.enable_body:
                command.vy_cmd = 0.0
                command.yaw_rate_cmd = 0.0
        if self.config.enable_approach is not None:
            command.enable_approach = bool(self.config.enable_approach)
            if not command.enable_approach:
                command.vx_cmd = 0.0
        command.active = bool(
            command.enable_gimbal or command.enable_body or command.enable_approach
        )
        return command
