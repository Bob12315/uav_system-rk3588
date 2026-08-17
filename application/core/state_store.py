from __future__ import annotations

import threading

from contracts.core.cycle import CoreCycleQueryPort, CoreCycleSnapshot
from contracts.core.input_state import RuntimeInputQueryPort, RuntimeInputSnapshot


class RuntimeInputStore(RuntimeInputQueryPort):
    """Single-writer immutable-reference store; readers never observe a partial cut."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._current: RuntimeInputSnapshot | None = None

    def publish(self, snapshot: RuntimeInputSnapshot) -> None:
        with self._condition:
            current = self._current
            if current is not None:
                if snapshot.ref.publication_version.generation_id == current.ref.publication_version.generation_id:
                    if snapshot.ref.publication_version.revision <= current.ref.publication_version.revision:
                        raise ValueError("runtime snapshot publication must advance")
            self._current = snapshot
            self._condition.notify_all()

    def current(self) -> RuntimeInputSnapshot | None:
        with self._condition:
            return self._current

    def wait_next(self, revision: int, timeout_s: float) -> RuntimeInputSnapshot | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._current is not None
                and self._current.ref.publication_version.revision > revision,
                timeout=max(0.0, timeout_s),
            )
            return self._current


class CoreCycleStore(CoreCycleQueryPort):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: CoreCycleSnapshot | None = None

    def publish(self, snapshot: CoreCycleSnapshot) -> None:
        with self._lock:
            current = self._current
            if current is not None and snapshot.correlation.scheduler_session_id == current.correlation.scheduler_session_id:
                if snapshot.correlation.tick_sequence <= current.correlation.tick_sequence:
                    raise ValueError("core cycle sequence must advance")
            self._current = snapshot

    def current(self) -> CoreCycleSnapshot | None:
        with self._lock:
            return self._current
