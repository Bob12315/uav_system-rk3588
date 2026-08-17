from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from contracts.platform.observability import (
    CycleRecordEnvelope, DrainState, RecordDisposition, RecordReceipt, RecorderSegmentMetadata,
    RecorderStart, RecorderStatus, RetentionPolicy,
)


@dataclass(frozen=True)
class _Barrier:
    kind: str
    reason: str
    event: threading.Event


class AsyncCycleRecorder:
    def __init__(self, store: object, *, capacity: int = 256, keep_files: int = 20,
                 shutdown_flush_timeout_s: float = 1.0) -> None:
        self.store = store; self.capacity = max(1, capacity); self.keep_files = keep_files
        self.shutdown_flush_timeout_s = max(0.0, shutdown_flush_timeout_s)
        self._queue: queue.Queue[CycleRecordEnvelope | _Barrier] = queue.Queue(maxsize=self.capacity)
        self._lock = threading.RLock(); self._session_id: str | None = None
        self._state = DrainState.IDLE; self._persisted = 0; self._dropped = 0
        self._ranges: list[tuple[int, int]] = []; self._failures = 0; self._last_error: str | None = None
        self._thread = threading.Thread(target=self._run, name="CycleRecordWriter", daemon=True)
        self._sample_interval_ns = 0; self._last_sampled_ns: int | None = None
        self._thread.start()

    def start_session(self, request: RecorderStart) -> RecorderStatus:
        with self._lock:
            if self._state == DrainState.RECORDING: return self.status()
            self._session_id = uuid.uuid4().hex; self._state = DrainState.RECORDING
            session = self._session_id
            self._persisted = 0; self._dropped = 0; self._ranges = []
            self._failures = 0; self._last_error = None
            self._sample_interval_ns = 0 if request.sample_hz <= 0 else int(1_000_000_000 / request.sample_hz)
            self._last_sampled_ns = None
        self._start_request = request
        event = threading.Event(); self._offer_barrier(_Barrier("start", request.reason, event))
        if not event.wait(self.shutdown_flush_timeout_s):
            with self._lock:
                self._state = DrainState.PARTIAL
                self._last_error = "start_barrier_timeout"
        return self.status()

    def record(self, record: CycleRecordEnvelope) -> RecordReceipt:
        with self._lock:
            if self._state != DrainState.RECORDING or record.recorder_session_id != self._session_id:
                return RecordReceipt(RecordDisposition.REJECTED, record.sequence, "session_mismatch")
            if (self._sample_interval_ns and self._last_sampled_ns is not None
                    and record.sampled_at_monotonic_ns - self._last_sampled_ns < self._sample_interval_ns):
                return RecordReceipt(RecordDisposition.REJECTED, record.sequence, "sample_interval")
            self._last_sampled_ns = record.sampled_at_monotonic_ns
        disposition = RecordDisposition.ACCEPTED
        try: self._queue.put_nowait(record)
        except queue.Full:
            try: dropped = self._queue.get_nowait()
            except queue.Empty: return RecordReceipt(RecordDisposition.REJECTED, record.sequence, "queue_race")
            if isinstance(dropped, _Barrier):
                self._queue.put_nowait(dropped)
                return RecordReceipt(RecordDisposition.REJECTED, record.sequence, "barrier_pending")
            self._record_drop(dropped.sequence); self._queue.put_nowait(record)
            disposition = RecordDisposition.DROPPED_OLDEST
        return RecordReceipt(disposition, record.sequence, "accepted" if disposition == RecordDisposition.ACCEPTED else "drop_oldest")

    def stop_session(self, reason: str) -> RecorderStatus:
        with self._lock:
            if self._session_id is None: return self.status()
        event = threading.Event(); barrier = _Barrier("stop", reason, event)
        self._offer_barrier(barrier)
        if not event.wait(self.shutdown_flush_timeout_s):
            with self._lock: self._state = DrainState.PARTIAL
        return self.status()

    def status(self) -> RecorderStatus:
        with self._lock:
            return RecorderStatus(self._state, self._session_id, self._queue.qsize(), self._persisted,
                self._dropped, tuple(self._ranges), self._failures, self._last_error,
                getattr(self.store, "current_segment", None))

    def close(self) -> RecorderStatus:
        status = self.stop_session("shutdown")
        event=threading.Event(); self._offer_barrier(_Barrier("shutdown", "shutdown", event)); event.wait(self.shutdown_flush_timeout_s)
        self._thread.join(self.shutdown_flush_timeout_s)
        if self._thread.is_alive():
            with self._lock: self._state = DrainState.PARTIAL
        return self.status()

    def _offer_barrier(self, barrier: _Barrier) -> None:
        try: self._queue.put(barrier, timeout=self.shutdown_flush_timeout_s)
        except queue.Full:
            with self._lock: self._state = DrainState.PARTIAL; self._last_error = "barrier_queue_timeout"

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if isinstance(item, _Barrier):
                    if item.kind == "start":
                        request = getattr(self, "_start_request", RecorderStart(item.reason, 0.0))
                        self.store.open_segment(RecorderSegmentMetadata(str(self._session_id), datetime.now(timezone.utc), item.reason, request.sample_hz))
                        self.store.prune(RetentionPolicy(self.keep_files))
                    elif item.kind == "stop":
                        self._close_store()
                        with self._lock: self._state = DrainState.DRAINED
                    elif item.kind == "shutdown":
                        self._close_store(); item.event.set(); return
                    item.event.set(); continue
                previous_segment = getattr(self.store, "current_segment", None)
                self.store.append(item)
                if getattr(self.store, "current_segment", None) != previous_segment:
                    self.store.prune(RetentionPolicy(self.keep_files))
                with self._lock: self._persisted += 1
            except Exception as exc:
                with self._lock:
                    self._failures += 1; self._last_error = str(exc); self._state = DrainState.FAILED
                if isinstance(item, _Barrier): item.event.set()

    def _record_drop(self, sequence: int) -> None:
        with self._lock:
            self._dropped += 1
            if self._ranges and self._ranges[-1][1] + 1 == sequence:
                self._ranges[-1] = (self._ranges[-1][0], sequence)
            else: self._ranges.append((sequence, sequence))

    def _close_store(self) -> None:
        try: self.store.close_segment(self.status())
        except TypeError: self.store.close_segment()
        self.store.prune(RetentionPolicy(self.keep_files))
