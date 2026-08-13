from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class RunAuthorization:
    run_id: str
    operator: str
    scope_type: str
    scope_name: str
    target_source: str
    confirmed_at: float
    confirmed_at_monotonic: float
    allowed_actions: frozenset[str]

    @classmethod
    def create(
        cls,
        *,
        operator: str,
        scope_type: str,
        scope_name: str,
        target_source: str,
        allowed_actions: set[str] | frozenset[str],
    ) -> "RunAuthorization":
        if target_source not in {"sitl", "real"}:
            raise ValueError("target_source must be sitl or real")
        now = time.time()
        return cls(
            run_id=uuid.uuid4().hex,
            operator=str(operator or "unknown"),
            scope_type=scope_type,
            scope_name=scope_name,
            target_source=target_source,
            confirmed_at=now,
            confirmed_at_monotonic=time.monotonic(),
            allowed_actions=frozenset(allowed_actions),
        )

    def permits(self, action_name: str | None, source: str | None) -> bool:
        return bool(
            action_name
            and action_name in self.allowed_actions
            and (source == self.target_source or source == "test")
        )

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["allowed_actions"] = sorted(self.allowed_actions)
        return value
