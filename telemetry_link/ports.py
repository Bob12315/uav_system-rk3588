"""Narrow state/read and command/write adapters around LinkManager."""
from __future__ import annotations

from typing import Callable


class VehicleStateAdapter:
    def __init__(self, provider: Callable[[], object | None]) -> None:
        self._provider = provider

    def _link(self):
        return self._provider()

    def get_active_source(self) -> str:
        link = self._link()
        return str(link.get_active_source()) if link is not None else "real"

    def switch_active_source(self, source: str) -> bool:
        link = self._link()
        return bool(link is not None and link.switch_active_source(source))

    def get_latest_drone_state(self):
        link = self._link()
        return link.get_latest_drone_state() if link is not None else None

    def get_latest_gimbal_state(self):
        link = self._link()
        return link.get_latest_gimbal_state() if link is not None else None

    def get_link_status(self):
        link = self._link()
        return link.get_link_status() if link is not None else None


class VehicleCommandAdapter:
    """Execution-only forwarding surface; no telemetry read methods."""

    def __init__(self, provider: Callable[[], object | None]) -> None:
        self._provider = provider

    def __getattr__(self, name: str):
        if name.startswith("get_") or name in {"switch_active_source", "start", "stop"}:
            raise AttributeError(name)
        link = self._provider()
        if link is None:
            raise AttributeError(name)
        return getattr(link, name)
