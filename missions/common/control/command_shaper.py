from __future__ import annotations

import math
from dataclasses import dataclass, field

from missions.common.control.types import FlightCommand


@dataclass(slots=True)
class CommandShaperConfig:
    max_vx: float = 0.8
    max_vy: float = 1.0
    max_vz: float = 0.5
    max_yaw_rate: float = 1.0
    max_gimbal_yaw_rate: float = 1.0
    max_gimbal_pitch_rate: float = 1.0
    max_vx_rate: float = 1.0
    max_vy_rate: float = 1.5
    max_vz_rate: float = 1.0
    max_yaw_rate_rate: float = 2.0
    max_gimbal_yaw_rate_rate: float = 3.0
    max_gimbal_pitch_rate_rate: float = 3.0
    smooth_to_zero_when_disabled: bool = True
    dt_min: float = 1e-3


@dataclass(slots=True)
class CommandShaper:
    config: CommandShaperConfig = field(default_factory=CommandShaperConfig)
    _last_command: FlightCommand = field(init=False, default_factory=FlightCommand)

    def reset(self) -> None:
        self._last_command = FlightCommand(valid=False)

    def update(self, raw: FlightCommand, dt: float) -> FlightCommand:
        enable_body = bool(raw.enable_body)
        enable_gimbal = bool(raw.enable_gimbal)
        enable_gimbal_angle = bool(raw.enable_gimbal_angle)
        enable_approach = bool(raw.enable_approach)
        body_enabled = enable_body or enable_approach

        target_vx = self._clamp(
            self._target_or_zero(raw.vx_cmd, body_enabled),
            -self.config.max_vx,
            self.config.max_vx,
        )
        target_vy = self._clamp(
            self._target_or_zero(raw.vy_cmd, body_enabled),
            -self.config.max_vy,
            self.config.max_vy,
        )
        target_vz = self._clamp(
            self._target_or_zero(raw.vz_cmd, body_enabled),
            -self.config.max_vz,
            self.config.max_vz,
        )
        target_yaw_rate = self._clamp(
            self._target_or_zero(raw.yaw_rate_cmd, body_enabled),
            -self.config.max_yaw_rate,
            self.config.max_yaw_rate,
        )
        target_gimbal_yaw_rate = self._clamp(
            self._target_or_zero(raw.gimbal_yaw_rate_cmd, enable_gimbal),
            -self.config.max_gimbal_yaw_rate,
            self.config.max_gimbal_yaw_rate,
        )
        target_gimbal_pitch_rate = self._clamp(
            self._target_or_zero(raw.gimbal_pitch_rate_cmd, enable_gimbal),
            -self.config.max_gimbal_pitch_rate,
            self.config.max_gimbal_pitch_rate,
        )

        shaped_vx = self._shape_channel(
            target=target_vx,
            previous=self._last_command.vx_cmd,
            enabled=body_enabled,
            max_delta_rate=self.config.max_vx_rate,
            dt=dt,
        )
        shaped_vy = self._shape_channel(
            target=target_vy,
            previous=self._last_command.vy_cmd,
            enabled=body_enabled,
            max_delta_rate=self.config.max_vy_rate,
            dt=dt,
        )
        shaped_vz = self._shape_channel(
            target=target_vz,
            previous=self._last_command.vz_cmd,
            enabled=body_enabled,
            max_delta_rate=self.config.max_vz_rate,
            dt=dt,
        )
        shaped_yaw_rate = self._shape_channel(
            target=target_yaw_rate,
            previous=self._last_command.yaw_rate_cmd,
            enabled=body_enabled,
            max_delta_rate=self.config.max_yaw_rate_rate,
            dt=dt,
        )
        shaped_gimbal_yaw_rate = self._shape_channel(
            target=target_gimbal_yaw_rate,
            previous=self._last_command.gimbal_yaw_rate_cmd,
            enabled=enable_gimbal,
            max_delta_rate=self.config.max_gimbal_yaw_rate_rate,
            dt=dt,
        )
        shaped_gimbal_pitch_rate = self._shape_channel(
            target=target_gimbal_pitch_rate,
            previous=self._last_command.gimbal_pitch_rate_cmd,
            enabled=enable_gimbal,
            max_delta_rate=self.config.max_gimbal_pitch_rate_rate,
            dt=dt,
        )

        command = FlightCommand(
            vx_cmd=self._clamp(shaped_vx, -self.config.max_vx, self.config.max_vx),
            vy_cmd=self._clamp(shaped_vy, -self.config.max_vy, self.config.max_vy),
            vz_cmd=self._clamp(shaped_vz, -self.config.max_vz, self.config.max_vz),
            yaw_rate_cmd=self._clamp(
                shaped_yaw_rate,
                -self.config.max_yaw_rate,
                self.config.max_yaw_rate,
            ),
            gimbal_yaw_rate_cmd=self._clamp(
                shaped_gimbal_yaw_rate,
                -self.config.max_gimbal_yaw_rate,
                self.config.max_gimbal_yaw_rate,
            ),
            gimbal_pitch_rate_cmd=self._clamp(
                shaped_gimbal_pitch_rate,
                -self.config.max_gimbal_pitch_rate,
                self.config.max_gimbal_pitch_rate,
            ),
            gimbal_yaw_angle_cmd=self._angle_or_none(raw.gimbal_yaw_angle_cmd),
            gimbal_pitch_angle_cmd=self._angle_or_none(raw.gimbal_pitch_angle_cmd),
            enable_body=enable_body,
            enable_gimbal=enable_gimbal,
            enable_gimbal_angle=enable_gimbal_angle,
            enable_approach=enable_approach,
            active=self._compute_active(
                enable_body=enable_body,
                enable_gimbal=enable_gimbal,
                enable_gimbal_angle=enable_gimbal_angle,
                enable_approach=enable_approach,
                vx_cmd=shaped_vx,
                vy_cmd=shaped_vy,
                vz_cmd=shaped_vz,
                yaw_rate_cmd=shaped_yaw_rate,
                gimbal_yaw_rate_cmd=shaped_gimbal_yaw_rate,
                gimbal_pitch_rate_cmd=shaped_gimbal_pitch_rate,
            ),
            valid=bool(raw.valid),
        )

        self._last_command = command
        return command

    def _target_or_zero(self, value: float, enabled: bool) -> float:
        if not enabled:
            return 0.0
        return self._sanitize(value)

    def _shape_channel(
        self,
        target: float,
        previous: float,
        enabled: bool,
        max_delta_rate: float,
        dt: float,
    ) -> float:
        target = self._sanitize(target)
        previous = self._sanitize(previous)
        if not enabled and not self.config.smooth_to_zero_when_disabled:
            return 0.0
        return self._slew_limit(
            target=target,
            previous=previous,
            max_delta_rate=max_delta_rate,
            dt=dt,
        )

    def _clamp(self, value: float, lower: float, upper: float) -> float:
        value = self._sanitize(value)
        if lower > upper:
            lower, upper = upper, lower
        return min(upper, max(lower, value))

    def _slew_limit(
        self,
        target: float,
        previous: float,
        max_delta_rate: float,
        dt: float,
    ) -> float:
        if max_delta_rate <= 0.0:
            return target
        if not math.isfinite(float(dt)) or float(dt) < self.config.dt_min:
            return target
        max_delta = max_delta_rate * float(dt)
        delta = target - previous
        delta = self._clamp(delta, -max_delta, max_delta)
        return previous + delta

    def _compute_active(
        self,
        enable_body: bool,
        enable_gimbal: bool,
        enable_gimbal_angle: bool,
        enable_approach: bool,
        vx_cmd: float,
        vy_cmd: float,
        vz_cmd: float,
        yaw_rate_cmd: float,
        gimbal_yaw_rate_cmd: float,
        gimbal_pitch_rate_cmd: float,
    ) -> bool:
        if enable_body or enable_gimbal or enable_gimbal_angle or enable_approach:
            return True
        return not all(
            math.isclose(value, 0.0, abs_tol=1e-9)
            for value in (
                vx_cmd,
                vy_cmd,
                vz_cmd,
                yaw_rate_cmd,
                gimbal_yaw_rate_cmd,
                gimbal_pitch_rate_cmd,
            )
        )

    @staticmethod
    def _sanitize(value: float) -> float:
        value = float(value)
        if not math.isfinite(value):
            return 0.0
        return value

    @staticmethod
    def _angle_or_none(value: float | None) -> float | None:
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value):
            return None
        return value
