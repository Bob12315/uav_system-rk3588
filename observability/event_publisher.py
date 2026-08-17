from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from dataclasses import dataclass

from contracts.platform.observability import (
    OperationalEvent, OperationalEventPage, PublishReceipt, SinkDisposition, SinkPublishReceipt,
)


class RecentEventSink:
    nonblocking_inline = True
    def __init__(self, capacity: int = 200) -> None:
        self.name = "recent"
        self._items: deque[tuple[int, OperationalEvent]] = deque(maxlen=max(1, capacity))
        self._lock = threading.Lock()
        self._sequence = 0

    def append(self, event: OperationalEvent) -> None:
        with self._lock:
            self._sequence += 1
            self._items.append((self._sequence, event))

    def latest(self, limit: int, cursor: str | None = None) -> OperationalEventPage:
        after = max(0, int(cursor or 0))
        with self._lock:
            items = tuple(self._items)
        selected_pairs = tuple(item for item in items if item[0] > after)[:max(0, limit)]
        selected = tuple(item[1] for item in selected_pairs)
        next_cursor = str(selected_pairs[-1][0]) if selected_pairs else None
        return OperationalEventPage(selected, next_cursor)


@dataclass
class _SinkWorker:
    name: str
    sink: object
    capacity: int

    def __post_init__(self) -> None:
        self.queue: queue.Queue[OperationalEvent | None] = queue.Queue(maxsize=self.capacity)
        self.failures = 0
        self.dropped = 0
        self.logger = logging.getLogger(f"EventSink.{self.name}")
        self.thread = threading.Thread(target=self._run, name=f"EventSink-{self.name}", daemon=True)
        self.thread.start()

    def offer(self, event: OperationalEvent) -> SinkPublishReceipt:
        if getattr(self.sink, "nonblocking_inline", False):
            try:
                self.sink.append(event)
                return SinkPublishReceipt(self.name, SinkDisposition.PERSISTED, "persisted_in_memory")
            except Exception:
                self.failures += 1
                return SinkPublishReceipt(self.name, SinkDisposition.FAILED, "sink_failed")
        try:
            self.queue.put_nowait(event)
            return SinkPublishReceipt(self.name, SinkDisposition.ACCEPTED, "accepted")
        except queue.Full:
            self.dropped += 1
            return SinkPublishReceipt(self.name, SinkDisposition.DROPPED, "queue_full")

    def _run(self) -> None:
        while True:
            event = self.queue.get()
            if event is None: return
            try: self.sink.append(event)
            except Exception as exc:
                self.failures += 1
                self.logger.error("event sink failure: %s", exc, exc_info=True)

    def close(self, timeout_s: float) -> None:
        try:
            self.queue.put(None, timeout=max(0.0, timeout_s))
        except queue.Full:
            self.logger.error("event sink close timed out with a full queue")
            return
        self.thread.join(max(0.0, timeout_s))


class IsolatedEventPublisher:
    def __init__(self, sinks: tuple[tuple[str, object, int], ...]) -> None:
        self._workers = tuple(_SinkWorker(name, sink, capacity) for name, sink, capacity in sinks)

    def publish(self, event: OperationalEvent) -> PublishReceipt:
        return PublishReceipt(event.event_id, tuple(worker.offer(event) for worker in self._workers))

    def health(self) -> dict[str, dict[str, int]]:
        return {worker.name: {"failures": worker.failures, "dropped": worker.dropped,
                             "queued": worker.queue.qsize()} for worker in self._workers}

    def close(self, timeout_s: float = 1.0) -> None:
        for worker in self._workers: worker.close(timeout_s)


class LegacyRecentEventSink:
    """Outermost compatibility projection for the existing Web status shape."""
    nonblocking_inline = True

    def __init__(self, target: deque[dict[str, object]]) -> None:
        self.target = target

    def append(self, event: OperationalEvent) -> None:
        self.target.appendleft({"timestamp": event.occurred_at_utc.timestamp(),
                                "level": event.severity, "message": event.payload.get("message", event.reason_code),
                                "event_id": event.event_id, "reason_code": event.reason_code})
