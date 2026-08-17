from __future__ import annotations

from collections import deque


class FakeUdpPeer:
    """Socket-free datagram peer with deterministic loss, duplication and restart."""

    def __init__(self, *, session_id: str = "session-1") -> None:
        self.session_id = session_id
        self.inbound: deque[bytes] = deque()
        self.outbound: deque[bytes] = deque()
        self.drop_next = 0
        self.duplicate_next = 0
        self.reorder_next = False

    def send(self, payload: bytes) -> None:
        data = bytes(payload)
        if self.drop_next:
            self.drop_next -= 1
            return
        copies = 2 if self.duplicate_next else 1
        self.duplicate_next = max(0, self.duplicate_next - 1)
        for _ in range(copies):
            if self.reorder_next:
                self.outbound.appendleft(data)
            else:
                self.outbound.append(data)
        self.reorder_next = False

    def inject(self, payload: bytes) -> None:
        self.inbound.append(bytes(payload))

    def receive(self) -> bytes | None:
        return self.inbound.popleft() if self.inbound else None

    def restart(self, session_id: str) -> None:
        self.session_id = session_id
        self.inbound.clear()
        self.outbound.clear()
