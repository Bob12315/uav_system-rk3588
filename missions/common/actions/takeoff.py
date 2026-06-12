from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ActionModule
from .result import ActionResult


@dataclass(slots=True)
class _AltitudeSample:
    value_m: float
    source: str


class TakeoffAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        raw_mode = data.get("mode", "GUIDED")
        if not isinstance(raw_mode, str):
            raise ValueError("mode must be a non-empty string")
        mode = raw_mode.strip().upper()
        if not mode:
            raise ValueError("mode must be a non-empty string")

        altitude_m = float(data.get("altitude_m", 3.0))
        altitude_tolerance_m = float(data.get("altitude_tolerance_m", 0.3))
        max_updates = int(data.get("max_updates", 120))
        if altitude_m <= 0.0:
            raise ValueError("altitude_m must be positive")
        if altitude_tolerance_m <= 0.0:
            raise ValueError("altitude_tolerance_m must be positive")
        if max_updates < 1:
            raise ValueError("max_updates must be at least 1")

        self.mode = mode
        self.altitude_m = altitude_m
        self.altitude_tolerance_m = altitude_tolerance_m
        self.require_armed = self._bool_param(data.get("require_armed", True), "require_armed")
        self.max_updates = max_updates
        self.priority = int(data.get("priority", 2))
        self.arm_priority = int(data.get("arm_priority", 1))
        self.mode_priority = int(data.get("mode_priority", 2))
        self.key = str(data.get("key") or "takeoff")

        self.phase = "set_mode"
        self.started = True
        self.stopped = False
        self.done = False
        self.failed = False
        self.failure_reason = ""
        self.update_count = 0
        self.mode_sent = False
        self.arm_sent = False
        self.takeoff_sent = False
        self.last_detail = self._detail()

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail())
        if self.done:
            return ActionResult(done=True, reason="takeoff_done", detail=dict(self.last_detail))

        self.update_count += 1
        context_data = context or {}
        altitude = self._current_altitude(context_data)
        if self.update_count > self.max_updates:
            self.phase = "failed"
            self.failed = True
            self.failure_reason = "takeoff_timeout"
            detail = self._detail(altitude)
            self.last_detail = detail
            return ActionResult(failed=True, reason="takeoff_timeout", detail=detail)

        if self.phase == "set_mode":
            action = {
                "action_type": "set_mode",
                "params": {"mode": self.mode},
                "key": f"{self.key}_set_mode",
                "once": True,
                "priority": self.mode_priority,
            }
            self.mode_sent = True
            detail = self._detail(altitude, phase="set_mode")
            self.last_detail = detail
            self.phase = "arm"
            return ActionResult(actions=[action], reason="set_mode_sent", detail=detail)

        if self.phase == "arm":
            if not self.require_armed:
                self.phase = "takeoff"
                return self._takeoff_result(altitude)
            action = {
                "action_type": "arm",
                "params": {},
                "key": f"{self.key}_arm",
                "once": True,
                "priority": self.arm_priority,
            }
            self.arm_sent = True
            detail = self._detail(altitude, phase="arm")
            self.last_detail = detail
            self.phase = "takeoff"
            return ActionResult(actions=[action], reason="arm_sent", detail=detail)

        if self.phase == "takeoff":
            return self._takeoff_result(altitude)

        if self.phase == "wait_altitude":
            if altitude is None:
                detail = self._detail(None)
                self.last_detail = detail
                return ActionResult(reason="waiting_for_altitude", detail=detail)
            reached = altitude.value_m >= self.altitude_m - self.altitude_tolerance_m
            detail = self._detail(altitude, reached=reached)
            self.last_detail = detail
            if reached:
                self.done = True
                self.phase = "done"
                return ActionResult(done=True, reason="takeoff_altitude_reached", detail=detail)
            return ActionResult(reason="waiting_for_takeoff_altitude", detail=detail)

        return ActionResult(failed=True, reason="invalid_takeoff_phase", detail=self._detail(altitude))

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
        self.mode_sent = False
        self.arm_sent = False
        self.takeoff_sent = False
        self.mode = "GUIDED"
        self.altitude_m = 3.0
        self.altitude_tolerance_m = 0.3
        self.require_armed = True
        self.max_updates = 120
        self.priority = 2
        self.arm_priority = 1
        self.mode_priority = 2
        self.key = "takeoff"
        self.last_detail: dict[str, Any] = {}

    def _takeoff_result(self, altitude: _AltitudeSample | None) -> ActionResult:
        action = {
            "action_type": "takeoff",
            "params": {"altitude_m": self.altitude_m},
            "key": f"{self.key}_takeoff",
            "once": True,
            "priority": self.priority,
        }
        self.takeoff_sent = True
        detail = self._detail(altitude, phase="takeoff")
        self.last_detail = detail
        self.phase = "wait_altitude"
        return ActionResult(actions=[action], reason="takeoff_sent", detail=detail)

    def _current_altitude(self, context: dict[str, Any]) -> _AltitudeSample | None:
        for name in ("relative_altitude", "relative_altitude_m", "altitude_m"):
            sample = self._float_sample(context, name, name)
            if sample is not None:
                return sample

        sample = self._negative_z_sample(context, "local_z")
        if sample is not None:
            return sample

        local_position = context.get("local_position")
        if isinstance(local_position, dict):
            sample = self._negative_z_sample(local_position, "local_position.z")
            if sample is not None:
                return sample

        drone = context.get("drone")
        if isinstance(drone, dict):
            for name in ("relative_altitude", "relative_altitude_m", "altitude_m"):
                sample = self._float_sample(drone, name, f"drone.{name}")
                if sample is not None:
                    return sample
            sample = self._negative_z_sample(drone, "drone.local_z")
            if sample is not None:
                return sample
            local_position = drone.get("local_position")
            if isinstance(local_position, dict):
                sample = self._negative_z_sample(local_position, "drone.local_position.z")
                if sample is not None:
                    return sample

        vehicle = context.get("vehicle")
        if isinstance(vehicle, dict):
            for name in ("relative_altitude", "relative_altitude_m"):
                sample = self._float_sample(vehicle, name, f"vehicle.{name}")
                if sample is not None:
                    return sample
            sample = self._negative_z_sample(vehicle, "vehicle.local_z")
            if sample is not None:
                return sample

        return None

    def _float_sample(self, data: dict[str, Any], name: str, source: str) -> _AltitudeSample | None:
        if name not in data:
            return None
        try:
            value = float(data[name])
        except (TypeError, ValueError):
            return None
        return _AltitudeSample(max(0.0, value), source)

    def _negative_z_sample(self, data: dict[str, Any], source: str) -> _AltitudeSample | None:
        value = None
        for name in ("local_z", "z"):
            if name in data:
                try:
                    value = float(data[name])
                except (TypeError, ValueError):
                    value = None
                break
        if value is not None and value < 0.0:
            return _AltitudeSample(max(0.0, -value), source)
        return None

    def _detail(
        self,
        altitude: _AltitudeSample | None = None,
        *,
        phase: str | None = None,
        reached: bool | None = None,
    ) -> dict[str, Any]:
        current_altitude_m = None if altitude is None else altitude.value_m
        if reached is None:
            reached = (
                current_altitude_m is not None
                and current_altitude_m >= self.altitude_m - self.altitude_tolerance_m
            )
        return {
            "phase": phase or self.phase,
            "mode": self.mode,
            "target_altitude_m": self.altitude_m,
            "altitude_tolerance_m": self.altitude_tolerance_m,
            "current_altitude_m": current_altitude_m,
            "altitude_source": "" if altitude is None else altitude.source,
            "reached": reached,
            "update_count": self.update_count,
            "max_updates": self.max_updates,
            "mode_sent": self.mode_sent,
            "arm_sent": self.arm_sent,
            "takeoff_sent": self.takeoff_sent,
        }

    def _bool_param(self, value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"{name} must be a bool")
