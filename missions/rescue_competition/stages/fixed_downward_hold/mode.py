from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import ClassVar

from missions.common.control.types import FlightCommand, MissionStageInput, MissionStageStatus
from missions.rescue_competition.stages.fixed_downward_hold.config import (
    FixedDownwardHoldConfig,
)


@dataclass(slots=True)
class FixedDownwardHoldMode:
    """Center a target under a vehicle with a physically fixed downward camera."""

    name: ClassVar[str] = "FIXED_DOWNWARD_HOLD"
    config: FixedDownwardHoldConfig = field(default_factory=FixedDownwardHoldConfig)
    _last_ex_cam: float | None = field(init=False, default=None)
    _last_ey_cam: float | None = field(init=False, default=None)

    def reset(self) -> None:
        self._last_ex_cam = None
        self._last_ey_cam = None

    def update(self, inputs: MissionStageInput) -> tuple[FlightCommand, MissionStageStatus]:
        hold_reason = self._hold_reason(inputs)
        if hold_reason:
            self.reset()
            return FlightCommand(valid=True), MissionStageStatus(
                mode_name=self.name,
                active=False,
                valid=True,
                hold_reason=hold_reason,
            )

        ex_cam = self._deadband(float(inputs.ex_cam), self.config.deadband_ex_cam)
        ey_cam = self._deadband(float(inputs.ey_cam), self.config.deadband_ey_cam)
        vy_cmd = self.config.vy_sign * self.config.kp_vy * ex_cam
        vx_cmd = self.config.vx_sign * self.config.kp_vx * ey_cam

        if self.config.use_derivative_vy:
            vy_cmd += self.config.vy_sign * self.config.kd_vy * self._derivative(
                float(inputs.ex_cam),
                self._last_ex_cam,
                float(inputs.dt),
            )
        if self.config.use_derivative_vx:
            vx_cmd += self.config.vx_sign * self.config.kd_vx * self._derivative(
                float(inputs.ey_cam),
                self._last_ey_cam,
                float(inputs.dt),
            )

        vy_cmd = self._clamp(vy_cmd, -self.config.max_vy, self.config.max_vy)
        vx_cmd = self._clamp(
            vx_cmd,
            -self.config.max_backward_vx if self.config.allow_backward else 0.0,
            self.config.max_forward_vx,
        )
        self._last_ex_cam = float(inputs.ex_cam)
        self._last_ey_cam = float(inputs.ey_cam)
        active = not (
            math.isclose(vx_cmd, 0.0, abs_tol=1e-9)
            and math.isclose(vy_cmd, 0.0, abs_tol=1e-9)
        )
        command = FlightCommand(
            vx_cmd=vx_cmd,
            vy_cmd=vy_cmd,
            enable_body=True,
            enable_approach=True,
            active=True,
            valid=True,
        )
        return command, MissionStageStatus(
            mode_name=self.name,
            active=command.active,
            valid=True,
            detail={"fixed_downward_camera": True, "body_motion_active": active},
        )

    def _hold_reason(self, inputs: MissionStageInput) -> str:
        if not inputs.control_allowed:
            return "control_not_allowed"
        if not inputs.vision_valid:
            return "vision_invalid"
        if not self._fresh(inputs.vision_age_s, self.config.max_vision_age_s):
            return "vision_stale"
        if not inputs.target_valid:
            return "no_target"
        if self.config.require_target_locked and not inputs.target_locked:
            return "target_not_locked"
        if not inputs.drone_valid:
            return "drone_invalid"
        if not self._fresh(inputs.drone_age_s, self.config.max_drone_age_s):
            return "drone_stale"
        if not math.isfinite(float(inputs.ex_cam)) or not math.isfinite(float(inputs.ey_cam)):
            return "camera_error_invalid"
        return ""

    @staticmethod
    def _fresh(age_s: float, max_age_s: float) -> bool:
        return (
            math.isfinite(float(age_s))
            and math.isfinite(float(max_age_s))
            and float(max_age_s) >= 0.0
            and float(age_s) <= float(max_age_s)
        )

    @staticmethod
    def _deadband(value: float, threshold: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return 0.0 if threshold > 0.0 and abs(value) < threshold else value

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return min(float(upper), max(float(lower), float(value))) if math.isfinite(value) else 0.0

    def _derivative(self, value: float, previous: float | None, dt: float) -> float:
        if previous is None or not math.isfinite(value) or not math.isfinite(previous):
            return 0.0
        if not math.isfinite(dt) or dt < self.config.dt_min:
            return 0.0
        return (value - previous) / dt
