from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AlignDescendConfig:
    kp_vx: float = 0.4
    kp_vy: float = 0.4
    max_vx_mps: float = 0.4
    max_vy_mps: float = 0.4
    descend_speed_mps: float = 0.2
    slow_descend_speed_mps: float = 0.0
    max_ex_cam: float = 0.06
    max_ey_cam: float = 0.06
    slow_descend_max_ex_cam: float | None = None
    slow_descend_max_ey_cam: float | None = None
    min_altitude_m: float = 2.0
    deadband_ex_cam: float = 0.015
    deadband_ey_cam: float = 0.015
    vx_sign: float = -1.0
    vy_sign: float = 1.0
    require_target_locked: bool = True
    height_gain_enabled: bool = False
    gain_low_altitude_m: float = 1.2
    gain_high_altitude_m: float = 3.0
    gain_high_scale: float = 0.3
    scale_max_velocity_with_height: bool = True
    height_gain_mode: str = "linear"
    height_scale_points: list[dict[str, float]] | None = None
    # payload drop offset compensation (BODY frame, m)
    payload_offset_enabled: bool = False
    payload_forward_m: float = 0.0
    payload_right_m: float = 0.0
    fov_x_deg: float = 113.0
    fov_y_deg: float = 93.0
    image_x_sign: float = 1.0
    image_y_sign: float = -1.0
    max_payload_offset_ex_cam: float = 0.8
    max_payload_offset_ey_cam: float = 0.8
    # unaligned descent gate for recon mode (default keeps existing behaviour)
    descent_gate_policy: str = "aligned_or_slow"
    unaligned_descend_speed_mps: float = 0.0
    # Hold preserves legacy yaw behavior; ignore emits pure BODY_NED velocity.
    yaw_control_mode: str = "hold"
    altitude_source: str = "auto"
    descent_speed_stages: list[dict[str, float]] | None = None
    # target loss behaviour — "fail" (default, existing behaviour) or "continue_descent"
    target_loss_policy: str = "fail"
    target_loss_descend_speed_mps: float = 0.0
    # Low-altitude visual-alignment assistance. Disabled by default so visual
    # landing and existing missions retain their current behaviour.
    integral_enabled: bool = False
    integral_active_below_altitude_m: float = 1.6
    ki_vx: float = 0.04
    ki_vy: float = 0.04
    integral_vx_limit_mps: float = 0.03
    integral_vy_limit_mps: float = 0.03
    min_effective_speed_enabled: bool = False
    min_effective_speed_active_below_altitude_m: float = 1.6
    min_effective_speed_mps: float = 0.035
    min_effective_speed_ex_threshold: float = 0.12
    min_effective_speed_ey_threshold: float = 0.16
    target_loss_grace_updates: int = 0
    target_loss_grace_horizontal_scale: float = 0.5

    def __post_init__(self) -> None:
        for name in ("kp_vx", "kp_vy"):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("max_vx_mps", "max_vy_mps", "descend_speed_mps"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
        slow_value = float(self.slow_descend_speed_mps)
        if not math.isfinite(slow_value):
            raise ValueError("slow_descend_speed_mps must be finite")
        if slow_value < 0.0:
            raise ValueError("slow_descend_speed_mps must be non-negative")
        for name in ("max_ex_cam", "max_ey_cam"):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be positive")
        for name in ("slow_descend_max_ex_cam", "slow_descend_max_ey_cam"):
            value = getattr(self, name)
            if value is not None and float(value) <= 0.0:
                raise ValueError(f"{name} must be positive when set")
        if (
            self.slow_descend_max_ex_cam is not None
            and float(self.slow_descend_max_ex_cam) < float(self.max_ex_cam)
        ):
            raise ValueError("slow_descend_max_ex_cam must be >= max_ex_cam")
        if (
            self.slow_descend_max_ey_cam is not None
            and float(self.slow_descend_max_ey_cam) < float(self.max_ey_cam)
        ):
            raise ValueError("slow_descend_max_ey_cam must be >= max_ey_cam")
        if float(self.min_altitude_m) <= 0.0:
            raise ValueError("min_altitude_m must be positive")
        for name in ("deadband_ex_cam", "deadband_ey_cam"):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if self.deadband_ex_cam > self.max_ex_cam:
            raise ValueError("deadband_ex_cam must be <= max_ex_cam")
        if self.deadband_ey_cam > self.max_ey_cam:
            raise ValueError("deadband_ey_cam must be <= max_ey_cam")
        if float(self.vx_sign) == 0.0:
            raise ValueError("vx_sign must be non-zero")
        if float(self.vy_sign) == 0.0:
            raise ValueError("vy_sign must be non-zero")
        if float(self.gain_low_altitude_m) <= 0.0:
            raise ValueError("gain_low_altitude_m must be positive")
        if float(self.gain_high_altitude_m) <= float(self.gain_low_altitude_m):
            raise ValueError("gain_high_altitude_m must be > gain_low_altitude_m")
        if float(self.gain_high_scale) <= 0.0 or float(self.gain_high_scale) > 1.0:
            raise ValueError("gain_high_scale must be > 0 and <= 1")
        # multi-point height gain validation
        if self.height_gain_mode not in ("linear", "points"):
            raise ValueError("height_gain_mode must be 'linear' or 'points'")
        if self.height_gain_mode == "points":
            if self.height_scale_points is None or not isinstance(self.height_scale_points, list):
                raise ValueError("height_scale_points must be a non-empty list when mode='points'")
            if len(self.height_scale_points) < 2:
                raise ValueError("height_scale_points must contain at least 2 points")
            altitudes: list[float] = []
            for i, point in enumerate(self.height_scale_points):
                if not isinstance(point, dict):
                    raise ValueError(f"height_scale_points[{i}] must be a dict")
                alt = float(point.get("altitude_m", float("nan")))
                scl = float(point.get("scale", float("nan")))
                if not math.isfinite(alt) or alt <= 0.0:
                    raise ValueError(f"height_scale_points[{i}].altitude_m must be finite and > 0")
                if not math.isfinite(scl) or scl <= 0.0 or scl > 1.5:
                    raise ValueError(f"height_scale_points[{i}].scale must be finite, > 0, <= 1.5")
                altitudes.append(alt)
            if len(set(altitudes)) != len(altitudes):
                raise ValueError("height_scale_points contains duplicate altitude_m values")
        # payload offset validation
        if float(self.fov_x_deg) <= 0.0 or float(self.fov_x_deg) >= 180.0:
            raise ValueError("fov_x_deg must be in (0, 180)")
        if float(self.fov_y_deg) <= 0.0 or float(self.fov_y_deg) >= 180.0:
            raise ValueError("fov_y_deg must be in (0, 180)")
        if float(self.image_x_sign) not in (1.0, -1.0):
            raise ValueError("image_x_sign must be 1.0 or -1.0")
        if float(self.image_y_sign) not in (1.0, -1.0):
            raise ValueError("image_y_sign must be 1.0 or -1.0")
        if float(self.max_payload_offset_ex_cam) <= 0.0 or float(self.max_payload_offset_ex_cam) > 1.5:
            raise ValueError("max_payload_offset_ex_cam must be > 0 and <= 1.5")
        if float(self.max_payload_offset_ey_cam) <= 0.0 or float(self.max_payload_offset_ey_cam) > 1.5:
            raise ValueError("max_payload_offset_ey_cam must be > 0 and <= 1.5")
        if not math.isfinite(float(self.payload_forward_m)):
            raise ValueError("payload_forward_m must be finite")
        if not math.isfinite(float(self.payload_right_m)):
            raise ValueError("payload_right_m must be finite")
        # descent gate policy validation
        if self.descent_gate_policy not in ("aligned_or_slow", "allow_unaligned"):
            raise ValueError("descent_gate_policy must be 'aligned_or_slow' or 'allow_unaligned'")
        if float(self.unaligned_descend_speed_mps) < 0.0:
            raise ValueError("unaligned_descend_speed_mps must be non-negative")
        if not math.isfinite(float(self.unaligned_descend_speed_mps)):
            raise ValueError("unaligned_descend_speed_mps must be finite")
        if (
            self.descent_gate_policy == "allow_unaligned"
            and float(self.unaligned_descend_speed_mps) > float(self.descend_speed_mps)
        ):
            raise ValueError("unaligned_descend_speed_mps must be <= descend_speed_mps")
        if self.yaw_control_mode not in ("hold", "ignore", "hold_zero_rate"):
            raise ValueError("yaw_control_mode must be 'hold', 'ignore', or 'hold_zero_rate'")
        if self.altitude_source not in ("auto", "relative_altitude", "local_ned"):
            raise ValueError("altitude_source must be 'auto', 'relative_altitude', or 'local_ned'")
        # descent speed stages validation
        if self.descent_speed_stages is not None:
            if not isinstance(self.descent_speed_stages, list):
                raise ValueError("descent_speed_stages must be a list or None")
            for i, stage in enumerate(self.descent_speed_stages):
                if not isinstance(stage, dict):
                    raise ValueError(f"descent_speed_stages[{i}] must be a dict")
                if isinstance(stage.get("max_altitude_m"), bool):
                    raise ValueError(
                        f"descent_speed_stages[{i}].max_altitude_m must not be boolean"
                    )
                if isinstance(stage.get("max_descend_speed_mps"), bool):
                    raise ValueError(
                        f"descent_speed_stages[{i}].max_descend_speed_mps must not be boolean"
                    )
                alt = float(stage.get("max_altitude_m", float("nan")))
                spd = float(stage.get("max_descend_speed_mps", float("nan")))
                if not math.isfinite(alt) or alt <= 0.0:
                    raise ValueError(f"descent_speed_stages[{i}].max_altitude_m must be finite and > 0, got {alt}")
                if not math.isfinite(spd) or spd < 0.0:
                    raise ValueError(f"descent_speed_stages[{i}].max_descend_speed_mps must be finite and >= 0, got {spd}")
        # target loss policy validation
        if self.target_loss_policy not in ("fail", "continue_descent"):
            raise ValueError("target_loss_policy must be 'fail' or 'continue_descent'")
        if float(self.target_loss_descend_speed_mps) < 0.0:
            raise ValueError("target_loss_descend_speed_mps must be non-negative")
        if not math.isfinite(float(self.target_loss_descend_speed_mps)):
            raise ValueError("target_loss_descend_speed_mps must be finite")
        for name in (
            "integral_active_below_altitude_m", "ki_vx", "ki_vy",
            "integral_vx_limit_mps", "integral_vy_limit_mps",
            "min_effective_speed_active_below_altitude_m", "min_effective_speed_mps",
            "min_effective_speed_ex_threshold", "min_effective_speed_ey_threshold",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if (isinstance(self.target_loss_grace_updates, bool) or not isinstance(self.target_loss_grace_updates, int) or self.target_loss_grace_updates < 0):
            raise ValueError("target_loss_grace_updates must be a non-negative integer")
        scale = float(self.target_loss_grace_horizontal_scale)
        if not math.isfinite(scale) or scale < 0.0 or scale > 1.0:
            raise ValueError("target_loss_grace_horizontal_scale must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class _AltitudeSample:
    value_m: float
    source: str


def _payload_offset_to_error_setpoint(
    altitude_m: float | None,
    config: AlignDescendConfig,
) -> tuple[float, float, dict[str, Any]]:
    """Convert payload physical offset (BODY frame) to desired camera error.

    Returns (desired_ex_cam, desired_ey_cam, detail).
    """
    base_detail: dict[str, Any] = {
        "payload_offset_enabled": bool(config.payload_offset_enabled),
        "payload_forward_m": config.payload_forward_m,
        "payload_right_m": config.payload_right_m,
        "fov_x_deg": config.fov_x_deg,
        "fov_y_deg": config.fov_y_deg,
        "image_x_sign": config.image_x_sign,
        "image_y_sign": config.image_y_sign,
    }

    if not config.payload_offset_enabled:
        return 0.0, 0.0, {**base_detail, "payload_offset_valid": False}

    if altitude_m is None:
        return 0.0, 0.0, {
            **base_detail,
            "payload_offset_valid": False,
            "payload_offset_reason": "missing_altitude",
        }

    try:
        alt = float(altitude_m)
    except (TypeError, ValueError):
        return 0.0, 0.0, {
            **base_detail,
            "payload_offset_valid": False,
            "payload_offset_reason": "invalid_altitude",
        }

    if not math.isfinite(alt) or alt <= 0.0:
        return 0.0, 0.0, {
            **base_detail,
            "payload_offset_valid": False,
            "payload_offset_reason": "altitude_not_positive",
        }

    half_fov_x = math.radians(config.fov_x_deg) / 2.0
    half_fov_y = math.radians(config.fov_y_deg) / 2.0

    # BODY frame: payload_right_m → affects ex, payload_forward_m → affects ey
    desired_ex = math.atan(
        config.payload_right_m / (config.image_x_sign * alt)
    ) / half_fov_x
    desired_ey = math.atan(
        config.payload_forward_m / (config.image_y_sign * alt)
    ) / half_fov_y

    desired_ex = _clamp(desired_ex, -config.max_payload_offset_ex_cam, config.max_payload_offset_ex_cam)
    desired_ey = _clamp(desired_ey, -config.max_payload_offset_ey_cam, config.max_payload_offset_ey_cam)

    return desired_ex, desired_ey, {
        **base_detail,
        "payload_offset_valid": True,
        "desired_ex_cam": desired_ex,
        "desired_ey_cam": desired_ey,
        "offset_altitude_m": alt,
    }


def _apply_descent_speed_stages(
    vz: float,
    altitude_m: float | None,
    config: AlignDescendConfig,
) -> dict | None:
    """Apply staged descent speed caps. Only limits vz > 0 (downward).
    Returns None when no stage is active (vz unchanged)."""
    if vz <= 0.0 or altitude_m is None:
        return None
    stages = config.descent_speed_stages
    if stages is None:
        return None
    try:
        height = float(altitude_m)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(height):
        return None
    cap = float("inf")
    active_max_altitude_m = None
    for stage in stages:
        try:
            max_alt = float(stage["max_altitude_m"])
            max_spd = float(stage["max_descend_speed_mps"])
        except (KeyError, TypeError, ValueError):
            continue
        if height <= max_alt and max_spd < cap:
            cap = max_spd
            active_max_altitude_m = max_alt
    if not math.isfinite(cap) or cap >= vz:
        return None
    capped_vz = min(vz, cap)
    return {
        "vz_cmd": capped_vz,
        "descent_speed_before_stage_mps": vz,
        "descent_speed_cap_mps": cap,
        "descent_speed_after_stage_mps": capped_vz,
        "descent_speed_stage_max_altitude_m": active_max_altitude_m,
        "descent_speed_stage_active": True,
    }



def compute_align_descend_command(
    inputs: dict[str, Any],
    config: AlignDescendConfig,
    altitude_m: float | None = None,
    integral_vx_mps: float = 0.0,
    integral_vy_mps: float = 0.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    control_allowed = bool(inputs.get("control_allowed", True))
    target_valid = bool(inputs.get("target_valid") or inputs.get("vision_valid"))
    target_locked = bool(inputs.get("target_locked", True))
    gain_scale = _height_gain_scale(altitude_m, config)
    kp_vx_eff = config.kp_vx * gain_scale
    kp_vy_eff = config.kp_vy * gain_scale
    if config.scale_max_velocity_with_height:
        max_vx_eff = config.max_vx_mps * gain_scale
        max_vy_eff = config.max_vy_mps * gain_scale
    else:
        max_vx_eff = config.max_vx_mps
        max_vy_eff = config.max_vy_mps

    reason = ""
    ex_cam = 0.0
    ey_cam = 0.0
    if not control_allowed:
        reason = "control_not_allowed"
    elif not target_valid:
        reason = "target_not_valid"
    elif config.require_target_locked and not target_locked:
        reason = "target_not_locked"
    else:
        try:
            ex_cam = float(inputs["ex_cam"])
            ey_cam = float(inputs["ey_cam"])
        except (KeyError, TypeError, ValueError):
            reason = "missing_error"
        else:
            if not math.isfinite(ex_cam) or not math.isfinite(ey_cam):
                reason = "invalid_error"

    enabled = reason == ""
    aligned = False
    vx = 0.0
    vy = 0.0
    vz = 0.0

    # compute payload offset desired setpoint
    desired_ex_cam, desired_ey_cam, offset_detail = _payload_offset_to_error_setpoint(
        altitude_m=altitude_m,
        config=config,
    )

    raw_ex_cam = ex_cam
    raw_ey_cam = ey_cam
    corrected_ex_cam = raw_ex_cam - desired_ex_cam
    corrected_ey_cam = raw_ey_cam - desired_ey_cam

    if enabled:
        aligned = abs(corrected_ex_cam) <= config.max_ex_cam and abs(corrected_ey_cam) <= config.max_ey_cam
        slow_descend_aligned = _slow_descend_aligned(corrected_ex_cam, corrected_ey_cam, config)
        ex_for_control = 0.0 if abs(corrected_ex_cam) <= config.deadband_ex_cam else corrected_ex_cam
        ey_for_control = 0.0 if abs(corrected_ey_cam) <= config.deadband_ey_cam else corrected_ey_cam
        p_vx = _clamp(config.vx_sign * kp_vx_eff * ey_for_control, -max_vx_eff, max_vx_eff)
        p_vy = _clamp(config.vy_sign * kp_vy_eff * ex_for_control, -max_vy_eff, max_vy_eff)
        combined_vx = p_vx + integral_vx_mps
        combined_vy = p_vy + integral_vy_mps
        vx = _clamp(combined_vx, -max_vx_eff, max_vx_eff)
        vy = _clamp(combined_vy, -max_vy_eff, max_vy_eff)
        min_speed_active = (
            config.min_effective_speed_enabled
            and altitude_m is not None
            and altitude_m <= config.min_effective_speed_active_below_altitude_m
        )
        min_speed_applied_vx = False
        min_speed_applied_vy = False
        if min_speed_active and abs(corrected_ey_cam) >= config.min_effective_speed_ey_threshold and 0.0 < abs(vx) < config.min_effective_speed_mps:
            vx = _clamp(math.copysign(config.min_effective_speed_mps, vx), -max_vx_eff, max_vx_eff)
            min_speed_applied_vx = True
        if min_speed_active and abs(corrected_ex_cam) >= config.min_effective_speed_ex_threshold and 0.0 < abs(vy) < config.min_effective_speed_mps:
            vy = _clamp(math.copysign(config.min_effective_speed_mps, vy), -max_vy_eff, max_vy_eff)
            min_speed_applied_vy = True
        if aligned:
            vz = config.descend_speed_mps
            reason = "descending"
        elif slow_descend_aligned:
            vz = config.slow_descend_speed_mps
            reason = "descending_slow"
        elif config.descent_gate_policy == "allow_unaligned" and config.unaligned_descend_speed_mps > 0.0:
            vz = config.unaligned_descend_speed_mps
            reason = "descending_unaligned"
        else:
            vz = 0.0
            reason = "aligning"

    command = _command_dict(
        vx=vx,
        vy=vy,
        vz=vz,
        enabled=enabled,
    )
    # apply staged descent speed caps (only limits vz > 0)
    stage_detail = _apply_descent_speed_stages(vz, altitude_m, config)
    if stage_detail is not None:
        command["vz_cmd"] = stage_detail["vz_cmd"]
    detail = {
        "enabled": enabled,
        "aligned": aligned,
        "slow_descending": bool(enabled and not aligned and vz > 0.0),
        "hold_reason": reason,
        "ex_cam": corrected_ex_cam,
        "ey_cam": corrected_ey_cam,
        "raw_ex_cam": raw_ex_cam,
        "raw_ey_cam": raw_ey_cam,
        "desired_ex_cam": desired_ex_cam,
        "desired_ey_cam": desired_ey_cam,
        "corrected_ex_cam": corrected_ex_cam,
        "corrected_ey_cam": corrected_ey_cam,
        "height_gain_scale": gain_scale,
        "height_gain_mode": config.height_gain_mode,
        "height_gain_points_active": bool(
            config.height_gain_enabled and config.height_gain_mode == "points"
        ),
        "kp_vx_eff": kp_vx_eff,
        "kp_vy_eff": kp_vy_eff,
        "max_vx_eff": max_vx_eff,
        "max_vy_eff": max_vy_eff,
        "p_vx_mps": p_vx if enabled else 0.0,
        "p_vy_mps": p_vy if enabled else 0.0,
        "integral_vx_mps": integral_vx_mps if enabled else 0.0,
        "integral_vy_mps": integral_vy_mps if enabled else 0.0,
        "combined_vx_before_clamp_mps": combined_vx if enabled else 0.0,
        "combined_vy_before_clamp_mps": combined_vy if enabled else 0.0,
        "min_effective_speed_enabled": bool(config.min_effective_speed_enabled),
        "min_effective_speed_active": min_speed_active if enabled else False,
        "min_effective_speed_applied_vx": min_speed_applied_vx if enabled else False,
        "min_effective_speed_applied_vy": min_speed_applied_vy if enabled else False,
        "min_effective_speed_mps": config.min_effective_speed_mps,
        "descent_speed_before_stage_mps": stage_detail["descent_speed_before_stage_mps"] if stage_detail is not None else (vz if vz > 0 else 0.0),
        "descent_speed_cap_mps": stage_detail["descent_speed_cap_mps"] if stage_detail is not None else None,
        "descent_speed_after_stage_mps": stage_detail["descent_speed_after_stage_mps"] if stage_detail is not None else vz,
        "descent_speed_stage_max_altitude_m": stage_detail["descent_speed_stage_max_altitude_m"] if stage_detail is not None else None,
        "descent_speed_stage_active": stage_detail["descent_speed_stage_active"] if stage_detail is not None else False,
        **offset_detail,
    }
    return command, detail


def _command_dict(*, vx: float, vy: float, vz: float, enabled: bool) -> dict[str, Any]:
    return {
        "type": "flight_command",
        "vx_cmd": float(vx),
        "vy_cmd": float(vy),
        "vz_cmd": float(vz),
        "yaw_rate_cmd": 0.0,
        "gimbal_yaw_rate_cmd": 0.0,
        "gimbal_pitch_rate_cmd": 0.0,
        "gimbal_yaw_angle_cmd": None,
        "gimbal_pitch_angle_cmd": None,
        "enable_body": bool(enabled),
        "enable_gimbal": False,
        "enable_gimbal_angle": False,
        "enable_approach": bool(enabled),
        "active": bool(enabled),
        "valid": True,
    }


def _inactive_command() -> dict[str, Any]:
    command = _command_dict(vx=0.0, vy=0.0, vz=0.0, enabled=False)
    command["enable_body"] = True
    command["enable_approach"] = False
    command["active"] = False
    command["valid"] = True
    return command


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _height_gain_scale(altitude_m: float | None, config: AlignDescendConfig) -> float:
    if not config.height_gain_enabled or altitude_m is None:
        return 1.0
    try:
        height = float(altitude_m)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(height):
        return 1.0

    if config.height_gain_mode == "points" and config.height_scale_points:
        return _height_gain_scale_points(height, config)
    return _height_gain_scale_linear(height, config)


def _height_gain_scale_linear(height: float, config: AlignDescendConfig) -> float:
    low = float(config.gain_low_altitude_m)
    high = float(config.gain_high_altitude_m)
    high_scale = float(config.gain_high_scale)

    if height <= low:
        return 1.0
    if height >= high:
        return high_scale

    t = (height - low) / (high - low)
    return 1.0 + t * (high_scale - 1.0)


def _height_gain_scale_points(height_m: float, config: AlignDescendConfig) -> float:
    points = sorted(config.height_scale_points or [], key=lambda p: float(p["altitude_m"]))
    if height_m <= points[0]["altitude_m"]:
        return float(points[0]["scale"])
    if height_m >= points[-1]["altitude_m"]:
        return float(points[-1]["scale"])
    for i in range(len(points) - 1):
        lower = points[i]
        upper = points[i + 1]
        lower_alt = float(lower["altitude_m"])
        upper_alt = float(upper["altitude_m"])
        if lower_alt <= height_m <= upper_alt:
            t = (height_m - lower_alt) / (upper_alt - lower_alt)
            lower_scale = float(lower["scale"])
            upper_scale = float(upper["scale"])
            return lower_scale + t * (upper_scale - lower_scale)
    return 1.0


def _slow_descend_aligned(ex_cam: float, ey_cam: float, config: AlignDescendConfig) -> bool:
    if config.slow_descend_speed_mps <= 0.0:
        return False
    max_ex = config.slow_descend_max_ex_cam
    max_ey = config.slow_descend_max_ey_cam
    if max_ex is None or max_ey is None:
        return False
    return abs(ex_cam) <= max_ex and abs(ey_cam) <= max_ey
