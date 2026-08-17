from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from contracts.platform.common import SchemaVersion
from contracts.platform.observability import AuditEntry
from observability.jsonl_audit_adapter import JsonlAuditAdapter, sanitize_detail


_request_audit_context: ContextVar[dict[str, str] | None] = ContextVar(
    "request_audit_context", default=None
)


def bind_audit_request_context(*, request_id: str, correlation_id: str,
                               source_address: str, actor_id: str = "anonymous",
                               actor_role: str = "observer") -> None:
    _request_audit_context.set({
        "request_id": request_id,
        "correlation_id": correlation_id,
        "source_address": source_address,
        "actor_id": actor_id,
        "actor_role": actor_role,
    })


class AuditLog:
    """Legacy Web projection over the platform audit adapter.

    Web code no longer owns JSONL I/O.  Append acceptance is independent of
    the already-decided business result.
    """

    def __init__(self, path: str) -> None:
        self._adapter = JsonlAuditAdapter(path)

    @property
    def path(self):
        return self._adapter.path

    def append(self, source: str, action: str, ok: bool, message: str, *,
               operator: str = "unknown", actor_role: str = "operator",
               source_address: str = "", run_id: str | None = None,
               target_source: str | None = None, reason: str = "",
               request_id: str | None = None, correlation_id: str | None = None,
               resource: str = "", detail: dict[str, object] | None = None) -> dict[str, object]:
        context = _request_audit_context.get() or {}
        if operator == "unknown":
            operator = context.get("actor_id", operator)
        if actor_role == "operator" and context.get("actor_role"):
            actor_role = context["actor_role"]
        source_address = source_address or context.get("source_address", "")
        request_id = request_id or context.get("request_id")
        correlation_id = correlation_id or context.get("correlation_id") or request_id
        entry = AuditEntry(
            SchemaVersion(1, 0), uuid.uuid4().hex, datetime.now(timezone.utc), operator,
            actor_role, source_address, request_id, correlation_id or request_id,
            action, resource or source, "allowed" if ok else "rejected",
            reason or message, run_id, target_source,
            sanitize_detail({"message": message, **(detail or {})}),
        )
        receipt = self._adapter.append(entry)
        return {
            "timestamp": entry.timestamp_utc.timestamp(), "source": source, "action": action,
            "ok": bool(ok), "message": message, "operator": operator,
            "source_address": source_address, "run_id": run_id, "target_source": target_source,
            "operation_type": action, "result": "allowed" if ok else "rejected",
            "reason": reason or message, "audit_id": entry.audit_id,
            "audit_disposition": receipt.disposition.value,
        }

    def read_latest(self, limit: int = 100) -> list[dict[str, object]]:
        page = self._adapter.latest(max(1, limit))
        return [{
            "timestamp": item.timestamp_utc.timestamp(), "source": item.resource,
            "action": item.operation, "ok": item.decision == "allowed",
            "message": item.sanitized_detail.get("message", item.reason_code),
            "operator": item.actor_id, "source_address": item.source_address,
            "run_id": item.run_id, "target_source": item.target_source,
            "operation_type": item.operation, "result": item.decision,
            "reason": item.reason_code, "audit_id": item.audit_id,
            "request_id": item.request_id, "correlation_id": item.correlation_id,
        } for item in reversed(page.items)]

    def health(self) -> dict[str, object]:
        return {"write_failures": self._adapter.failures, "dropped": self._adapter.dropped,
                "last_error": self._adapter.last_error}

    def close(self) -> None:
        self._adapter.close()
