from __future__ import annotations

import math
import time
from typing import Any

from guidance.align_descend import (
    AlignDescendConfig,
    _AltitudeSample,
    _apply_descent_speed_stages,
    _clamp,
    _command_dict,
    _height_gain_scale,
    _inactive_command,
    compute_align_descend_command,
)
from missions.common.actions.result import ActionResult

class AlignDescendLifecycle:
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
        raw_finish_timeout_s = data.get("finish_alignment_timeout_s")
        self.finish_alignment_timeout_s: float | None = None
        if raw_finish_timeout_s is not None:
            self.finish_alignment_timeout_s = float(raw_finish_timeout_s)
            if (
                not math.isfinite(self.finish_alignment_timeout_s)
                or self.finish_alignment_timeout_s <= 0.0
            ):
                raise ValueError("finish_alignment_timeout_s must be finite and > 0")

        # Validate latched_center_alignment params
        if not math.isfinite(self.finish_alignment_max_ex_cam) or self.finish_alignment_max_ex_cam <= 0.0:
            raise ValueError("finish_alignment_max_ex_cam must be finite and > 0")
        if not math.isfinite(self.finish_alignment_max_ey_cam) or self.finish_alignment_max_ey_cam <= 0.0:
            raise ValueError("finish_alignment_max_ey_cam must be finite and > 0")

        self.final_align_started = False
        self.final_align_started_monotonic_s: float | None = None
        self.finish_alignment_elapsed_s = 0.0
        self.finish_alignment_hold_count = 0
        self._reset_integral("start")
        self._previous_update_monotonic_s = None
        self._last_valid_vx = 0.0
        self._last_valid_vy = 0.0

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
            return ActionResult(failed=True, reason="action_not_started", effects=ActionResult.typed([]))
        if self.stopped:
            return ActionResult(
                effects=ActionResult.typed([]),
                done=True,
                reason="stopped",
                detail=self._detail(
                    command=_inactive_command(),
                    command_detail={"enabled": False, "aligned": False, "hold_reason": "stopped"},
                    height_m=None,
                ),
            )
        if self.done:
            return ActionResult(effects=ActionResult.typed([]), done=True, reason="align_descend_done", detail=self.last_detail)
        if self.failed:
            return ActionResult(
                effects=ActionResult.typed([]),
                failed=True,
                reason=self.failure_reason or "align_descend_failed",
                detail=self._failed_detail(),
            )

        self.update_count += 1
        if self.update_count > self.max_updates:
            self.failed = True
            self.failure_reason = "align_descend_timeout"
            return ActionResult(
                effects=ActionResult.typed([]),
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
                effects=ActionResult.typed([]),
                failed=True,
                reason=self.failure_reason,
                detail=detail,
            )

        now = time.monotonic()
        dt_s = 0.0 if self._previous_update_monotonic_s is None else _clamp(now - self._previous_update_monotonic_s, 0.0, 1.0)
        self._previous_update_monotonic_s = now
        command, command_detail = compute_align_descend_command(inputs, self.config, altitude_m=altitude.value_m)
        target_ok = command_detail["enabled"] is True

        if target_ok:
            self.lost_updates = 0
            self._reset_integral_for_track_change(inputs)
            self._update_integral(command_detail, altitude.value_m, dt_s)
            if self.config.integral_enabled or self.config.min_effective_speed_enabled:
                command, command_detail = compute_align_descend_command(
                    inputs, self.config, altitude_m=altitude.value_m,
                    integral_vx_mps=self._integral_vx, integral_vy_mps=self._integral_vy,
                )
            command_detail["integral_enabled"] = bool(self.config.integral_enabled)
            command_detail["integral_active"] = self._integral_active(altitude.value_m)
            command_detail["integral_dt_s"] = dt_s
            command_detail["integral_reset_reason"] = self._integral_reset_reason
            self._last_valid_vx = float(command.get("vx_cmd", 0.0))
            self._last_valid_vy = float(command.get("vy_cmd", 0.0))
        elif (
            command_detail["hold_reason"] == "target_not_valid"
            and self.config.target_loss_policy != "continue_descent"
        ):
            self.lost_updates += 1
            self.hold_updates = 0
            if self.lost_updates <= self.config.target_loss_grace_updates:
                command = _command_dict(
                    vx=self._last_valid_vx * self.config.target_loss_grace_horizontal_scale,
                    vy=self._last_valid_vy * self.config.target_loss_grace_horizontal_scale,
                    vz=0.0,
                    enabled=True,
                )
                command_detail = {
                    **command_detail,
                    "enabled": True,
                    "hold_reason": "target_loss_grace",
                    "integral_enabled": bool(self.config.integral_enabled),
                    "integral_active": False,
                    "integral_dt_s": dt_s,
                    "integral_vx_mps": self._integral_vx,
                    "integral_vy_mps": self._integral_vy,
                    "integral_reset_reason": self._integral_reset_reason,
                }
            else:
                self._reset_integral("target_loss_timeout")
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
                        return ActionResult(effects=ActionResult.typed([]), reason="align_retry", detail=detail)
                    self.failed = True
                    self.failure_reason = "target_lost_timeout"
                    return ActionResult(
                        effects=ActionResult.typed([]), failed=True, reason="target_lost_timeout",
                        detail=self._failed_detail("target_lost_timeout", height_m=altitude.value_m, altitude_source=altitude.source),
                    )
        elif (
            self.config.target_loss_policy == "continue_descent"
            and command_detail["hold_reason"] == "target_not_valid"
        ):
            # Blind descent: zero horizontal, continue vertical
            self.hold_updates = 0
            blind_vz = self.config.target_loss_descend_speed_mps
            command = _command_dict(vx=0.0, vy=0.0, vz=blind_vz, enabled=True)
            gain_scale = _height_gain_scale(altitude.value_m, self.config)
            command_detail = {
                "enabled": True,
                "aligned": False,
                "slow_descending": False,
                "hold_reason": "target_loss_blind_descent",
                "ex_cam": 0.0,
                "ey_cam": 0.0,
                "raw_ex_cam": 0.0,
                "raw_ey_cam": 0.0,
                "desired_ex_cam": 0.0,
                "desired_ey_cam": 0.0,
                "corrected_ex_cam": 0.0,
                "corrected_ey_cam": 0.0,
                "height_gain_scale": gain_scale,
                "height_gain_mode": self.config.height_gain_mode,
                "height_gain_points_active": False,
                "kp_vx_eff": 0.0,
                "kp_vy_eff": 0.0,
                "max_vx_eff": 0.0,
                "max_vy_eff": 0.0,
                "payload_offset_enabled": False,
                "payload_offset_valid": False,
                "descent_speed_before_stage_mps": blind_vz,
                "descent_speed_cap_mps": None,
                "descent_speed_after_stage_mps": blind_vz,
                "descent_speed_stage_max_altitude_m": None,
                "descent_speed_stage_active": False,
            }
            stage_result = _apply_descent_speed_stages(blind_vz, altitude.value_m, self.config)
            if stage_result is not None:
                command["vz_cmd"] = stage_result["vz_cmd"]
                command_detail["descent_speed_before_stage_mps"] = stage_result.get("descent_speed_before_stage_mps", blind_vz)
                command_detail["descent_speed_cap_mps"] = stage_result.get("descent_speed_cap_mps")
                command_detail["descent_speed_after_stage_mps"] = stage_result.get("descent_speed_after_stage_mps", blind_vz)
                command_detail["descent_speed_stage_max_altitude_m"] = stage_result.get("descent_speed_stage_max_altitude_m")
                command_detail["descent_speed_stage_active"] = stage_result.get("descent_speed_stage_active", False)
        elif self.config.target_loss_policy == "continue_descent":
            # Blind descent is only permitted for loss of visual target.  A
            # control/state/input fault must fail so the mission can take its
            # Configured fallback for alignment workflows such as land_home.
            self.failed = True
            self.failure_reason = str(command_detail["hold_reason"])
            detail = self._failed_detail(
                self.failure_reason,
                height_m=altitude.value_m,
                altitude_source=altitude.source,
            )
            self.last_detail = detail
            return ActionResult(
                effects=ActionResult.typed([]),
                failed=True,
                reason=self.failure_reason,
                detail=detail,
            )
        else:
            self.lost_updates += 1
            self.hold_updates = 0
            self._reset_integral(str(command_detail["hold_reason"]))
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
                    return ActionResult(effects=ActionResult.typed([]), reason="align_retry", detail=detail)
                self.failed = True
                self.failure_reason = "target_lost_timeout"
                return ActionResult(
                    effects=ActionResult.typed([]),
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
                self.final_align_started_monotonic_s = now
                self.finish_alignment_hold_count = 0

            if self.final_align_started:
                self.finish_alignment_elapsed_s = (
                    0.0 if self.final_align_started_monotonic_s is None
                    else max(0.0, now - self.final_align_started_monotonic_s)
                )
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
                        self._reset_integral("completed")
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
                            effects=ActionResult.typed([]),
                            done=True,
                            reason="latched_center_aligned",
                            detail=detail,
                        )

                if (
                    self.finish_alignment_timeout_s is not None
                    and self.finish_alignment_elapsed_s >= self.finish_alignment_timeout_s
                ):
                    self.done = True
                    self._reset_integral("finish_alignment_timeout")
                    detail = self._detail(
                        command=self._command_with_yaw_hold(_inactive_command(), data),
                        command_detail={
                            **command_detail,
                            "hold_reason": "finish_alignment_timeout_release",
                        },
                        height_m=altitude.value_m,
                        altitude_source=altitude.source,
                    )
                    self.last_detail = detail
                    return ActionResult(
                        effects=ActionResult.typed([]),
                        done=True,
                        reason="finish_alignment_timeout_release",
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
                    effects=ActionResult.typed([]),
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
                return ActionResult(effects=ActionResult.typed([]), done=True, reason="aligned_at_finish_altitude", detail=detail)
            # Not aligned yet — continue with vz=0, vx/vy still active
            command, command_detail = compute_align_descend_command(
                inputs, self.config, altitude_m=altitude.value_m,
                integral_vx_mps=self._integral_vx, integral_vy_mps=self._integral_vy,
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
            return ActionResult(effects=ActionResult.typed([]), reason="aligning_at_finish_altitude", detail=detail)

        if altitude.value_m <= self.config.min_altitude_m:
            if self.finish_policy == "require_alignment_or_timeout":
                # Strict: don't set done, continue with vz=0
                command, command_detail = compute_align_descend_command(
                    inputs, self.config, altitude_m=altitude.value_m,
                    integral_vx_mps=self._integral_vx, integral_vy_mps=self._integral_vy,
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
                return ActionResult(effects=ActionResult.typed([]), reason="aligning_at_finish_altitude", detail=detail)
            self.done = True
            self._reset_integral("completed")
            detail = self._detail(
                command=self._command_with_yaw_hold(_inactive_command(), data),
                command_detail={**command_detail, "hold_reason": "min_altitude_reached"},
                height_m=altitude.value_m,
                altitude_source=altitude.source,
            )
            self.last_detail = detail
            return ActionResult(effects=ActionResult.typed([]), done=True, reason="min_altitude_reached", detail=detail)

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
                return ActionResult(effects=ActionResult.typed([]), done=True, reason="aligned_at_finish_altitude", detail=detail)
            if self.finish_policy == "require_alignment_or_timeout":
                # Not aligned yet — continue with vz=0, vx/vy still active
                command, command_detail = compute_align_descend_command(
                    inputs, self.config, altitude_m=altitude.value_m,
                    integral_vx_mps=self._integral_vx, integral_vy_mps=self._integral_vy,
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
                return ActionResult(effects=ActionResult.typed([]), reason="aligning_at_finish_altitude", detail=detail)
            self.done = True
            self._reset_integral("completed")
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
            return ActionResult(effects=ActionResult.typed([]), done=True, reason=done_reason, detail=detail)

        reason = "align_descending" if target_ok and command_detail["aligned"] else command_detail["hold_reason"]
        command = self._command_with_yaw_hold(command, data)
        detail = self._detail(
            command=command,
            command_detail={**command_detail, "hold_reason": reason},
            height_m=altitude.value_m,
            altitude_source=altitude.source,
        )
        self.last_detail = detail
        return ActionResult(effects=ActionResult.typed([]), reason=reason, detail=detail)

    def stop(self) -> None:
        self.stopped = True
        self._reset_integral("stop")

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
        self.final_align_started_monotonic_s: float | None = None
        self.finish_alignment_elapsed_s = 0.0
        self.finish_alignment_timeout_s: float | None = None
        self.finish_alignment_hold_count = 0
        self.yaw_hold_rad: float | None = None
        self.yaw_hold_source: str | None = None
        self.latest_context: dict[str, Any] = {}
        self.last_detail: dict[str, Any] = {}
        self._integral_vx = 0.0
        self._integral_vy = 0.0
        self._integral_reset_reason = "reset"
        self._previous_integral_ex: float | None = None
        self._previous_integral_ey: float | None = None
        self._integral_track_id: Any = None
        self._previous_update_monotonic_s: float | None = None
        self._last_valid_vx = 0.0
        self._last_valid_vy = 0.0

    def _reset_integral(self, reason: str) -> None:
        self._integral_vx = 0.0
        self._integral_vy = 0.0
        self._previous_integral_ex = None
        self._previous_integral_ey = None
        self._integral_reset_reason = reason

    def _integral_active(self, altitude_m: float) -> bool:
        return bool(self.config.integral_enabled and altitude_m <= self.config.integral_active_below_altitude_m)

    def _reset_integral_for_track_change(self, inputs: dict[str, Any]) -> None:
        track_id = inputs.get("track_id")
        if track_id is not None and self._integral_track_id is not None and track_id != self._integral_track_id:
            self._reset_integral("track_changed")
        if track_id is not None:
            self._integral_track_id = track_id

    def _update_integral(self, detail: dict[str, Any], altitude_m: float, dt_s: float) -> None:
        if not self._integral_active(altitude_m):
            return
        ex = float(detail["corrected_ex_cam"])
        ey = float(detail["corrected_ey_cam"])
        ex_active = abs(ex) > self.config.deadband_ex_cam
        ey_active = abs(ey) > self.config.deadband_ey_cam
        if not ex_active:
            self._integral_vy = 0.0
            self._previous_integral_ex = None
            self._integral_reset_reason = "ex_deadband"
        if not ey_active:
            self._integral_vx = 0.0
            self._previous_integral_ey = None
            self._integral_reset_reason = "ey_deadband"
        if ex_active and self._previous_integral_ex is not None and ex * self._previous_integral_ex < 0.0:
            self._integral_vy = 0.0
            self._integral_reset_reason = "ex_direction_reversed"
        if ey_active and self._previous_integral_ey is not None and ey * self._previous_integral_ey < 0.0:
            self._integral_vx = 0.0
            self._integral_reset_reason = "ey_direction_reversed"
        p_vx = float(detail["p_vx_mps"])
        p_vy = float(detail["p_vy_mps"])
        max_vx = float(detail["max_vx_eff"])
        max_vy = float(detail["max_vy_eff"])
        add_vx = self.config.vx_sign * self.config.ki_vx * ey * dt_s
        add_vy = self.config.vy_sign * self.config.ki_vy * ex * dt_s
        if ey_active and not (abs(p_vx) >= max_vx and p_vx * add_vx > 0.0):
            self._integral_vx = _clamp(self._integral_vx + add_vx, -self.config.integral_vx_limit_mps, self.config.integral_vx_limit_mps)
        if ex_active and not (abs(p_vy) >= max_vy and p_vy * add_vy > 0.0):
            self._integral_vy = _clamp(self._integral_vy + add_vy, -self.config.integral_vy_limit_mps, self.config.integral_vy_limit_mps)
        self._previous_integral_ex = ex if ex_active else None
        self._previous_integral_ey = ey if ey_active else None

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
            "track_id",
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
            "integral_enabled": command_detail.get("integral_enabled", bool(self.config.integral_enabled)),
            "integral_active": command_detail.get("integral_active", False),
            "integral_dt_s": command_detail.get("integral_dt_s", 0.0),
            "integral_vx_mps": command_detail.get("integral_vx_mps", self._integral_vx),
            "integral_vy_mps": command_detail.get("integral_vy_mps", self._integral_vy),
            "p_vx_mps": command_detail.get("p_vx_mps", 0.0),
            "p_vy_mps": command_detail.get("p_vy_mps", 0.0),
            "combined_vx_before_clamp_mps": command_detail.get("combined_vx_before_clamp_mps", 0.0),
            "combined_vy_before_clamp_mps": command_detail.get("combined_vy_before_clamp_mps", 0.0),
            "integral_reset_reason": command_detail.get("integral_reset_reason", self._integral_reset_reason),
            "min_effective_speed_enabled": command_detail.get("min_effective_speed_enabled", bool(self.config.min_effective_speed_enabled)),
            "min_effective_speed_active": command_detail.get("min_effective_speed_active", False),
            "min_effective_speed_applied_vx": command_detail.get("min_effective_speed_applied_vx", False),
            "min_effective_speed_applied_vy": command_detail.get("min_effective_speed_applied_vy", False),
            "min_effective_speed_mps": command_detail.get("min_effective_speed_mps", self.config.min_effective_speed_mps),
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
            "finish_alignment_timeout_s": getattr(self, "finish_alignment_timeout_s", None),
            "finish_alignment_elapsed_s": getattr(self, "finish_alignment_elapsed_s", 0.0),
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
