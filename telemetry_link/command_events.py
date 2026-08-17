from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Condition


@dataclass(frozen=True, slots=True)
class CommandEvent:
    cursor: int
    command_id: str
    event_type: str
    monotonic_ns: int
    detail: dict[str, object]


class CommandEventRegistry:
    def __init__(self, capacity: int = 1000) -> None:
        self._events: deque[CommandEvent] = deque(maxlen=capacity)
        self._cursor = 0
        self._condition = Condition()

    def append(self, command_id: str, event_type: str, monotonic_ns: int, **detail: object) -> CommandEvent:
        with self._condition:
            self._cursor += 1
            event = CommandEvent(self._cursor, command_id, event_type, monotonic_ns, dict(detail))
            self._events.append(event)
            self._condition.notify_all()
            return event

    def read_after(self, cursor: int, limit: int = 100) -> tuple[CommandEvent, ...]:
        with self._condition:
            return tuple(event for event in self._events if event.cursor > cursor)[:limit]
