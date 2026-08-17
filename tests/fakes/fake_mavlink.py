from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Condition
from typing import Any


@dataclass(frozen=True, slots=True)
class FakeMavlinkMessage:
    message_type: str
    sysid: int
    compid: int
    fields: dict[str, Any]


class FakeMavlink:
    """In-memory MAVLink message source with explicit identity and ACK fields."""

    def __init__(self) -> None:
        self._messages: deque[FakeMavlinkMessage] = deque()
        self._condition = Condition()

    def inject(self, message_type: str, *, sysid: int = 1, compid: int = 1, **fields: Any) -> FakeMavlinkMessage:
        message = FakeMavlinkMessage(message_type.upper(), sysid, compid, dict(fields))
        with self._condition:
            self._messages.append(message)
            self._condition.notify_all()
        return message

    def inject_heartbeat(self, *, sysid: int = 1, compid: int = 1, **fields: Any) -> FakeMavlinkMessage:
        return self.inject("HEARTBEAT", sysid=sysid, compid=compid, **fields)

    def inject_ack(
        self,
        command: int,
        result: int,
        *,
        sysid: int = 1,
        compid: int = 1,
        progress: int | None = None,
    ) -> FakeMavlinkMessage:
        fields: dict[str, Any] = {"command": command, "result": result}
        if progress is not None:
            fields["progress"] = progress
        return self.inject("COMMAND_ACK", sysid=sysid, compid=compid, **fields)

    def receive(self, *, message_type: str | None = None) -> FakeMavlinkMessage | None:
        wanted = message_type.upper() if message_type else None
        with self._condition:
            for index, message in enumerate(self._messages):
                if wanted is None or message.message_type == wanted:
                    del self._messages[index]
                    return message
        return None

    def __len__(self) -> int:
        with self._condition:
            return len(self._messages)
