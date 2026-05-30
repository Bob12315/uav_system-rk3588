from __future__ import annotations

import math
from dataclasses import dataclass, field

from missions.common.control.types import MissionStageInput
from missions.visual_tracking.stages.overhead_hold.config import OverheadApproachConfig


@dataclass(slots=True)
class OverheadApproachCommand:
    vx_cmd: float = 0.0
    active: bool = False
    valid: bool = False


@dataclass(slots=True)
class OverheadApproachController:
    config: OverheadApproachConfig = field(default_factory=OverheadApproachConfig)
    _last_longitudinal_error: float | None = field(init=False, default=None)

    def reset(self) -> None:
        self._last_longitudinal_error = None

    def update(self, inputs: MissionStageInput, enabled: bool = True) -> OverheadApproachCommand:
        if not enabled:
            self.reset()
            return self._make_inactive_command(valid=False)
        if not self._validate_input(inputs):
            self.reset()
            return self._make_inactive_command(valid=False)

        longitudinal_error = self._apply_deadband(
            value=float(inputs.ey_cam),
            threshold=self.config.deadband_ey_cam,
        )

        vx_cmd = self.config.vx_sign * self.config.kp_vx * longitudinal_error

        if self.config.use_derivative and not math.isclose(
            longitudinal_error,
            0.0,
            abs_tol=1e-12,
        ):
            d_error = self._compute_derivative(
                value=float(inputs.ey_cam),
                last_value=self._last_longitudinal_error,
                dt=float(inputs.dt),
            )
            vx_cmd += self.config.vx_sign * self.config.kd_vx * d_error

        vx_cmd = self._clamp_vx(
            vx_cmd=vx_cmd,
            allow_backward=self.config.allow_backward,
        )
        self._last_longitudinal_error = float(inputs.ey_cam)

        return OverheadApproachCommand(
            vx_cmd=vx_cmd,
            active=not math.isclose(vx_cmd, 0.0, abs_tol=1e-9),
            valid=True,
        )

    def _validate_input(self, inputs: MissionStageInput) -> bool:
        if not (inputs.target_valid and inputs.vision_valid and inputs.drone_valid):
            return False
        return math.isfinite(float(inputs.ey_cam))

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

    def _make_inactive_command(self, valid: bool) -> OverheadApproachCommand:
        return OverheadApproachCommand(active=False, valid=valid)

