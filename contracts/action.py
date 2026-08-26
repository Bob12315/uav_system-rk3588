from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from .effects import Effect, effect_from_request


@dataclass(frozen=True, slots=True)
class OperationResult:
    ok: bool
    message: str


@dataclass(slots=True)
class ActionResult:
    effects: list[Effect] = field(default_factory=list)
    done: bool = False
    failed: bool = False
    reason: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        effects: list[Effect] | None = None,
        done: bool = False,
        failed: bool = False,
        reason: str = "",
        output: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.effects = list(effects or [])
        if any(not hasattr(item, "to_request") for item in self.effects):
            raise TypeError("ActionResult.effects accepts typed Effect values only")
        self.done = bool(done)
        self.failed = bool(failed)
        self.reason = str(reason)
        self.output = dict(output or {})
        self.detail = dict(detail or {})

    @staticmethod
    def typed(requests: list[Any] | None) -> list[Effect]:
        """Explicit migration boundary for Action-local request construction."""
        return [
            effect_from_request(item) if isinstance(item, dict) else item
            for item in list(requests or [])
        ]

    @property
    def actions(self) -> list[dict[str, Any]]:
        """Compatibility view removed when typed-effect migration completes."""
        return [item.to_request() for item in self.effects]

    def to_dict(self) -> dict[str, Any]:
        serialized = self.actions
        return {"actions": serialized, "done": self.done,
                "failed": self.failed, "reason": self.reason,
                "output": dict(self.output), "detail": dict(self.detail)}
