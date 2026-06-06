from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .base import ActionModule
from .result import ActionResult


@dataclass(frozen=True)
class AlignDescendConfig:
    kp_vx: float = 0.8
    kp_vy: float = 0.8
    max_vx_mps: float = 0.4
    max_vy_mps: float = 0.4
    descend_speed_mps: float = 0.2
    max_ex_cam: float = 0.06
    max_ey_cam: float = 0.06
    deadband_ex_cam: float = 0.015
    deadband_ey_cam: float = 0.015
    vx_sign: float = -1.0
    vy_sign: float = 1.0
    require_target_locked: bool = True

    def __post_init__(self) -> None:
        for name in ("kp_vx", "kp_vy"):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("max_vx_mps", "max_vy_mps", "descend_speed_mps"):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be positive")
        for name in ("max_ex_cam", "max_ey_cam"):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be positive")
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


def compute_align_descend_command(
    inputs: dict[str, Any],
    config: AlignDescendConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    control_allowed = bool(inputs.get("control_allowed", True))
    target_valid = bool(inputs.get("target_valid") or inputs.get("vision_valid"))
    target_locked = bool(inputs.get("target_locked", True))

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

    if enabled:
        aligned = abs(ex_cam) <= config.max_ex_cam and abs(ey_cam) <= config.max_ey_cam
        ex_for_control = 0.0 if abs(ex_cam) <= config.deadband_ex_cam else ex_cam
        ey_for_control = 0.0 if abs(ey_cam) <= config.deadband_ey_cam else ey_cam
        vx = _clamp(
            config.vx_sign * config.kp_vx * ey_for_control,
            -config.max_vx_mps,
            config.max_vx_mps,
        )
        vy = _clamp(
            config.vy_sign * config.kp_vy * ex_for_control,
            -config.max_vy_mps,
            config.max_vy_mps,
        )
        vz = config.descend_speed_mps if aligned else 0.0
        reason = "descending" if aligned else "aligning"

    command = _command_dict(
        vx=vx,
        vy=vy,
        vz=vz,
        enabled=enabled,
    )
    detail = {
        "enabled": enabled,
        "aligned": aligned,
        "hold_reason": reason,
        "ex_cam": ex_cam,
        "ey_cam": ey_cam,
    }
    return command, detail


class AlignDescendAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.config = AlignDescendConfig(**dict(data.get("config") or {}))

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
        inputs = self._inputs(data)
        height_m = self._height_m(data)
        command, command_detail = compute_align_descend_command(inputs, self.config)
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
                        height_m=height_m,
                    )
                    self.last_detail = detail
                    return ActionResult(actions=[], reason="align_retry", detail=detail)
                self.failed = True
                self.failure_reason = "target_lost_timeout"
                return ActionResult(
                    actions=[],
                    failed=True,
                    reason="target_lost_timeout",
                    detail=self._failed_detail("target_lost_timeout", height_m=height_m),
                )

        if target_ok and command_detail["aligned"] is True:
            self.hold_updates += 1
        elif target_ok:
            self.hold_updates = 0

        if (
            self.finish_altitude_m is not None
            and height_m is not None
            and height_m <= self.finish_altitude_m
            and self.hold_updates >= self.hold_updates_required
        ):
            self.done = True
            detail = self._detail(
                command=_inactive_command(),
                command_detail={**command_detail, "hold_reason": "align_descend_done"},
                height_m=height_m,
            )
            self.last_detail = detail
            return ActionResult(actions=[], done=True, reason="align_descend_done", detail=detail)

        reason = "align_descending" if target_ok and command_detail["aligned"] else command_detail["hold_reason"]
        detail = self._detail(
            command=command,
            command_detail={**command_detail, "hold_reason": reason},
            height_m=height_m,
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
        self.last_detail: dict[str, Any] = {}

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

    def _height_m(self, context: dict[str, Any]) -> float | None:
        candidates: list[dict[str, Any]] = [context]
        drone = context.get("drone")
        if isinstance(drone, dict):
            candidates.append(drone)
            local_position = drone.get("local_position")
            if isinstance(local_position, dict):
                candidates.append(local_position)
        local_position = context.get("local_position")
        if isinstance(local_position, dict):
            candidates.append(local_position)

        for name in ("relative_altitude", "relative_altitude_m"):
            value = self._first_float(candidates, name)
            if value is not None:
                return max(0.0, value)

        local_z = self._first_float(candidates, "local_z")
        if local_z is None:
            local_z = self._first_float(candidates, "z")
        if local_z is not None and local_z < 0.0:
            return -local_z

        for name in ("altitude", "altitude_m"):
            value = self._first_float(candidates, name)
            if value is not None:
                return max(0.0, value)
        return None

    def _detail(
        self,
        *,
        command: dict[str, Any],
        command_detail: dict[str, Any],
        height_m: float | None,
    ) -> dict[str, Any]:
        return {
            "command": command,
            "enabled": bool(command_detail.get("enabled", False)),
            "aligned": bool(command_detail.get("aligned", False)),
            "hold_reason": str(command_detail.get("hold_reason", "")),
            "height_m": height_m,
            "lost_updates": int(self.lost_updates),
            "hold_updates": int(self.hold_updates),
            "retries": int(self.retries),
            "update_count": int(self.update_count),
        }

    def _failed_detail(self, reason: str | None = None, *, height_m: float | None = None) -> dict[str, Any]:
        return self._detail(
            command=_inactive_command(),
            command_detail={
                "enabled": False,
                "aligned": False,
                "hold_reason": reason or self.failure_reason or "align_descend_failed",
            },
            height_m=height_m,
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
    return _command_dict(vx=0.0, vy=0.0, vz=0.0, enabled=False)


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))
