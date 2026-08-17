from __future__ import annotations

import threading
import uuid

from contracts.core.input_state import SendGateSnapshot
from contracts.platform.common import ResourceVersion, SendGeneration

from .execution_fence_authority import CoreExecutionFenceAuthority


class SystemSendState:
    def __init__(self, fence: CoreExecutionFenceAuthority) -> None:
        self._lock = threading.Lock()
        self._fence = fence
        self._enabled = False
        self._version = ResourceVersion(uuid.uuid4().hex, 0)

    def snapshot(self) -> SendGateSnapshot:
        with self._lock:
            return SendGateSnapshot(self._enabled, self._fence.snapshot().send_generation, self._version)

    def set(self, enabled: bool, expected_version: ResourceVersion, now_ns: int) -> SendGateSnapshot:
        with self._lock:
            if expected_version != self._version:
                raise ValueError("send gate resource version mismatch")
            if enabled == self._enabled:
                return SendGateSnapshot(self._enabled, self._fence.snapshot().send_generation, self._version)
            self._enabled = enabled
            fence = self._fence.set_send(enabled, now_ns)
            self._version = self._version.next()
            return SendGateSnapshot(enabled, SendGeneration(fence.send_generation), self._version)

    def force_off(self, now_ns: int) -> SendGateSnapshot:
        with self._lock:
            self._enabled = False
            fence = self._fence.set_send(False, now_ns, force_generation=True)
            self._version = self._version.next()
            return SendGateSnapshot(False, fence.send_generation, self._version)

    # Temporary outer compatibility.  It delegates to the same authority and
    # must be removed with the PA Web compatibility routes.
    def set_send_commands(self, enabled: bool) -> SendGateSnapshot:
        import time

        return self.set(enabled, self.snapshot().version, time.monotonic_ns())
