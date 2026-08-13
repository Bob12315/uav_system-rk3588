from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SendStateSnapshot:
    send_commands: bool


class SystemSendState:
    """Thread-safe state for the only live runtime control switch: SEND."""

    def __init__(self, enabled: bool = False) -> None:
        self._lock = threading.Lock()
        self._enabled = bool(enabled)

    def snapshot(self) -> SendStateSnapshot:
        with self._lock:
            return SendStateSnapshot(send_commands=self._enabled)

    def set_send_commands(self, enabled: bool) -> SendStateSnapshot:
        with self._lock:
            self._enabled = bool(enabled)
            return SendStateSnapshot(send_commands=self._enabled)
