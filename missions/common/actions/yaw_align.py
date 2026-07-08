from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult


class YawAlignAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.yaw_mode = str(data.get("yaw_mode", "field_heading")).strip().lower()
        if self.yaw_mode not in {"field_heading", "fixed"}:
            raise ValueError("yaw_mode must be field_heading or fixed")
        self.yaw_rad = self._optional_float(data.get("yaw_rad"))
        if self.yaw_mode == "fixed" and self.yaw_rad is None:
            yaw_deg = self._optional_float(data.get("yaw_deg"))
            if yaw_deg is not None:
                self.yaw_rad = math.radians(yaw_deg)
        if self.yaw_mode == "fixed" and self.yaw_rad is None:
            raise ValueError("yaw_mode fixed requires yaw_rad or yaw_deg")

        self.tolerance_rad = math.radians(float(data.get("tolerance_deg", 3.0)))
        self.yaw_speed_deg_s = float(data.get("yaw_speed_deg_s", 25.0))
        self.min_hold_updates = int(data.get("min_hold_updates", 5))
        self.max_updates = int(data.get("max_updates", 120))
        if self.tolerance_rad <= 0.0:
            raise ValueError("tolerance_deg must be positive")
        if self.yaw_speed_deg_s <= 0.0:
            raise ValueError("yaw_speed_deg_s must be positive")
        if self.min_hold_updates < 1:
            raise ValueError("min_hold_updates must be at least 1")
        if self.max_updates < 1:
            raise ValueError("max_updates must be at least 1")

        self.priority = int(data.get("priority", 4))
        self.key = str(data.get("key") or "").strip() or "yaw_align"
        self.started = True
        self.stopped = False
        self.done = False
        self.failed = False
        self.failure_reason = ""
        self.update_count = 0
        self.hold_updates = 0
        self.command_sent = False
        self.last_detail = self._detail()

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail())
        if self.done:
            return ActionResult(done=True, reason="yaw_aligned", detail=dict(self.last_detail))

        self.update_count += 1
        context_data = context or {}
        target_yaw = self._target_yaw(context_data)
        current_yaw = self._current_yaw(context_data)
        if target_yaw is None:
            self.failed = True
            self.failure_reason = "missing_target_yaw"
            detail = self._detail(current_yaw=current_yaw, target_yaw=target_yaw)
            self.last_detail = detail
            return ActionResult(failed=True, reason="missing_target_yaw", detail=detail)
        if current_yaw is None:
            detail = self._detail(current_yaw=current_yaw, target_yaw=target_yaw)
            self.last_detail = detail
            if self.update_count > self.max_updates:
                self.failed = True
                self.failure_reason = "yaw_align_timeout"
                return ActionResult(failed=True, reason="yaw_align_timeout", detail=detail)
            return ActionResult(reason="waiting_for_yaw_state", detail=detail)

        yaw_error = self._normalize(current_yaw - target_yaw)
        if abs(yaw_error) <= self.tolerance_rad:
            self.hold_updates += 1
        else:
            self.hold_updates = 0

        detail = self._detail(
            current_yaw=current_yaw,
            target_yaw=target_yaw,
            yaw_error=yaw_error,
            context=context_data,
        )
        self.last_detail = detail
        if self.hold_updates >= self.min_hold_updates:
            self.done = True
            return ActionResult(done=True, reason="yaw_aligned", detail=detail)
        if self.update_count > self.max_updates:
            self.failed = True
            self.failure_reason = "yaw_align_timeout"
            return ActionResult(failed=True, reason="yaw_align_timeout", detail=detail)
        if not self.command_sent:
            self.command_sent = True
            return ActionResult(
                actions=[self._condition_yaw_action(target_yaw)],
                reason="yaw_align_sent",
                detail=detail,
            )
        return ActionResult(reason="yaw_align_waiting", detail=detail)

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.started = False
        self.stopped = False
        self.done = False
        self.failed = False
        self.failure_reason = ""
        self.yaw_mode = "field_heading"
        self.yaw_rad: float | None = None
        self.tolerance_rad = math.radians(3.0)
        self.yaw_speed_deg_s = 25.0
        self.min_hold_updates = 5
        self.max_updates = 120
        self.priority = 4
        self.key = "yaw_align"
        self.update_count = 0
        self.hold_updates = 0
        self.command_sent = False
        self.last_detail: dict[str, Any] = {}

    def _condition_yaw_action(self, target_yaw: float) -> dict[str, Any]:
        return {
            "action_type": "condition_yaw",
            "params": {
                "yaw_deg": self._yaw_deg_0_360(target_yaw),
                "yaw_speed_deg_s": self.yaw_speed_deg_s,
                "direction": 0,
                "relative": False,
            },
            "key": f"{self.key}_condition_yaw",
            "once": False,
            "priority": self.priority,
        }

    def _target_yaw(self, context: dict[str, Any]) -> float | None:
        if self.yaw_mode == "fixed":
            return self._normalize(self.yaw_rad) if self.yaw_rad is not None else None
        if not bool(context.get("field_heading_confirmed", False)):
            return None
        return self._optional_float(context.get("field_heading_yaw_rad"))

    def _current_yaw(self, context: dict[str, Any]) -> float | None:
        drone = context.get("drone")
        if isinstance(drone, dict):
            yaw = self._optional_float(drone.get("yaw"))
            if yaw is not None:
                return yaw
        return self._optional_float(context.get("yaw"))

    def _detail(
        self,
        *,
        current_yaw: float | None = None,
        target_yaw: float | None = None,
        yaw_error: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context_data = context or {}
        return {
            "yaw_mode": self.yaw_mode,
            "current_yaw_rad": current_yaw,
            "target_yaw_rad": target_yaw,
            "yaw_error_rad": yaw_error,
            "yaw_error_deg": None if yaw_error is None else math.degrees(yaw_error),
            "tolerance_deg": math.degrees(self.tolerance_rad),
            "hold_updates": self.hold_updates,
            "min_hold_updates": self.min_hold_updates,
            "update_count": self.update_count,
            "max_updates": self.max_updates,
            "command_sent": self.command_sent,
            "field_heading_confirmed": bool(context_data.get("field_heading_confirmed", False)),
        }

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(result):
            return None
        return result

    @staticmethod
    def _normalize(yaw: float | None) -> float:
        if yaw is None:
            return 0.0
        return (float(yaw) + math.pi) % (2.0 * math.pi) - math.pi

    @staticmethod
    def _yaw_deg_0_360(yaw: float) -> float:
        return math.degrees(yaw) % 360.0
