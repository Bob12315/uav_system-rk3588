from __future__ import annotations

from typing import Any

from .base import ActionModule
from .result import ActionResult


class PayloadReleaseAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.channels = self._channels(data)
        self.release_pwm = self._pwm(data, "release_pwm")
        self.hold_pwm = self._pwm(data, "hold_pwm")
        self.payload_id = self._required_id(data, "payload_id")
        self.target_id = self._required_id(data, "target_id")
        self.release_wait_updates = int(data.get("release_wait_updates", 5))
        if self.release_wait_updates < 1:
            raise ValueError("release_wait_updates must be at least 1")
        self.priority = int(data.get("priority", 3))
        self.key = str(data.get("key") or f"payload_release_{self.payload_id}_{self.target_id}")
        self.release_time = data.get("release_time")

        self.started = True
        self.state = "release"
        self.wait_updates = 0
        self.release_sent = False
        self.hold_sent = False
        self.done = False
        self.failed = False
        self.stopped = False
        self.last_detail = self._detail()

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", actions=[], detail=self._detail())
        if self.done:
            return ActionResult(done=True, reason="payload_released", actions=[], detail=self.last_detail)

        if self.state == "release":
            if self.release_time is None:
                self.release_time = self._release_time_from_context(context or {})
            self.release_sent = True
            self.state = "wait"
            self.wait_updates = 0
            detail = self._detail()
            self.last_detail = detail
            return ActionResult(
                actions=self._servo_actions(self.release_pwm, "release"),
                reason="release_sent",
                detail=detail,
            )

        if self.state == "wait":
            self.wait_updates += 1
            if self.wait_updates < self.release_wait_updates:
                detail = self._detail()
                self.last_detail = detail
                return ActionResult(actions=[], reason="release_waiting", detail=detail)

            self.hold_sent = True
            self.state = "done"
            self.done = True
            detail = self._detail()
            self.last_detail = detail
            return ActionResult(
                actions=self._servo_actions(self.hold_pwm, "hold"),
                done=True,
                reason="payload_released",
                detail=detail,
            )

        self.failed = True
        return ActionResult(failed=True, reason="invalid_payload_release_state", actions=[], detail=self._detail())

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.started = False
        self.state = "idle"
        self.channels: list[int] = []
        self.release_pwm = 0
        self.hold_pwm = 0
        self.payload_id: str | int = ""
        self.target_id: str | int = ""
        self.release_time: float | str | None = None
        self.release_wait_updates = 5
        self.priority = 3
        self.key = ""
        self.wait_updates = 0
        self.release_sent = False
        self.hold_sent = False
        self.done = False
        self.failed = False
        self.stopped = False
        self.last_detail: dict[str, Any] = {}

    def _servo_actions(self, pwm: int, phase: str) -> list[dict[str, Any]]:
        return [
            {
                "action_type": "set_servo",
                "params": {"channel": channel, "pwm": pwm},
                "key": f"{self.key}_{phase}_rc{channel}",
                "once": True,
                "priority": self.priority,
            }
            for channel in self.channels
        ]

    def _detail(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "channels": list(self.channels),
            "release_pwm": self.release_pwm,
            "hold_pwm": self.hold_pwm,
            "payload_id": self.payload_id,
            "target_id": self.target_id,
            "release_time": self.release_time,
            "release_sent": bool(self.release_sent),
            "hold_sent": bool(self.hold_sent),
            "wait_updates": int(self.wait_updates),
            "release_wait_updates": int(self.release_wait_updates),
        }

    def _channels(self, params: dict[str, Any]) -> list[int]:
        raw_channels: Any
        if params.get("channels") is not None:
            raw_channels = params["channels"]
            if not isinstance(raw_channels, list):
                raise ValueError("channels must be a list")
        elif params.get("channel") is not None:
            raw_channels = [params["channel"]]
        else:
            raw_channels = [13]

        if not raw_channels:
            raise ValueError("channels must be non-empty")
        channels: list[int] = []
        seen: set[int] = set()
        for value in raw_channels:
            try:
                channel = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("channel must be an integer") from exc
            if channel <= 0:
                raise ValueError("channel must be positive")
            if channel not in seen:
                channels.append(channel)
                seen.add(channel)
        if not channels:
            raise ValueError("channels must be non-empty")
        return channels

    def _pwm(self, params: dict[str, Any], name: str) -> int:
        if name not in params:
            raise ValueError(f"{name} is required")
        try:
            value = int(params[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if not 500 <= value <= 2500:
            raise ValueError(f"{name} must be between 500 and 2500")
        return value

    def _required_id(self, params: dict[str, Any], name: str) -> str | int:
        if name not in params:
            raise ValueError(f"{name} is required")
        value = params[name]
        if isinstance(value, str) and value.strip() == "":
            raise ValueError(f"{name} is required")
        return value

    @staticmethod
    def _release_time_from_context(context: dict[str, Any]) -> float | str | None:
        if "timestamp" in context:
            return context["timestamp"]
        if "time" in context:
            return context["time"]
        return None
