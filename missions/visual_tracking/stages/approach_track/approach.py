from __future__ import annotations

import math
from dataclasses import dataclass, field

from missions.visual_tracking.stages.approach_track.config import ApproachForwardConfig
from missions.common.control.types import MissionStageInput


@dataclass(slots=True)
class ApproachForwardCommand:
    vx_cmd: float = 0.0
    active: bool = False
    valid: bool = False


@dataclass(slots=True)
class ApproachForwardController:
    config: ApproachForwardConfig = field(default_factory=ApproachForwardConfig)
    _last_longitudinal_error: float | None = field(init=False, default=None)

    def reset(self) -> None:
        self._last_longitudinal_error = None

    def update(self, inputs: MissionStageInput, enabled: bool = True) -> ApproachForwardCommand:
        if not enabled:
            self.reset()
            return self._make_inactive_command(valid=False)
        if not self._validate_input(inputs):
            self.reset()
            return self._make_inactive_command(valid=False)

        size_error = self._compute_size_error(
            target_size=float(inputs.target_size),
            target_size_ref=self.config.target_size_ref,
        )
        size_error_for_control = self._apply_deadband(
            value=size_error,
            threshold=self.config.deadband_size,
        )

        vx_cmd = self.config.vx_sign * self.config.kp_vx * size_error_for_control

        if self.config.use_derivative and not math.isclose(
            size_error_for_control,
            0.0,
            abs_tol=1e-12,
        ):
            d_size_error = self._compute_derivative(
                value=size_error,
                last_value=self._last_longitudinal_error,
                dt=float(inputs.dt),
            )
            vx_cmd += self.config.vx_sign * self.config.kd_vx * d_size_error

        vx_cmd = self._clamp_vx(
            vx_cmd=vx_cmd,
            allow_backward=self.config.allow_backward,
        )
        self._last_longitudinal_error = size_error

        return ApproachForwardCommand(
            vx_cmd=vx_cmd,
            active=not math.isclose(vx_cmd, 0.0, abs_tol=1e-9),
            valid=True,
        )

    def _validate_input(self, inputs: MissionStageInput) -> bool:
        if not (inputs.target_valid and inputs.vision_valid and inputs.drone_valid):
            return False
        if not inputs.target_size_valid:
            return False
        target_size = float(inputs.target_size)
        if not math.isfinite(target_size):
            return False
        return target_size > self.config.min_valid_target_size

    def _compute_size_error(self, target_size: float, target_size_ref: float) -> float:
        if not math.isfinite(target_size) or not math.isfinite(target_size_ref):
            return 0.0
        return target_size_ref - target_size

    def _apply_deadband(self, value: float, threshold: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if threshold <= 0.0:
            return value
        if abs(value) < threshold:
            return 0.0
        return value

    def _clamp_vx(self, vx_cmd: float, allow_backward: bool) -> float:
        if not math.isfinite(vx_cmd):
            return 0.0
        vx_cmd = min(self.config.max_forward_vx, vx_cmd)
        if allow_backward:
            return max(-self.config.max_backward_vx, vx_cmd)
        return max(0.0, vx_cmd)

    def _compute_derivative(
        self,
        value: float,
        last_value: float | None,
        dt: float,
    ) -> float:
        if last_value is None:
            return 0.0
        if not math.isfinite(value) or not math.isfinite(last_value):
            return 0.0
        if not math.isfinite(dt) or dt < self.config.dt_min:
            return 0.0
        return (value - last_value) / dt

    def _make_inactive_command(self, valid: bool) -> ApproachForwardCommand:
        return ApproachForwardCommand(active=False, valid=valid)

