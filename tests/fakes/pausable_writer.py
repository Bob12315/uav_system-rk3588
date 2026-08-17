from __future__ import annotations

from threading import Event, Lock
from typing import Any, Callable


class PausableWriter:
    """Writer with named deterministic interleaving checkpoints."""

    CHECKPOINTS = (
        "after_dequeue",
        "before_final_check",
        "after_final_check",
        "before_write",
        "after_write",
    )

    def __init__(self) -> None:
        self.writes: list[Any] = []
        self._entered = {name: Event() for name in self.CHECKPOINTS}
        self._released = {name: Event() for name in self.CHECKPOINTS}
        for event in self._released.values():
            event.set()
        self._lock = Lock()

    def pause_at(self, checkpoint: str) -> None:
        self._event(self._released, checkpoint).clear()
        self._event(self._entered, checkpoint).clear()

    def release(self, checkpoint: str) -> None:
        self._event(self._released, checkpoint).set()

    def wait_until(self, checkpoint: str, timeout: float = 1.0) -> bool:
        return self._event(self._entered, checkpoint).wait(timeout)

    def checkpoint(self, name: str) -> None:
        self._event(self._entered, name).set()
        if not self._event(self._released, name).wait(5.0):
            raise TimeoutError(f"checkpoint not released: {name}")

    def write(self, value: Any, *, final_check: Callable[[], bool] | None = None) -> bool:
        if final_check is not None:
            self.checkpoint("after_dequeue")
            self.checkpoint("before_final_check")
            allowed = bool(final_check())
            self.checkpoint("after_final_check")
            if not allowed:
                return False
            self.checkpoint("before_write")
        with self._lock:
            self.writes.append(value)
        if final_check is not None:
            self.checkpoint("after_write")
        return True

    @staticmethod
    def _event(events: dict[str, Event], name: str) -> Event:
        try:
            return events[name]
        except KeyError as exc:
            raise ValueError(f"unknown checkpoint: {name}") from exc
