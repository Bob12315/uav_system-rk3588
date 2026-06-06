from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    actions: list[Any] = field(default_factory=list)
    done: bool = False
    failed: bool = False
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "done": bool(self.done),
            "failed": bool(self.failed),
            "reason": str(self.reason),
            "detail": dict(self.detail),
        }
