from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import ClassVar

from missions.common.control.types import FlightCommand, MissionStageInput, MissionStageStatus
from missions.visual_tracking.stages.overhead_hold.approach import OverheadApproachController
from missions.visual_tracking.stages.overhead_hold.body import OverheadBodyController
from missions.visual_tracking.stages.overhead_hold.config import OverheadHoldConfig
from missions.visual_tracking.stages.overhead_hold.gimbal import OverheadGimbalController


@dataclass(slots=True)
class OverheadHoldMode:
    name: ClassVar[str] = "OVERHEAD_HOLD"
    config: OverheadHoldConfig = field(default_factory=OverheadHoldConfig)
    gimbal: OverheadGimbalController = field(init=False)
    body: OverheadBodyController = field(init=False)
    approach: OverheadApproachController = field(init=False)

    def __post_init__(self) -> None:
        self.gimbal = OverheadGimbalController(config=self.config.gimbal)
        self.body = OverheadBodyController(config=self.config.body)
        self.approach = OverheadApproachController(config=self.config.approach)

    def reset(self) -> None:
        self.gimbal.reset()
        self.body.reset()
        self.approach.reset()

    def update(self, inputs: MissionStageInput) -> tuple[FlightCommand, MissionStageStatus]:
        vision_fresh = self._vision_fresh(inputs)
        drone_fresh = self._drone_fresh(inputs)
        gimbal_fresh = self._gimbal_fresh(inputs)

        enable_gimbal = self._compute_enable_gimbal(inputs, vision_fresh, gimbal_fresh)
        enable_body = self._compute_enable_body(
            inputs,
            vision_fresh,
            drone_fresh,
            gimbal_fresh,
        )
        enable_approach = self._compute_enable_approach(
            inputs,
            vision_fresh,
            drone_fresh,
            gimbal_fresh,
        )

        gimbal_cmd = self.gimbal.update(inputs, enabled=enable_gimbal)
        enable_gimbal_output = (
            enable_gimbal and gimbal_cmd.active and not gimbal_cmd.angle_active
        )
        body_cmd = self.body.update(inputs, enabled=enable_body)
        approach_cmd = self.approach.update(inputs, enabled=enable_approach)

        command = FlightCommand(
            vx_cmd=approach_cmd.vx_cmd if approach_cmd.valid and approach_cmd.active else 0.0,
            vy_cmd=body_cmd.vy_cmd if body_cmd.valid and body_cmd.active else 0.0,
            yaw_rate_cmd=body_cmd.yaw_rate_cmd if body_cmd.valid and body_cmd.active else 0.0,
            gimbal_yaw_angle_cmd=(
                gimbal_cmd.yaw_angle_cmd
                if gimbal_cmd.valid and gimbal_cmd.angle_active
                else None
            ),
            gimbal_pitch_angle_cmd=(
                gimbal_cmd.pitch_angle_cmd
                if gimbal_cmd.valid and gimbal_cmd.angle_active
                else None
            ),
            gimbal_yaw_rate_cmd=(
                gimbal_cmd.yaw_rate_cmd if gimbal_cmd.valid and gimbal_cmd.active else 0.0
            ),
            gimbal_pitch_rate_cmd=(
                gimbal_cmd.pitch_rate_cmd if gimbal_cmd.valid and gimbal_cmd.active else 0.0
            ),
            enable_body=enable_body,
            enable_gimbal=enable_gimbal_output,
            enable_gimbal_angle=enable_gimbal and gimbal_cmd.angle_active,
            enable_approach=enable_approach,
            active=enable_gimbal_output or gimbal_cmd.angle_active or enable_body or enable_approach,
            valid=True,
        )
        mode_name = (
            "OVERHEAD_HOLD"
            if enable_gimbal and enable_body and enable_approach
            else "OVERHEAD_RECOVERY"
        )
        hold_reason = self._compute_hold_reason(
            inputs,
            vision_fresh,
            drone_fresh,
            gimbal_fresh,
            enable_body,
            enable_approach,
        )
        status = MissionStageStatus(
            mode_name=mode_name,
            active=command.active,
            valid=True,
            hold_reason=hold_reason,
            detail={
                "enable_gimbal": enable_gimbal,
                "enable_gimbal_output": enable_gimbal_output,
                "enable_gimbal_angle": command.enable_gimbal_angle,
                "gimbal_pitch_aligned": gimbal_cmd.pitch_aligned,
                "enable_body": enable_body,
                "enable_approach": enable_approach,
                "vision_fresh": vision_fresh,
                "drone_fresh": drone_fresh,
                "gimbal_fresh": gimbal_fresh,
            },
        )
        return command, status

    def _compute_enable_gimbal(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        gimbal_fresh: bool,
    ) -> bool:
        if not (
            inputs.control_allowed
            and inputs.fused_valid
            and vision_fresh
            and inputs.target_valid
        ):
            return False
        if self.config.require_gimbal_fresh_for_gimbal and not gimbal_fresh:
            return False
        return True

    def _compute_enable_body(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        drone_fresh: bool,
        gimbal_fresh: bool,
    ) -> bool:
        if not inputs.control_allowed:
            return False
        if not inputs.fused_valid or not vision_fresh or not drone_fresh:
            return False
        if self.config.require_gimbal_fresh_for_body and not gimbal_fresh:
            return False
        if not inputs.target_valid:
            return False
        return True

    def _compute_enable_approach(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        drone_fresh: bool,
        gimbal_fresh: bool,
    ) -> bool:
        if not inputs.control_allowed:
            return False
        if not inputs.fused_valid or not vision_fresh or not drone_fresh:
            return False
        if self.config.require_gimbal_fresh_for_approach and not gimbal_fresh:
            return False
        if not inputs.target_valid or not inputs.target_locked:
            return False
        return True

    def _compute_hold_reason(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        drone_fresh: bool,
        gimbal_fresh: bool,
        enable_body: bool,
        enable_approach: bool,
    ) -> str:
        if enable_body and enable_approach:
            return ""
        if not inputs.control_allowed:
            return "control_not_allowed"
        if not inputs.fused_valid:
            return "fusion_invalid"
        if not inputs.vision_valid:
            return "vision_invalid"
        if not vision_fresh:
            return "vision_stale"
        if not inputs.target_valid:
            return "no_target"
        if not inputs.drone_valid:
            return "drone_invalid"
        if not drone_fresh:
            return "drone_stale"
        if self.config.require_gimbal_fresh_for_gimbal and not gimbal_fresh:
            return "gimbal_stale"
        if (
            self.config.require_gimbal_fresh_for_body
            or self.config.require_gimbal_fresh_for_approach
        ) and not inputs.gimbal_valid:
            return "gimbal_invalid"
        if (
            self.config.require_gimbal_fresh_for_body
            or self.config.require_gimbal_fresh_for_approach
        ) and not gimbal_fresh:
            return "gimbal_stale"
        if not inputs.target_locked:
            return "target_not_locked"
        return ""

    def _vision_fresh(self, inputs: MissionStageInput) -> bool:
        return inputs.vision_valid and self._age_fresh(
            inputs.vision_age_s,
            self.config.max_vision_age_s,
        )

    def _drone_fresh(self, inputs: MissionStageInput) -> bool:
        return inputs.drone_valid and self._age_fresh(
            inputs.drone_age_s,
            self.config.max_drone_age_s,
        )

    def _gimbal_fresh(self, inputs: MissionStageInput) -> bool:
        return inputs.gimbal_valid and self._age_fresh(
            inputs.gimbal_age_s,
            self.config.max_gimbal_age_s,
        )

    @staticmethod
    def _age_fresh(age_s: float, max_age_s: float) -> bool:
        age_s = float(age_s)
        max_age_s = float(max_age_s)
        if not math.isfinite(age_s) or not math.isfinite(max_age_s):
            return False
        if max_age_s < 0.0:
            return False
        return age_s <= max_age_s
