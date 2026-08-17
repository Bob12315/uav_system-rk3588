from __future__ import annotations

import json
import logging
import queue
import re
import threading
from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from contracts.platform.common import SchemaVersion
from contracts.platform.observability import AuditAppendReceipt, AuditEntry, AuditPage, SinkDisposition

_SENSITIVE = ("password", "token", "secret", "cookie", "authorization", "credential")
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|token|secret|cookie|authorization|credential)\b(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def sanitize_detail(value):
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if any(word in str(key).lower() for word in _SENSITIVE)
                else sanitize_detail(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [sanitize_detail(item) for item in value]
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", _INLINE_SECRET.sub(r"\1\2[REDACTED]", value))
    if isinstance(value, (int, float, bool)) or value is None: return value
    return str(value)


class JsonlAuditAdapter:
    def __init__(self, path: str | Path, *, capacity: int = 512,
                 receipt_capacity: int = 2048) -> None:
        self.path = Path(path).resolve()
        self._queue: queue.Queue[AuditEntry | None] = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._receipts: dict[str, AuditAppendReceipt] = {}
        self._receipt_capacity = max(1, int(receipt_capacity))
        self._closed = False
        self.failures = 0
        self.dropped = 0
        self.last_error: str | None = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._thread = threading.Thread(target=self._run, name="AuditJsonlWriter", daemon=True)
        self._thread.start()

    def append(self, entry: AuditEntry) -> AuditAppendReceipt:
        clean = AuditEntry(entry.schema, entry.audit_id, entry.timestamp_utc, entry.actor_id,
            entry.actor_role, entry.source_address, entry.request_id, entry.correlation_id,
            entry.operation, entry.resource, entry.decision, entry.reason_code, entry.run_id,
            entry.target_source, sanitize_detail(dict(entry.sanitized_detail)))
        with self._lock:
            closed = self._closed
        if closed:
            receipt = AuditAppendReceipt(entry.audit_id, SinkDisposition.FAILED, "sink_closed")
        else:
            try:
                self._queue.put_nowait(clean)
                receipt = AuditAppendReceipt(entry.audit_id, SinkDisposition.ACCEPTED, "accepted")
            except queue.Full:
                self.dropped += 1
                receipt = AuditAppendReceipt(entry.audit_id, SinkDisposition.DROPPED, "queue_full")
        self._remember_receipt(receipt)
        return receipt

    def receipt(self, audit_id: str) -> AuditAppendReceipt | None:
        with self._lock:
            return self._receipts.get(audit_id)

    def _remember_receipt(self, receipt: AuditAppendReceipt) -> None:
        with self._lock:
            self._receipts.pop(receipt.audit_id, None)
            self._receipts[receipt.audit_id] = receipt
            while len(self._receipts) > self._receipt_capacity:
                self._receipts.pop(next(iter(self._receipts)))

    def _run(self) -> None:
        while True:
            entry = self._queue.get()
            if entry is None: return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                record = asdict(entry)
                record["schema"] = {"major": entry.schema.major, "minor": entry.schema.minor}
                record["timestamp_utc"] = entry.timestamp_utc.isoformat()
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                self._remember_receipt(AuditAppendReceipt(entry.audit_id, SinkDisposition.PERSISTED, "persisted"))
            except Exception as exc:
                self.failures += 1; self.last_error = str(exc)
                self._remember_receipt(AuditAppendReceipt(entry.audit_id, SinkDisposition.FAILED, "write_failed"))
                self.logger.error("audit sink failure: %s", exc, exc_info=True)

    def latest(self, limit: int, cursor: str | None = None) -> AuditPage:
        limit = max(0, min(int(limit), 1000))
        if not self.path.exists() or limit == 0:
            return AuditPage((), None)
        after = max(0, int(cursor or 0))
        bounded = deque(maxlen=max(1, limit + after))
        # Memory is bounded by the requested page/cursor window.  The adapter
        # never materializes the complete JSONL file.
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                bounded.append(line)
        lines = list(bounded)
        end = len(lines) - min(after, len(lines))
        start = max(0, end - limit)
        entries = []
        for line in lines[start:end]:
            try:
                value = json.loads(line); schema = value.pop("schema"); value["schema"] = SchemaVersion(**schema)
                value["timestamp_utc"] = datetime.fromisoformat(value["timestamp_utc"])
                entries.append(AuditEntry(**value))
            except Exception: continue
        return AuditPage(tuple(entries), str(after + len(entries)) if entries else None)

    def close(self, timeout_s: float = 1.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._queue.put(None, timeout=max(0.0, timeout_s))
        except queue.Full:
            self.last_error = "audit close timed out with a full queue"
            return
        self._thread.join(max(0.0, timeout_s))
