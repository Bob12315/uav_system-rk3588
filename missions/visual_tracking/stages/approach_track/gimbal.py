from __future__ import annotations

import math
from dataclasses import dataclass, field

from missions.visual_tracking.stages.approach_track.config import ApproachGimbalConfig
from missions.common.control.types import MissionStageInput


@dataclass(slots=True)
class ApproachGimbalCommand:
    yaw_rate_cmd: float = 0.0
    pitch_rate_cmd: float = 0.0
    active: bool = False
    valid: bool = False


@dataclass(slots=True)
class ApproachGimbalController:
    config: ApproachGimbalConfig = field(default_factory=ApproachGimbalConfig)
    _yaw_integral: float = field(init=False, default=0.0)
    _pitch_integral: float = field(init=False, default=0.0)
    _last_ex_cam: float | None = field(init=False, default=None)
    _last_ey_cam: float | None = field(init=False, default=None)

    def reset(self) -> None:
        self._yaw_integral = 0.0
        self._pitch_integral = 0.0
        self._last_ex_cam = None
        self._last_ey_cam = None

    def update(self, inputs: MissionStageInput, enabled: bool = True) -> ApproachGimbalCommand:
        if not enabled:
            self.reset()
            return self._make_inactive_command(valid=False)
        if not self._validate_input(inputs):
            self.reset()
            return self._make_inactive_command(valid=False)

        ex_cam = self._apply_deadband(float(inputs.ex_cam), self.config.deadband_x)
        ey_cam = self._apply_deadband(float(inputs.ey_cam), self.config.deadband_y)
        dt = self._sanitize_dt(float(inputs.dt))

        if abs(ex_cam) <= self.config.center_hold_yaw_threshold:
            yaw_rate_cmd = 0.0
            self._yaw_integral = 0.0
            self._last_ex_cam = 0.0
        else:
            d_ex = 0.0
            if self.config.use_derivative:
                d_ex = self._compute_derivative(
                    value=float(inputs.ex_cam),
                    last_value=self._last_ex_cam,
                    dt=dt,
                    derivative_limit=self.config.derivative_limit_yaw,
                )
            self._yaw_integral = self._integrate(self._yaw_integral, ex_cam, dt)
            yaw_rate_cmd = self.config.yaw_sign * (
                self.config.kp_yaw * ex_cam
                + self.config.ki_yaw * self._yaw_integral
                + self.config.kd_yaw * d_ex
            )
            self._last_ex_cam = float(inputs.ex_cam)

        if abs(ey_cam) <= self.config.center_hold_pitch_threshold:
            pitch_rate_cmd = 0.0
            self._pitch_integral = 0.0
            self._last_ey_cam = 0.0
        else:
            d_ey = 0.0
            if self.config.use_derivative:
                d_ey = self._compute_derivative(
                    value=float(inputs.ey_cam),
                    last_value=self._last_ey_cam,
                    dt=dt,
                    derivative_limit=self.config.derivative_limit_pitch,
                )
            self._pitch_integral = self._integrate(self._pitch_integral, ey_cam, dt)
            pitch_rate_cmd = self.config.pitch_sign * (
                self.config.kp_pitch * ey_cam
                + self.config.ki_pitch * self._pitch_integral
                + self.config.kd_pitch * d_ey
            )
            self._last_ey_cam = float(inputs.ey_cam)

        yaw_rate_cmd = self._clamp(
            yaw_rate_cmd,
            -self.config.max_yaw_rate,
            self.config.max_yaw_rate,
        )
        pitch_rate_cmd = self._clamp(
            pitch_rate_cmd,
            -self.config.max_pitch_rate,
            self.config.max_pitch_rate,
        )

        return ApproachGimbalCommand(
            yaw_rate_cmd=yaw_rate_cmd,
            pitch_rate_cmd=pitch_rate_cmd,
            active=not (
                math.isclose(yaw_rate_cmd, 0.0, abs_tol=1e-9)
                and math.isclose(pitch_rate_cmd, 0.0, abs_tol=1e-9)
            ),
            valid=True,
        )

    def _validate_input(self, inputs: MissionStageInput) -> bool:
        if not (inputs.target_valid and inputs.vision_valid):
            return False
        return math.isfinite(float(inputs.ex_cam)) and math.isfinite(float(inputs.ey_cam))

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

    def _compute_derivative(
        self,
        value: float,
        last_value: float | None,
        dt: float,
        derivative_limit: float | None,
    ) -> float:
        if last_value is None:
            return 0.0
        if not math.isfinite(value) or not math.isfinite(last_value):
            return 0.0
        if not math.isfinite(dt) or dt < self.config.dt_min:
            return 0.0
        derivative = (value - last_value) / dt
        if derivative_limit is not None:
            derivative = max(-derivative_limit, min(derivative_limit, derivative))
        return derivative

    def _sanitize_dt(self, dt: float) -> float:
        if not math.isfinite(dt) or dt < self.config.dt_min:
            return 0.02
        return dt

    def _integrate(self, integral: float, error: float, dt: float) -> float:
        integral += error * dt
        return max(-self.config.integral_limit, min(self.config.integral_limit, integral))

    def _make_inactive_command(self, valid: bool) -> ApproachGimbalCommand:
        return ApproachGimbalCommand(active=False, valid=valid)
