from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()

    def append(
        self,
        source: str,
        action: str,
        ok: bool,
        message: str,
        *,
        operator: str = "unknown",
        source_address: str = "",
        run_id: str | None = None,
        target_source: str | None = None,
        reason: str = "",
    ) -> dict[str, object]:
        record: dict[str, object] = {
            "timestamp": time.time(),
            "source": source,
            "action": action,
            "ok": bool(ok),
            "message": message,
            "operator": operator,
            "source_address": source_address,
            "run_id": run_id,
            "target_source": target_source,
            "operation_type": action,
            "result": "allowed" if ok else "rejected",
            "reason": reason or message,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return record

    def read_latest(self, limit: int = 100) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[dict[str, object]] = []
        for line in reversed(lines[-max(1, limit) :]):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records
