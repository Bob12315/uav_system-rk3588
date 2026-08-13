from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult


_SPEED_TYPES = {"air": 0, "ground": 1, "climb": 2, "descent": 3}


class ChangeSpeedAction(ActionModule):
    """Apply a flight-controller speed target through the normal dispatcher."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.speed_mps = float(data.get("speed_mps", 0.0))
        if not math.isfinite(self.speed_mps) or self.speed_mps <= 0.0:
            raise ValueError("speed_mps must be finite and > 0")
        speed_type = str(data.get("speed_type", "ground")).strip().lower()
        if speed_type not in _SPEED_TYPES:
            raise ValueError("speed_type must be air, ground, climb, or descent")
        self.speed_type = speed_type
        self.speed_type_id = _SPEED_TYPES[speed_type]
        self.priority = int(data.get("priority", 4))
        self.key = str(data.get("key") or f"change_speed_{speed_type}_{self.speed_mps:.2f}")
        self.started = True
        self.stopped = False
        self.done = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail())
        if self.done:
            return ActionResult(done=True, reason="speed_changed", detail=self._detail())
        self.done = True
        return ActionResult(
            effects=ActionResult.typed([{
                "action_type": "change_speed",
                "params": {
                    "speed_mps": self.speed_mps,
                    "speed_type": self.speed_type_id,
                },
                "key": self.key,
                "once": True,
                "priority": self.priority,
            }]),
            done=True,
            reason="speed_change_sent",
            detail=self._detail(),
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.speed_mps = 0.0
        self.speed_type = "ground"
        self.speed_type_id = 1
        self.priority = 4
        self.key = "change_speed"
        self.started = False
        self.stopped = False
        self.done = False

    def _detail(self) -> dict[str, Any]:
        return {
            "speed_mps": self.speed_mps,
            "speed_type": self.speed_type,
            "speed_type_id": self.speed_type_id,
            "priority": self.priority,
            "key": self.key,
        }
