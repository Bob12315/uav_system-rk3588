from __future__ import annotations

from typing import Any

from .base import ActionModule
from .result import ActionResult


class LandAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        land_altitude_threshold_m = float(data.get("land_altitude_threshold_m", 0.25))
        max_updates = int(data.get("max_updates", 200))
        if land_altitude_threshold_m < 0.0:
            raise ValueError("land_altitude_threshold_m must be non-negative")
        if max_updates < 1:
            raise ValueError("max_updates must be at least 1")

        key = str(data.get("key") or "").strip() or "land"
        self.land_altitude_threshold_m = land_altitude_threshold_m
        self.max_updates = max_updates
        self.priority = int(data.get("priority", 2))
        self.key = key
        self.phase = "send_land"
        self.started = True
        self.stopped = False
        self.done = False
        self.failed = False
        self.failure_reason = ""
        self.update_count = 0
        self.land_sent = False
        self.last_detail = self._detail()

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail())
        if self.done:
            return ActionResult(done=True, reason="land_done", detail=dict(self.last_detail))

        self.update_count += 1
        context_data = context or {}
        current_altitude_m, altitude_source = self._current_altitude(context_data)
        armed = self._current_armed(context_data)
        if self.update_count > self.max_updates:
            self.phase = "failed"
            self.failed = True
            self.failure_reason = "land_timeout"
            detail = self._detail(current_altitude_m, altitude_source, armed)
            self.last_detail = detail
            return ActionResult(failed=True, reason="land_timeout", detail=detail)

        if self.phase == "send_land":
            action = {
                "action_type": "land",
                "params": {},
                "key": f"{self.key}_command",
                "once": True,
                "priority": self.priority,
            }
            self.land_sent = True
            detail = self._detail(current_altitude_m, altitude_source, armed, phase="send_land")
            self.last_detail = detail
            self.phase = "wait_landed"
            return ActionResult(actions=[action], reason="land_sent", detail=detail)

        if self.phase == "wait_landed":
            landed = self._landed(current_altitude_m, armed)
            detail = self._detail(current_altitude_m, altitude_source, armed, landed=landed)
            self.last_detail = detail
            if landed:
                self.done = True
                self.phase = "done"
                return ActionResult(done=True, reason="landed", detail=detail)
            if current_altitude_m is None and armed is None:
                return ActionResult(reason="waiting_for_landing_state", detail=detail)
            return ActionResult(reason="waiting_for_landing", detail=detail)

        return ActionResult(
            failed=True,
            reason="invalid_land_phase",
            detail=self._detail(current_altitude_m, altitude_source, armed),
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.phase = "idle"
        self.started = False
        self.stopped = False
        self.done = False
        self.failed = False
        self.update_count = 0
        self.failure_reason = ""
        self.land_sent = False
        self.land_altitude_threshold_m = 0.25
        self.max_updates = 200
        self.priority = 2
        self.key = "land"
        self.last_detail: dict[str, Any] = {}

    def _current_altitude(self, context: dict[str, Any]) -> tuple[float | None, str]:
        for name in ("relative_altitude", "relative_altitude_m", "altitude_m"):
            value = self._float_value(context.get(name))
            if value is not None:
                return max(0.0, value), name

        value = self._negative_z_value(context)
        if value is not None:
            return value, "local_z"

        local_position = context.get("local_position")
        if isinstance(local_position, dict):
            value = self._negative_z_value(local_position)
            if value is not None:
                return value, "local_position.z"

        drone = context.get("drone")
        if isinstance(drone, dict):
            for name in ("relative_altitude", "relative_altitude_m", "altitude_m"):
                value = self._float_value(drone.get(name))
                if value is not None:
                    return max(0.0, value), f"drone.{name}"
            value = self._negative_z_value(drone)
            if value is not None:
                return value, "drone.local_z"
            local_position = drone.get("local_position")
            if isinstance(local_position, dict):
                value = self._negative_z_value(local_position)
                if value is not None:
                    return value, "drone.local_position.z"

        vehicle = context.get("vehicle")
        if isinstance(vehicle, dict):
            for name in ("relative_altitude", "relative_altitude_m"):
                value = self._float_value(vehicle.get(name))
                if value is not None:
                    return max(0.0, value), f"vehicle.{name}"
            value = self._negative_z_value(vehicle)
            if value is not None:
                return value, "vehicle.local_z"

        return None, ""

    def _current_armed(self, context: dict[str, Any]) -> bool | None:
        for source in (context, context.get("drone"), context.get("vehicle")):
            if not isinstance(source, dict) or "armed" not in source:
                continue
            value = source.get("armed")
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off"}:
                    return False
        return None

    def _landed(self, current_altitude_m: float | None, armed: bool | None) -> bool:
        if current_altitude_m is not None and current_altitude_m <= self.land_altitude_threshold_m:
            return True
        return armed is False

    def _detail(
        self,
        current_altitude_m: float | None = None,
        altitude_source: str = "",
        armed: bool | None = None,
        *,
        phase: str | None = None,
        landed: bool | None = None,
    ) -> dict[str, Any]:
        if landed is None:
            landed = self._landed(current_altitude_m, armed)
        return {
            "phase": phase or self.phase,
            "land_altitude_threshold_m": self.land_altitude_threshold_m,
            "current_altitude_m": current_altitude_m,
            "altitude_source": altitude_source,
            "armed": armed,
            "land_sent": self.land_sent,
            "landed": landed,
            "update_count": self.update_count,
            "max_updates": self.max_updates,
        }

    def _float_value(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _negative_z_value(self, data: dict[str, Any]) -> float | None:
        for name in ("local_z", "z"):
            value = self._float_value(data.get(name))
            if value is not None and value < 0.0:
                return max(0.0, -value)
        return None
