from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from missions.common.control.types import FlightCommand, MissionStageInput, MissionStageStatus
from missions.rescue_competition.stages.downward_align_descend.config import (
    DownwardAlignDescendConfig,
)


@dataclass(slots=True)
class DownwardAlignDescendMode:
    name: ClassVar[str] = "DOWNWARD_ALIGN_DESCEND"
    config: DownwardAlignDescendConfig = field(default_factory=DownwardAlignDescendConfig)

    def reset(self) -> None:
        return None

    def update(self, inputs: MissionStageInput) -> tuple[FlightCommand, MissionStageStatus]:
        reason = self._hold_reason(inputs)
        enabled = reason == ""
        aligned = (
            abs(float(inputs.ex_cam)) <= self.config.max_ex_cam
            and abs(float(inputs.ey_cam)) <= self.config.max_ey_cam
        )
        vx = self._axis(
            float(inputs.ey_cam),
            kp=self.config.kp_vx,
            max_abs=self.config.max_vx_mps,
            sign=self.config.vx_sign,
            deadband=self.config.deadband_ey_cam,
        )
        vy = self._axis(
            float(inputs.ex_cam),
            kp=self.config.kp_vy,
            max_abs=self.config.max_vy_mps,
            sign=self.config.vy_sign,
            deadband=self.config.deadband_ex_cam,
        )
        vz = self.config.descend_speed_mps if enabled and aligned else 0.0
        command = FlightCommand(
            vx_cmd=vx if enabled else 0.0,
            vy_cmd=vy if enabled else 0.0,
            vz_cmd=vz if enabled else 0.0,
            yaw_rate_cmd=0.0,
            enable_body=enabled,
            enable_approach=enabled,
            enable_gimbal=False,
            active=enabled,
            valid=True,
        )
        return command, MissionStageStatus(
            mode_name=self.name,
            active=command.active,
            valid=True,
            hold_reason=reason or ("descending" if aligned else "aligning"),
            detail={
                "aligned": aligned,
                "enable_body": enabled,
                "enable_approach": enabled,
                "ex_cam": inputs.ex_cam,
                "ey_cam": inputs.ey_cam,
            },
        )

    def _hold_reason(self, inputs: MissionStageInput) -> str:
        if not inputs.control_allowed:
            return "control_not_allowed"
        if not inputs.fused_valid:
            return "fusion_not_valid"
        if not inputs.drone_valid or inputs.drone_age_s > self.config.max_drone_age_s:
            return "drone_not_fresh"
        if not inputs.vision_valid or inputs.vision_age_s > self.config.max_vision_age_s:
            return "vision_not_fresh"
        if not inputs.target_valid:
            return "target_not_valid"
        if self.config.require_target_locked and not inputs.target_locked:
            return "target_not_locked"
        return ""

    @staticmethod
    def _axis(value: float, *, kp: float, max_abs: float, sign: float, deadband: float) -> float:
        if abs(value) < deadband:
            return 0.0
        cmd = sign * kp * value
        limit = abs(max_abs)
        return min(limit, max(-limit, cmd))
