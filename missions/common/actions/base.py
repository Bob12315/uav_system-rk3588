from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .result import ActionResult


class ActionModule(ABC):
    @abstractmethod
    def start(self, params: dict[str, Any] | None = None) -> None:
        ...

    @abstractmethod
    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...
