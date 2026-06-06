from __future__ import annotations

from .base import ActionModule


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, type[ActionModule]] = {}

    def register(
        self,
        name: str,
        action_cls: type[ActionModule],
        *,
        overwrite: bool = False,
    ) -> None:
        normalized = self._validate_name(name)
        if not isinstance(action_cls, type) or not issubclass(action_cls, ActionModule):
            raise TypeError("action_cls must be an ActionModule subclass")
        if normalized in self._actions and not overwrite:
            raise ValueError(f"action already registered: {normalized}")
        self._actions[normalized] = action_cls

    def get(self, name: str) -> type[ActionModule]:
        normalized = self._validate_name(name)
        try:
            return self._actions[normalized]
        except KeyError as exc:
            raise KeyError(f"unknown action: {normalized}") from exc

    def create(self, name: str) -> ActionModule:
        return self.get(name)()

    def list(self) -> list[str]:
        return sorted(self._actions)

    def clear(self) -> None:
        self._actions.clear()

    def _validate_name(self, name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("action name must be a non-empty string")
        return name.strip()


default_registry = ActionRegistry()
