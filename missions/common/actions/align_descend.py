from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .base import ActionModule
from .result import ActionResult


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
        vx = _clamp(
            config.vx_sign * kp_vx_eff * ey_for_control,
            -max_vx_eff,
            max_vx_eff,
        )
        vy = _clamp(
            config.vy_sign * kp_vy_eff * ex_for_control,
            -max_vy_eff,
            max_vy_eff,
        )
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
        "descent_speed_before_stage_mps": stage_detail["descent_speed_before_stage_mps"] if stage_detail is not None else (vz if vz > 0 else 0.0),
        "descent_speed_cap_mps": stage_detail["descent_speed_cap_mps"] if stage_detail is not None else None,
        "descent_speed_after_stage_mps": stage_detail["descent_speed_after_stage_mps"] if stage_detail is not None else vz,
        "descent_speed_stage_max_altitude_m": stage_detail["descent_speed_stage_max_altitude_m"] if stage_detail is not None else None,
        "descent_speed_stage_active": stage_detail["descent_speed_stage_active"] if stage_detail is not None else False,
        **offset_detail,
    }
    return command, detail


class AlignDescendAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        config_data = dict(data.get("config") or {})
        if "kp_x" in config_data and "kp_vx" not in config_data:
            config_data["kp_vx"] = config_data.pop("kp_x")
        if "kp_y" in config_data and "kp_vy" not in config_data:
            config_data["kp_vy"] = config_data.pop("kp_y")
        if "min_altitude_m" in data and "min_altitude_m" not in config_data:
            config_data["min_altitude_m"] = data["min_altitude_m"]
        self.config = AlignDescendConfig(**config_data)

        expected_dt_s = float(data.get("expected_dt_s", 0.1))
        if expected_dt_s <= 0.0:
            raise ValueError("expected_dt_s must be positive")

        self.lost_timeout_updates = self._updates_from_seconds_or_count(
            data=data,
            seconds_name="lost_timeout_s",
            count_name="lost_timeout_updates",
            default_count=5,
            expected_dt_s=expected_dt_s,
        )
        self.hold_updates_required = self._updates_from_seconds_or_count(
            data=data,
            seconds_name="hold_time_s",
            count_name="hold_updates_required",
            default_count=3,
            expected_dt_s=expected_dt_s,
        )
        self.max_retries = int(data.get("max_retries", 1))
        self.max_updates = int(data.get("max_updates", 300))
        if self.lost_timeout_updates < 1:
            raise ValueError("lost_timeout_updates must be at least 1")
        if self.hold_updates_required < 1:
            raise ValueError("hold_updates_required must be at least 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.max_updates < 1:
            raise ValueError("max_updates must be at least 1")

        self.finish_altitude_m = self._finish_altitude(data)
        if self.finish_altitude_m is not None and self.finish_altitude_m < self.config.min_altitude_m:
            self.finish_altitude_m = self.config.min_altitude_m
        self.finish_policy = str(data.get("finish_policy", "legacy")).strip().lower()
        if self.finish_policy not in ("legacy", "require_alignment_or_timeout", "latched_center_alignment"):
            raise ValueError("finish_policy must be 'legacy', 'require_alignment_or_timeout', or 'latched_center_alignment'")

        # ── latched_center_alignment params ──
        self.finish_alignment_max_ex_cam = float(data.get("finish_alignment_max_ex_cam", 0.20))
        self.finish_alignment_max_ey_cam = float(data.get("finish_alignment_max_ey_cam", 0.20))
        raw_hold_updates = data.get("finish_alignment_hold_updates", 2)
        if (
            isinstance(raw_hold_updates, bool)
            or not isinstance(raw_hold_updates, int)
            or raw_hold_updates < 1
        ):
            raise ValueError("finish_alignment_hold_updates must be an integer >= 1")
        self.finish_alignment_hold_updates = raw_hold_updates

        # Validate latched_center_alignment params
        if not math.isfinite(self.finish_alignment_max_ex_cam) or self.finish_alignment_max_ex_cam <= 0.0:
            raise ValueError("finish_alignment_max_ex_cam must be finite and > 0")
        if not math.isfinite(self.finish_alignment_max_ey_cam) or self.finish_alignment_max_ey_cam <= 0.0:
            raise ValueError("finish_alignment_max_ey_cam must be finite and > 0")

        self.final_align_started = False
        self.finish_alignment_hold_count = 0

        self.yaw_hold_rad = None
        self.yaw_hold_source = None
        self.started = True
        self.stopped = False
        self.done = False
        self.failed = False
        self.update_count = 0
        self.lost_updates = 0
        self.hold_updates = 0
        self.retries = 0
        self.failure_reason = ""
        self.last_detail = self._detail(
            command=_inactive_command(),
            command_detail={"enabled": False, "aligned": False, "hold_reason": "started"},
            height_m=None,
        )

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started", actions=[])
        if self.stopped:
            return ActionResult(
                actions=[],
                done=True,
                reason="stopped",
                detail=self._detail(
                    command=_inactive_command(),
                    command_detail={"enabled": False, "aligned": False, "hold_reason": "stopped"},
                    height_m=None,
                ),
            )
        if self.done:
            return ActionResult(actions=[], done=True, reason="align_descend_done", detail=self.last_detail)
        if self.failed:
            return ActionResult(
                actions=[],
                failed=True,
                reason=self.failure_reason or "align_descend_failed",
                detail=self._failed_detail(),
            )

        self.update_count += 1
        if self.update_count > self.max_updates:
            self.failed = True
            self.failure_reason = "align_descend_timeout"
            return ActionResult(
                actions=[],
                failed=True,
                reason="align_descend_timeout",
                detail=self._failed_detail("align_descend_timeout"),
            )

        data = context or {}
        self.latest_context = data
        self._ensure_yaw_hold(data)
        inputs = self._inputs(data)
        altitude = self._current_altitude(data)
        if altitude is None:
            self.failed = True
            self.failure_reason = "missing_local_ned_altitude" if self.config.altitude_source == "local_ned" else "missing_altitude"
            detail = self._failed_detail(self.failure_reason, height_m=None, altitude_source="")
            self.last_detail = detail
            return ActionResult(
                actions=[],
                failed=True,
                reason=self.failure_reason,
                detail=detail,
            )

        command, command_detail = compute_align_descend_command(
            inputs,
            self.config,
            altitude_m=altitude.value_m,
        )
        target_ok = command_detail["enabled"] is True

        if target_ok:
            self.lost_updates = 0
        else:
            self.lost_updates += 1
            self.hold_updates = 0
            if self.lost_updates > self.lost_timeout_updates:
                if self.retries < self.max_retries:
                    self.retries += 1
                    self.lost_updates = 0
                    detail = self._detail(
                        command=_inactive_command(),
                        command_detail={**command_detail, "hold_reason": "align_retry"},
                        height_m=altitude.value_m,
                        altitude_source=altitude.source,
                    )
                    self.last_detail = detail
                    return ActionResult(actions=[], reason="align_retry", detail=detail)
                self.failed = True
                self.failure_reason = "target_lost_timeout"
                return ActionResult(
                    actions=[],
                    failed=True,
                    reason="target_lost_timeout",
                    detail=self._failed_detail(
                        "target_lost_timeout",
                        height_m=altitude.value_m,
                        altitude_source=altitude.source,
                    ),
                )

        if target_ok and command_detail["aligned"] is True:
            self.hold_updates += 1
        elif target_ok:
            self.hold_updates = 0

        # ── latched_center_alignment policy ──────────────────────────
        if self.finish_policy == "latched_center_alignment" and self.finish_altitude_m is not None:
            if not self.final_align_started and altitude.value_m <= self.finish_altitude_m:
                self.final_align_started = True
                self.finish_alignment_hold_count = 0

            if self.final_align_started:
                # Continue vx/vy from visual error, but stop descent
                if isinstance(command, dict):
                    command["vz_cmd"] = 0.0

                if not target_ok:
                    # Target invalid: clear hold count, do NOT complete.
                    # Rely on existing lost_updates / retry / target_lost_timeout below.
                    self.finish_alignment_hold_count = 0
                else:
                    # Target valid: check payload-offset-compensated errors ONLY
                    corrected_ex = command_detail.get("corrected_ex_cam")
                    corrected_ey = command_detail.get("corrected_ey_cam")
                    in_center = (
                        corrected_ex is not None
                        and corrected_ey is not None
                        and math.isfinite(corrected_ex)
                        and math.isfinite(corrected_ey)
                        and abs(corrected_ex) <= self.finish_alignment_max_ex_cam
                        and abs(corrected_ey) <= self.finish_alignment_max_ey_cam
                    )

                    if in_center:
                        self.finish_alignment_hold_count += 1
                    else:
                        self.finish_alignment_hold_count = 0

                    if self.finish_alignment_hold_count >= self.finish_alignment_hold_updates:
                        self.done = True
                        detail = self._detail(
                            command=self._command_with_yaw_hold(_inactive_command(), data),
                            command_detail={
                                **command_detail,
                                "hold_reason": "latched_center_aligned",
                            },
                            height_m=altitude.value_m,
                            altitude_source=altitude.source,
                        )
                        self.last_detail = detail
                        return ActionResult(
                            actions=[],
                            done=True,
                            reason="latched_center_aligned",
                            detail=detail,
                        )

                detail = self._detail(
                    command=self._command_with_yaw_hold(command, data),
                    command_detail={
                        **command_detail,
                        "hold_reason": "aligning_at_finish_altitude",
                    },
                    height_m=altitude.value_m,
                    altitude_source=altitude.source,
                )
                self.last_detail = detail
                return ActionResult(
                    actions=[],
                    reason="aligning_at_finish_altitude",
                    detail=detail,
                )

        # Strict mode: check finish_altitude BEFORE min_altitude
        if self.finish_policy == "require_alignment_or_timeout" and self.finish_altitude_m is not None and altitude.value_m <= self.finish_altitude_m:
            if target_ok and command_detail["aligned"] is True and self.hold_updates >= self.hold_updates_required:
                self.done = True
                detail = self._detail(
                    command=self._command_with_yaw_hold(_inactive_command(), data),
                    command_detail={**command_detail, "hold_reason": "aligned_at_finish_altitude"},
                    height_m=altitude.value_m,
                    altitude_source=altitude.source,
                )
                self.last_detail = detail
                return ActionResult(actions=[], done=True, reason="aligned_at_finish_altitude", detail=detail)
            # Not aligned yet — continue with vz=0, vx/vy still active
            command, command_detail = compute_align_descend_command(
                inputs, self.config, altitude_m=altitude.value_m,
            )
            if isinstance(command, dict):
                command["vz_cmd"] = 0.0
            detail = self._detail(
                command=self._command_with_yaw_hold(command, data),
                command_detail={**command_detail, "hold_reason": "aligning_at_finish_altitude"},
                height_m=altitude.value_m,
                altitude_source=altitude.source,
            )
            self.last_detail = detail
            return ActionResult(actions=[], reason="aligning_at_finish_altitude", detail=detail)

        if altitude.value_m <= self.config.min_altitude_m:
            if self.finish_policy == "require_alignment_or_timeout":
                # Strict: don't set done, continue with vz=0
                command, command_detail = compute_align_descend_command(
                    inputs, self.config, altitude_m=altitude.value_m,
                )
                if isinstance(command, dict):
                    command["vz_cmd"] = 0.0
                detail = self._detail(
                    command=self._command_with_yaw_hold(command, data),
                    command_detail={**command_detail, "hold_reason": "aligning_at_finish_altitude"},
                    height_m=altitude.value_m,
                    altitude_source=altitude.source,
                )
                self.last_detail = detail
                return ActionResult(actions=[], reason="aligning_at_finish_altitude", detail=detail)
            self.done = True
            detail = self._detail(
                command=self._command_with_yaw_hold(_inactive_command(), data),
                command_detail={**command_detail, "hold_reason": "min_altitude_reached"},
                height_m=altitude.value_m,
                altitude_source=altitude.source,
            )
            self.last_detail = detail
            return ActionResult(actions=[], done=True, reason="min_altitude_reached", detail=detail)

        if self.finish_altitude_m is not None and altitude.value_m <= self.finish_altitude_m and self.finish_policy != "require_alignment_or_timeout":
            if (
                self.finish_policy == "require_alignment_or_timeout"
                and target_ok
                and command_detail["aligned"] is True
                and self.hold_updates >= self.hold_updates_required
            ):
                self.done = True
                detail = self._detail(
                    command=self._command_with_yaw_hold(_inactive_command(), data),
                    command_detail={**command_detail, "hold_reason": "aligned_at_finish_altitude"},
                    height_m=altitude.value_m,
                    altitude_source=altitude.source,
                )
                self.last_detail = detail
                return ActionResult(actions=[], done=True, reason="aligned_at_finish_altitude", detail=detail)
            if self.finish_policy == "require_alignment_or_timeout":
                # Not aligned yet — continue with vz=0, vx/vy still active
                command, command_detail = compute_align_descend_command(
                    inputs, self.config, altitude_m=altitude.value_m,
                )
                if isinstance(command, dict):
                    command["vz_cmd"] = 0.0
                detail = self._detail(
                    command=self._command_with_yaw_hold(command, data),
                    command_detail={**command_detail, "hold_reason": "aligning_at_finish_altitude"},
                    height_m=altitude.value_m,
                    altitude_source=altitude.source,
                )
                self.last_detail = detail
                return ActionResult(actions=[], reason="aligning_at_finish_altitude", detail=detail)
            self.done = True
            done_reason = (
                "aligned_at_finish_altitude"
                if target_ok
                and command_detail["aligned"] is True
                and self.hold_updates >= self.hold_updates_required
                else "finish_altitude_reached"
            )
            detail = self._detail(
                command=self._command_with_yaw_hold(_inactive_command(), data),
                command_detail={**command_detail, "hold_reason": done_reason},
                height_m=altitude.value_m,
                altitude_source=altitude.source,
            )
            self.last_detail = detail
            return ActionResult(actions=[], done=True, reason=done_reason, detail=detail)

        reason = "align_descending" if target_ok and command_detail["aligned"] else command_detail["hold_reason"]
        command = self._command_with_yaw_hold(command, data)
        detail = self._detail(
            command=command,
            command_detail={**command_detail, "hold_reason": reason},
            height_m=altitude.value_m,
            altitude_source=altitude.source,
        )
        self.last_detail = detail
        return ActionResult(actions=[], reason=reason, detail=detail)

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.config = AlignDescendConfig()
        self.lost_timeout_updates = 5
        self.hold_updates_required = 3
        self.max_retries = 1
        self.max_updates = 300
        self.finish_altitude_m: float | None = None
        self.started = False
        self.stopped = False
        self.done = False
        self.failed = False
        self.update_count = 0
        self.lost_updates = 0
        self.hold_updates = 0
        self.retries = 0
        self.failure_reason = ""
        self.final_align_started = False
        self.finish_alignment_hold_count = 0
        self.yaw_hold_rad: float | None = None
        self.yaw_hold_source: str | None = None
        self.latest_context: dict[str, Any] = {}
        self.last_detail: dict[str, Any] = {}

    def _ensure_yaw_hold(self, context: dict[str, Any]) -> None:
        if self.config.yaw_control_mode in ("ignore", "hold_zero_rate"):
            self.yaw_hold_rad = None
            self.yaw_hold_source = None
            return
        if self.yaw_hold_rad is not None:
            return
        yaw, source = self._current_yaw_rad(context)
        self.yaw_hold_rad = yaw
        self.yaw_hold_source = source

    def _command_with_yaw_hold(self, command: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.config.yaw_control_mode == "ignore":
            result = dict(command)
            result.pop("yaw_hold_rad", None)
            result.pop("velocity_yaw_rad", None)
            return result
        if self.config.yaw_control_mode == "hold_zero_rate":
            result = dict(command)
            result.pop("yaw_hold_rad", None)
            result.pop("velocity_yaw_rad", None)
            result["yaw_rate_rad_s"] = 0.0
            return result
        if self.yaw_hold_rad is None:
            return command
        result = {**command, "yaw_hold_rad": self.yaw_hold_rad}
        if context is not None:
            velocity_yaw_rad = self._current_valid_attitude_yaw_rad(context)
            if velocity_yaw_rad is not None:
                result["velocity_yaw_rad"] = velocity_yaw_rad
        return result

    def _current_yaw_rad(self, context: dict[str, Any]) -> tuple[float | None, str | None]:
        value = self._float_from(context, "field_heading_yaw_rad")
        if value is not None:
            return self._normalize_yaw(value), "field_heading"

        value = self._float_from(context, "arm_heading_yaw_rad")
        if value is not None:
            return self._normalize_yaw(value), "arm_heading"

        value = self._current_valid_attitude_yaw_rad(context)
        if value is not None:
            return value, "attitude"

        value = self._float_from(context, "yaw")
        if value is not None:
            return self._normalize_yaw(value), "yaw"
        return None, None

    def _current_valid_attitude_yaw_rad(self, context: dict[str, Any]) -> float | None:
        for section_name in ("drone", "vehicle"):
            section = context.get(section_name)
            if not isinstance(section, dict):
                continue
            if not bool(section.get("attitude_valid", False)):
                continue
            value = self._float_from(section, "yaw")
            if value is not None:
                return self._normalize_yaw(value)
        return None

    @staticmethod
    def _normalize_yaw(yaw: float) -> float:
        return math.atan2(math.sin(yaw), math.cos(yaw))

    def _inputs(self, context: dict[str, Any]) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for key in (
            "target_valid",
            "vision_valid",
            "target_locked",
            "control_allowed",
            "ex_cam",
            "ey_cam",
            "ex",
            "ey",
            "tracking_state",
        ):
            if key in context:
                inputs[key] = context[key]

        for section_name in ("perception", "target"):
            section = context.get(section_name)
            if isinstance(section, dict):
                inputs.update(section)

        if "ex_cam" not in inputs and "ex" in inputs:
            inputs["ex_cam"] = inputs["ex"]
        if "ey_cam" not in inputs and "ey" in inputs:
            inputs["ey_cam"] = inputs["ey"]
        if "target_locked" not in inputs and str(inputs.get("tracking_state", "")).lower() == "locked":
            inputs["target_locked"] = True
        return inputs

    def _current_altitude_m(self, context: dict[str, Any]) -> float | None:
        altitude = self._current_altitude(context)
        return None if altitude is None else altitude.value_m

    def _current_altitude(self, context: dict[str, Any]) -> _AltitudeSample | None:
        if self.config.altitude_source == "local_ned":
            return self._local_ned_altitude(context)
        if self.config.altitude_source == "relative_altitude":
            return self._relative_altitude(context)
        return self._auto_altitude(context)

    def _auto_altitude(self, context: dict[str, Any]) -> _AltitudeSample | None:
        for name in ("relative_altitude", "relative_altitude_m"):
            value = self._float_from(context, name)
            if value is not None:
                return _AltitudeSample(max(0.0, value), name)

        value = self._float_from(context, "altitude_m")
        if value is not None:
            return _AltitudeSample(max(0.0, value), "altitude_m")

        altitude = self._negative_local_z(context, "local_z")
        if altitude is not None:
            return altitude

        local_position = context.get("local_position")
        if isinstance(local_position, dict):
            altitude = self._negative_local_z(local_position, "local_position.local_z")
            if altitude is not None:
                return altitude

        drone = context.get("drone")
        if isinstance(drone, dict):
            for name in ("relative_altitude", "relative_altitude_m"):
                value = self._float_from(drone, name)
                if value is not None:
                    return _AltitudeSample(max(0.0, value), f"drone.{name}")
            altitude = self._negative_local_z(drone, "drone.local_z")
            if altitude is not None:
                return altitude
            local_position = drone.get("local_position")
            if isinstance(local_position, dict):
                altitude = self._negative_local_z(local_position, "drone.local_position.local_z")
                if altitude is not None:
                    return altitude

        vehicle = context.get("vehicle")
        if isinstance(vehicle, dict):
            for name in ("relative_altitude", "relative_altitude_m"):
                value = self._float_from(vehicle, name)
                if value is not None:
                    return _AltitudeSample(max(0.0, value), f"vehicle.{name}")
            altitude = self._negative_local_z(vehicle, "vehicle.local_z")
            if altitude is not None:
                return altitude

        value = self._float_from(context, "altitude")
        if value is not None:
            return _AltitudeSample(max(0.0, value), "altitude")
        return None

    def _relative_altitude(self, context: dict[str, Any]) -> _AltitudeSample | None:
        for source, prefix in ((context, ""), (context.get("drone"), "drone."), (context.get("vehicle"), "vehicle.")):
            if not isinstance(source, dict):
                continue
            for name in ("relative_altitude", "relative_altitude_m"):
                value = self._float_from(source, name)
                if value is not None:
                    return _AltitudeSample(max(0.0, value), f"{prefix}{name}")
        return None

    def _local_ned_altitude(self, context: dict[str, Any]) -> _AltitudeSample | None:
        value = self._float_from(context, "local_altitude_m")
        if bool(context.get("local_altitude_valid")) and value is not None and value >= 0.0:
            return _AltitudeSample(value, "local_position_ned_z")
        if bool(context.get("local_position_valid")):
            altitude = self._negative_local_z(context, "local_z")
            if altitude is not None:
                return altitude
        local_position = context.get("local_position")
        if isinstance(local_position, dict) and bool(context.get("local_position_valid")):
            altitude = self._negative_local_z(local_position, "local_position.z")
            if altitude is not None:
                return altitude
        drone = context.get("drone")
        if isinstance(drone, dict) and bool(drone.get("local_position_valid")):
            altitude = self._negative_local_z(drone, "drone.local_z")
            if altitude is not None:
                return altitude
        return None

    def _negative_local_z(self, source: dict[str, Any], source_name: str) -> _AltitudeSample | None:
        local_z = self._float_from(source, "local_z")
        if local_z is None:
            local_z = self._float_from(source, "z")
        if local_z is not None and local_z < 0.0:
            return _AltitudeSample(max(0.0, -local_z), source_name)
        return None

    def _detail(
        self,
        *,
        command: dict[str, Any],
        command_detail: dict[str, Any],
        height_m: float | None,
        altitude_source: str = "",
    ) -> dict[str, Any]:
        reached_finish_altitude = (
            height_m is not None
            and self.finish_altitude_m is not None
            and height_m <= self.finish_altitude_m
        )
        latest_context = self.latest_context
        local_altitude = self._local_ned_altitude(latest_context)
        relative_altitude = self._relative_altitude(latest_context)
        return {
            "command": command,
            "enabled": bool(command_detail.get("enabled", False)),
            "aligned": bool(command_detail.get("aligned", False)),
            "slow_descending": bool(command_detail.get("slow_descending", False)),
            "hold_reason": str(command_detail.get("hold_reason", "")),
            "height_m": height_m,
            "current_altitude_m": height_m,
            "finish_altitude_m": self.finish_altitude_m,
            "min_altitude_m": self.config.min_altitude_m,
            "altitude_source": altitude_source,
            "altitude_source_requested": self.config.altitude_source,
            "local_altitude_m": None if local_altitude is None else local_altitude.value_m,
            "relative_altitude_m": None if relative_altitude is None else relative_altitude.value_m,
            "altitude_difference_m": None if local_altitude is None or relative_altitude is None else relative_altitude.value_m - local_altitude.value_m,
            "local_altitude_valid": local_altitude is not None,
            "ex_cam": command_detail.get("ex_cam"),
            "ey_cam": command_detail.get("ey_cam"),
            "raw_ex_cam": command_detail.get("raw_ex_cam"),
            "raw_ey_cam": command_detail.get("raw_ey_cam"),
            "desired_ex_cam": command_detail.get("desired_ex_cam"),
            "desired_ey_cam": command_detail.get("desired_ey_cam"),
            "corrected_ex_cam": command_detail.get("corrected_ex_cam"),
            "corrected_ey_cam": command_detail.get("corrected_ey_cam"),
            "payload_offset_enabled": command_detail.get("payload_offset_enabled"),
            "payload_offset_valid": command_detail.get("payload_offset_valid"),
            "payload_forward_m": command_detail.get("payload_forward_m"),
            "payload_right_m": command_detail.get("payload_right_m"),
            "offset_altitude_m": command_detail.get("offset_altitude_m"),
            "height_gain_scale": command_detail.get("height_gain_scale"),
            "kp_vx_eff": command_detail.get("kp_vx_eff"),
            "kp_vy_eff": command_detail.get("kp_vy_eff"),
            "max_vx_eff": command_detail.get("max_vx_eff"),
            "max_vy_eff": command_detail.get("max_vy_eff"),
            "yaw_hold_rad": self.yaw_hold_rad,
            "yaw_hold_source": self.yaw_hold_source,
            "yaw_hold_active": self.yaw_hold_rad is not None,
            "field_heading_yaw_rad": self._float_from(latest_context, "field_heading_yaw_rad"),
            "field_heading_confirmed": bool(latest_context.get("field_heading_confirmed", False)),
            "field_heading_source": str(latest_context.get("field_heading_source") or ""),
            "reached_finish_altitude": bool(reached_finish_altitude),
            "lost_updates": int(self.lost_updates),
            "hold_updates": int(self.hold_updates),
            "retries": int(self.retries),
            "update_count": int(self.update_count),
            "finish_policy": self.finish_policy,
            "final_align_started": getattr(self, "final_align_started", False),
            "finish_alignment_hold_count": getattr(self, "finish_alignment_hold_count", 0),
        }

    def _failed_detail(
        self,
        reason: str | None = None,
        *,
        height_m: float | None = None,
        altitude_source: str = "",
    ) -> dict[str, Any]:
        return self._detail(
            command=_inactive_command(),
            command_detail={
                "enabled": False,
                "aligned": False,
                "hold_reason": reason or self.failure_reason or "align_descend_failed",
            },
            height_m=height_m,
            altitude_source=altitude_source,
        )

    @staticmethod
    def _updates_from_seconds_or_count(
        *,
        data: dict[str, Any],
        seconds_name: str,
        count_name: str,
        default_count: int,
        expected_dt_s: float,
    ) -> int:
        if data.get(seconds_name) is not None:
            seconds = float(data[seconds_name])
            return int(math.ceil(seconds / expected_dt_s))
        return int(data.get(count_name, default_count))

    @staticmethod
    def _finish_altitude(data: dict[str, Any]) -> float | None:
        values = []
        for name in ("finish_altitude_m", "min_altitude_m"):
            if data.get(name) is None:
                continue
            value = float(data[name])
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
            values.append(value)
        if not values:
            return None
        return max(values)

    @staticmethod
    def _first_float(candidates: list[dict[str, Any]], name: str) -> float | None:
        for item in candidates:
            if name not in item:
                continue
            try:
                value = float(item[name])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                return value
        return None

    @staticmethod
    def _float_from(item: dict[str, Any], name: str) -> float | None:
        if name not in item:
            return None
        try:
            value = float(item[name])
        except (TypeError, ValueError):
            return None
        if math.isfinite(value):
            return value
        return None


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
