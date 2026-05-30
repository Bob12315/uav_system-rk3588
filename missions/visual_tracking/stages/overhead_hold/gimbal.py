from __future__ import annotations

import math
from dataclasses import dataclass, field

from missions.common.control.types import MissionStageInput
from missions.visual_tracking.stages.overhead_hold.config import OverheadGimbalConfig


@dataclass(slots=True)
class OverheadGimbalCommand:
    yaw_rate_cmd: float = 0.0
    pitch_rate_cmd: float = 0.0
    yaw_angle_cmd: float | None = None
    pitch_angle_cmd: float | None = None
    angle_active: bool = False
    pitch_aligned: bool = False
    active: bool = False
    valid: bool = False


@dataclass(slots=True)
class OverheadGimbalController:
    config: OverheadGimbalConfig = field(default_factory=OverheadGimbalConfig)
    _pitch_aligned: bool = field(init=False, default=False)
    _angle_command_sent: bool = field(init=False, default=False)

    def reset(self) -> None:
        self._pitch_aligned = False
        self._angle_command_sent = False

    def update(self, inputs: MissionStageInput, enabled: bool = True) -> OverheadGimbalCommand:
        if not enabled:
            self.reset()
            return self._make_inactive_command(valid=False)
        if not self._validate_input(inputs):
            self.reset()
            return self._make_inactive_command(valid=False)

        pitch_error_raw = self.config.downward_pitch_rad - float(inputs.gimbal_pitch)
        if abs(pitch_error_raw) <= self.config.deadband_pitch:
            self._pitch_aligned = True

        if self._pitch_aligned:
            return OverheadGimbalCommand(pitch_aligned=True, active=False, valid=True)

        if not self._angle_command_sent:
            self._angle_command_sent = True
            return OverheadGimbalCommand(
                yaw_angle_cmd=float(inputs.gimbal_yaw),
                pitch_angle_cmd=self.config.downward_pitch_rad,
                angle_active=True,
                pitch_aligned=False,
                active=True,
                valid=True,
            )

        return OverheadGimbalCommand(
            angle_active=False,
            pitch_aligned=False,
            active=False,
            valid=True,
        )

    def _validate_input(self, inputs: MissionStageInput) -> bool:
        if not (inputs.gimbal_valid and inputs.vision_valid):
            return False
        return math.isfinite(float(inputs.gimbal_yaw)) and math.isfinite(
            float(inputs.gimbal_pitch)
        )

    def _apply_deadband(self, value: float, threshold: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if threshold <= 0.0:
            return value
        if abs(value) < threshold:
            return 0.0
        return value

    def _clamp(self, value: float, lower: float, upper: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return min(upper, max(lower, value))

    def _make_inactive_command(self, valid: bool) -> OverheadGimbalCommand:
        return OverheadGimbalCommand(
            angle_active=False,
            pitch_aligned=self._pitch_aligned,
            active=False,
            valid=valid,
        )
