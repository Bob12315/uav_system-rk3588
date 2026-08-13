from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from missions.common.actions.base import ActionModule


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """Single public definition consumed by registry, Web and validators."""

    name: str
    factory: type[ActionModule]
    label: str
    description: str
    default_params: dict[str, Any] = field(default_factory=dict)
    parameter_schema: dict[str, Any] = field(default_factory=dict)

    def web_spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "default_params": self.default_params,
            "parameter_schema": self.parameter_schema,
        }
