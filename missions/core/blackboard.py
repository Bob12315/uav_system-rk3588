from __future__ import annotations

from dataclasses import dataclass

from contracts.core.common import FrozenJson, FrozenObject, freeze_json, thaw_json
from contracts.core.mission import BlackboardRefExpr
from contracts.core.time import CoreTime
from contracts.platform.common import ResourceVersion


@dataclass(frozen=True, slots=True)
class BlackboardEntry:
    value: FrozenJson
    producing_step_id: str
    action_contract_fingerprint: str
    output_schema_id: str
    produced_at: CoreTime


@dataclass(frozen=True, slots=True)
class BlackboardSnapshot:
    version: ResourceVersion
    entries: tuple[tuple[str, BlackboardEntry], ...] = ()

    def put(self, key: str, entry: BlackboardEntry, *, allow_overwrite: bool = False) -> "BlackboardSnapshot":
        if not key:
            raise ValueError("blackboard key must not be empty")
        current = dict(self.entries)
        if key in current and not allow_overwrite:
            raise ValueError(f"blackboard key already exists: {key}")
        current[key] = entry
        return BlackboardSnapshot(self.version.next(), tuple(sorted(current.items())))

    def resolve(self, expression: BlackboardRefExpr) -> FrozenJson:
        try:
            value: FrozenJson = dict(self.entries)[expression.root_key].value
        except KeyError as exc:
            raise KeyError(expression.root_key) from exc
        for part in expression.path:
            if isinstance(part, int):
                if not isinstance(value, tuple):
                    raise KeyError(part)
                try:
                    value = value[part]
                except IndexError as exc:
                    raise KeyError(part) from exc
            else:
                if not isinstance(value, FrozenObject):
                    raise KeyError(part)
                value = value[part]
        return value


def resolve_compiled_parameters(value: FrozenJson, blackboard: BlackboardSnapshot) -> FrozenJson:
    """Resolve compiler-owned expression tags outside Coordinator/control code."""
    raw = thaw_json(value)

    def resolve(item):
        if isinstance(item, dict):
            if set(item) == {"$blackboard", "path"}:
                expression = BlackboardRefExpr(str(item["$blackboard"]), tuple(item["path"]))
                return thaw_json(blackboard.resolve(expression))
            return {key: resolve(child) for key, child in item.items()}
        if isinstance(item, list):
            return [resolve(child) for child in item]
        return item

    return freeze_json(resolve(raw))
