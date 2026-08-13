from __future__ import annotations

import copy
import threading
import time
from typing import Any, Mapping


class ApplicationStateStore:
    """Single thread-safe source of the current runtime state snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._updated_at = 0.0
        self._snapshot: dict[str, Any] = {}

    def replace(self, snapshot: Mapping[str, Any], *, updated_at: float | None = None) -> int:
        safe = copy.deepcopy(dict(snapshot))
        with self._lock:
            self._sequence += 1
            self._updated_at = time.time() if updated_at is None else float(updated_at)
            safe["state_sequence"] = self._sequence
            safe["state_updated_at"] = self._updated_at
            self._snapshot = safe
            return self._sequence

    def read(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._snapshot)

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence
