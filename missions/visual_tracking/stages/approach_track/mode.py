from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import ClassVar

from missions.visual_tracking.stages.approach_track.config import ApproachTrackConfig
from missions.common.control.types import FlightCommand, MissionStageInput, MissionStageStatus


@dataclass(slots=True)
class ApproachTrackMode:
    name: ClassVar[str] = "APPROACH_TRACK"
    config: ApproachTrackConfig = field(default_factory=ApproachTrackConfig)
    _phase: str = field(init=False, default="TRACKING")
    _yaw_aligned_since: float | None = field(init=False, default=None)
    _gimbal_yaw_integral: float = field(init=False, default=0.0)
    _gimbal_pitch_integral: float = field(init=False, default=0.0)
    _last_ex_cam: float | None = field(init=False, default=None)
    _last_ey_cam: float | None = field(init=False, default=None)

    def reset(self) -> None:
        self._phase = "TRACKING"
        self._yaw_aligned_since = None
        self._gimbal_yaw_integral = 0.0
        self._gimbal_pitch_integral = 0.0
        self._last_ex_cam = None
        self._last_ey_cam = None

    def update(self, inputs: MissionStageInput) -> tuple[FlightCommand, MissionStageStatus]:
        vision_fresh = self._fresh(inputs.vision_valid, inputs.vision_age_s, self.config.max_vision_age_s)
        drone_fresh = self._fresh(inputs.drone_valid, inputs.drone_age_s, self.config.max_drone_age_s)
        gimbal_fresh = self._fresh(inputs.gimbal_valid, inputs.gimbal_age_s, self.config.max_gimbal_age_s)

        can_track = self._can_track(inputs, vision_fresh, gimbal_fresh)
        can_yaw = self._can_yaw(inputs, vision_fresh, drone_fresh, gimbal_fresh)
        can_approach_base = self._can_approach_base(
            inputs,
            vision_fresh,
            drone_fresh,
            gimbal_fresh,
        )
        yaw_aligned = self._update_yaw_alignment(inputs, can_yaw and can_approach_base)
        enable_approach = can_approach_base and yaw_aligned

        if can_track:
            gimbal_yaw_rate, gimbal_pitch_rate = self._gimbal_rates(inputs)
        else:
            self._reset_gimbal_pid()
            gimbal_yaw_rate = 0.0
            gimbal_pitch_rate = 0.0

        yaw_rate_cmd = self._body_yaw_rate(inputs) if can_yaw else 0.0
        yaw_quality = self._yaw_quality(inputs)
        image_quality = self._image_quality(inputs)
        enable_approach = enable_approach and image_quality > 0.0
        vx_cmd = self._forward_vx(inputs) * yaw_quality * image_quality if enable_approach else 0.0

        command = FlightCommand(
            vx_cmd=vx_cmd,
            vy_cmd=0.0,
            yaw_rate_cmd=yaw_rate_cmd,
            gimbal_yaw_rate_cmd=gimbal_yaw_rate,
            gimbal_pitch_rate_cmd=gimbal_pitch_rate,
            enable_body=can_yaw,
            enable_gimbal=can_track,
            enable_approach=enable_approach,
            active=can_track or can_yaw or enable_approach,
            valid=True,
        )
        mode_name = self._mode_name(can_track, can_yaw, enable_approach)
        hold_reason = self._hold_reason(
            inputs,
            vision_fresh,
            drone_fresh,
            gimbal_fresh,
            can_yaw,
            enable_approach,
        )
        return command, MissionStageStatus(
            mode_name=mode_name,
            active=command.active,
            valid=True,
            hold_reason=hold_reason,
            detail={
                "phase": self._phase,
                "enable_gimbal": can_track,
                "enable_body": can_yaw,
                "enable_approach": enable_approach,
                "vision_fresh": vision_fresh,
                "drone_fresh": drone_fresh,
                "gimbal_fresh": gimbal_fresh,
                "target_stable": bool(inputs.target_stable),
                "yaw_aligned": yaw_aligned,
                "yaw_quality": yaw_quality,
                "image_quality": image_quality,
                "yaw_aligned_since": self._yaw_aligned_since,
            },
        )

    def _can_track(self, inputs: MissionStageInput, vision_fresh: bool, gimbal_fresh: bool) -> bool:
        if not (inputs.control_allowed and inputs.fused_valid and vision_fresh and inputs.target_valid):
            return False
        if self.config.require_gimbal_fresh_for_gimbal and not gimbal_fresh:
            return False
        return self._finite(inputs.ex_cam) and self._finite(inputs.ey_cam)

    def _can_yaw(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        drone_fresh: bool,
        gimbal_fresh: bool,
    ) -> bool:
        if not (inputs.control_allowed and inputs.fused_valid and vision_fresh and drone_fresh):
            return False
        if self.config.require_gimbal_fresh_for_body and not gimbal_fresh:
            return False
        if not inputs.target_valid:
            return False
        if self.config.require_target_locked_for_body and not inputs.target_locked:
            return False
        return self._finite(inputs.gimbal_yaw)

    def _can_approach_base(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        drone_fresh: bool,
        gimbal_fresh: bool,
    ) -> bool:
        if not (inputs.control_allowed and inputs.fused_valid and vision_fresh and drone_fresh):
            return False
        if self.config.require_gimbal_fresh_for_approach and not gimbal_fresh:
            return False
        if not inputs.target_valid or not inputs.target_locked:
            return False
        if self.config.require_target_stable_for_approach and not inputs.target_stable:
            return False
        if inputs.track_switched:
            return False
        if not inputs.target_size_valid:
            return False
        target_size = float(inputs.target_size)
        return math.isfinite(target_size) and target_size > self.config.approach.min_valid_target_size

    def _gimbal_rates(self, inputs: MissionStageInput) -> tuple[float, float]:
        cfg = self.config.gimbal
        dt = self._sanitize_dt(inputs.dt, cfg.dt_min)
        ex = self._deadband(float(inputs.ex_cam), cfg.deadband_x)
        ey = self._deadband(float(inputs.ey_cam), cfg.deadband_y)

        if abs(ex) <= cfg.center_hold_yaw_threshold:
            yaw_rate = 0.0
            self._gimbal_yaw_integral = 0.0
            self._last_ex_cam = 0.0
        else:
            self._gimbal_yaw_integral = self._integrate(self._gimbal_yaw_integral, ex, dt)
            d_ex = self._derivative(float(inputs.ex_cam), self._last_ex_cam, dt, cfg.derivative_limit_yaw)
            if not cfg.use_derivative:
                d_ex = 0.0
            yaw_rate = cfg.yaw_sign * (
                cfg.kp_yaw * ex + cfg.ki_yaw * self._gimbal_yaw_integral + cfg.kd_yaw * d_ex
            )
            self._last_ex_cam = float(inputs.ex_cam)

        if abs(ey) <= cfg.center_hold_pitch_threshold:
            pitch_rate = 0.0
            self._gimbal_pitch_integral = 0.0
            self._last_ey_cam = 0.0
        else:
            self._gimbal_pitch_integral = self._integrate(self._gimbal_pitch_integral, ey, dt)
            d_ey = self._derivative(float(inputs.ey_cam), self._last_ey_cam, dt, cfg.derivative_limit_pitch)
            if not cfg.use_derivative:
                d_ey = 0.0
            pitch_rate = cfg.pitch_sign * (
                cfg.kp_pitch * ey
                + cfg.ki_pitch * self._gimbal_pitch_integral
                + cfg.kd_pitch * d_ey
            )
            self._last_ey_cam = float(inputs.ey_cam)

        return (
            self._clamp(yaw_rate, -cfg.max_yaw_rate, cfg.max_yaw_rate),
            self._clamp(pitch_rate, -cfg.max_pitch_rate, cfg.max_pitch_rate),
        )

    def _body_yaw_rate(self, inputs: MissionStageInput) -> float:
        cfg = self.config.body
        yaw_error = self._deadband(float(inputs.gimbal_yaw), cfg.deadband_gimbal_yaw)
        image_error = self._deadband(float(inputs.ex_cam), self.config.gimbal.deadband_x)
        yaw_rate = cfg.yaw_sign * (cfg.kp_yaw * yaw_error + cfg.kp_ex_cam_yaw * image_error)
        yaw_rate -= cfg.yaw_rate_damping * self._zero_if_bad(inputs.yaw_rate)
        yaw_rate = self._quantize(yaw_rate, cfg.yaw_step_rate)
        return self._clamp(yaw_rate, -cfg.max_yaw_rate, cfg.max_yaw_rate)

    def _forward_vx(self, inputs: MissionStageInput) -> float:
        cfg = self.config.approach
        size_error = cfg.target_size_ref - float(inputs.target_size)
        size_error = self._deadband(size_error, cfg.deadband_size)
        vx = cfg.vx_sign * cfg.kp_vx * size_error
        vx = min(cfg.max_forward_vx, vx)
        if cfg.allow_backward:
            return max(-cfg.max_backward_vx, vx)
        return max(0.0, vx)

    def _update_yaw_alignment(self, inputs: MissionStageInput, enabled: bool) -> bool:
        if not self.config.require_yaw_aligned_for_approach:
            self._yaw_aligned_since = float(inputs.timestamp)
            return True
        if not enabled:
            self._yaw_aligned_since = None
            return False
        yaw = abs(float(inputs.gimbal_yaw))
        if not math.isfinite(yaw):
            self._yaw_aligned_since = None
            return False
        threshold = self._yaw_exit_thresh() if self._phase == "APPROACHING" else self._yaw_enter_thresh()
        if yaw > threshold:
            self._yaw_aligned_since = None
            return False
        now = self._time_value(inputs.timestamp)
        if self._yaw_aligned_since is None:
            self._yaw_aligned_since = now
            return self.config.yaw_align_hold_s <= 0.0
        return (now - self._yaw_aligned_since) >= self.config.yaw_align_hold_s

    def _yaw_quality(self, inputs: MissionStageInput) -> float:
        yaw = abs(float(inputs.gimbal_yaw))
        if not math.isfinite(yaw):
            return 0.0
        exit_thresh = self._yaw_exit_thresh()
        if exit_thresh <= 0.0:
            return 1.0 if math.isclose(yaw, 0.0, abs_tol=1e-9) else 0.0
        quality = max(0.0, min(1.0, 1.0 - yaw / exit_thresh))
        min_quality = max(0.0, min(1.0, float(self.config.min_yaw_quality)))
        return max(min_quality, quality)

    def _image_quality(self, inputs: MissionStageInput) -> float:
        ex_cam = abs(float(inputs.ex_cam))
        if not math.isfinite(ex_cam):
            return 0.0
        cfg = self.config.approach
        start = max(0.0, float(cfg.ex_cam_slowdown_start))
        stop = max(start, float(cfg.max_ex_cam_for_approach))
        if ex_cam <= start:
            return 1.0
        if ex_cam >= stop:
            return 0.0
        span = stop - start
        if span <= 0.0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - (ex_cam - start) / span))

    def _mode_name(self, can_track: bool, can_yaw: bool, enable_approach: bool) -> str:
        if can_track and can_yaw and enable_approach:
            self._phase = "APPROACHING"
        elif can_track and can_yaw:
            self._phase = "YAW_ALIGNING"
        elif can_track:
            self._phase = "TRACKING"
        else:
            self._phase = "IDLE"
        return self._phase

    def _hold_reason(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        drone_fresh: bool,
        gimbal_fresh: bool,
        can_yaw: bool,
        enable_approach: bool,
    ) -> str:
        if can_yaw and enable_approach:
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
        if inputs.track_switched:
            return "track_switched"
        if self.config.require_target_stable_for_approach and not inputs.target_stable:
            return "target_not_stable"
        if not inputs.target_size_valid:
            return "target_size_invalid"
        if not self._target_size_valid(inputs):
            return "target_size_invalid"
        if self._image_quality(inputs) <= 0.0:
            return "image_not_centered"
        if self.config.require_yaw_aligned_for_approach and abs(float(inputs.gimbal_yaw)) > self._yaw_exit_thresh():
            return "yaw_not_aligned"
        if self.config.require_yaw_aligned_for_approach and not enable_approach:
            return "yaw_aligning"
        return ""

    def _target_size_valid(self, inputs: MissionStageInput) -> bool:
        value = float(inputs.target_size)
        return math.isfinite(value) and value > self.config.approach.min_valid_target_size

    def _reset_gimbal_pid(self) -> None:
        self._gimbal_yaw_integral = 0.0
        self._gimbal_pitch_integral = 0.0
        self._last_ex_cam = None
        self._last_ey_cam = None

    def _yaw_enter_thresh(self) -> float:
        value = float(self.config.yaw_align_enter_thresh_rad)
        if not math.isfinite(value) or value < 0.0:
            return float(self.config.yaw_align_thresh_rad)
        return value

    def _yaw_exit_thresh(self) -> float:
        value = float(self.config.yaw_align_exit_thresh_rad)
        if not math.isfinite(value) or value < 0.0:
            return float(self.config.yaw_align_thresh_rad)
        return value

    def _integrate(self, integral: float, error: float, dt: float) -> float:
        integral += error * dt
        limit = self.config.gimbal.integral_limit
        return self._clamp(integral, -limit, limit)

    @staticmethod
    def _fresh(valid: bool, age_s: float, max_age_s: float) -> bool:
        age_s = float(age_s)
        max_age_s = float(max_age_s)
        return bool(valid) and math.isfinite(age_s) and math.isfinite(max_age_s) and max_age_s >= 0.0 and age_s <= max_age_s

    @staticmethod
    def _deadband(value: float, threshold: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if threshold <= 0.0:
            return value
        return 0.0 if abs(value) < threshold else value

    @staticmethod
    def _derivative(value: float, last_value: float | None, dt: float, limit: float | None) -> float:
        if last_value is None or not math.isfinite(value) or not math.isfinite(last_value):
            return 0.0
        if not math.isfinite(dt) or dt <= 0.0:
            return 0.0
        derivative = (value - last_value) / dt
        if limit is not None:
            derivative = max(-limit, min(limit, derivative))
        return derivative

    @staticmethod
    def _sanitize_dt(dt: float, dt_min: float) -> float:
        dt = float(dt)
        dt_min = float(dt_min)
        if not math.isfinite(dt) or not math.isfinite(dt_min) or dt < dt_min:
            return 0.02
        return dt

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if lower > upper:
            lower, upper = upper, lower
        return min(upper, max(lower, value))

    @staticmethod
    def _quantize(value: float, step: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if not math.isfinite(step) or step <= 0.0 or math.isclose(value, 0.0, abs_tol=1e-9):
            return value
        return math.copysign(math.ceil(abs(value) / step) * step, value)

    @staticmethod
    def _zero_if_bad(value: float) -> float:
        value = float(value)
        return value if math.isfinite(value) else 0.0

    @staticmethod
    def _finite(value: float) -> bool:
        return math.isfinite(float(value))

    @staticmethod
    def _time_value(timestamp: float) -> float:
        timestamp = float(timestamp)
        return timestamp if math.isfinite(timestamp) else 0.0
