"""Shared dependencies injected into Web routers."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from application.web_services import WebServices
from web_ui.audit import AuditLog
from web_ui.config_store import ConfigStore
from web_ui.security import WebSecurity


@dataclass(frozen=True, slots=True)
class WebContext:
    services: WebServices
    audit: AuditLog
    security: WebSecurity
    config_store: ConfigStore

    def append_field_audit(self, action: str, result: dict, *, profile_id: str | None = None) -> None:
        try:
            state = result.get("state")
            error = result.get("error")
            pid = profile_id or result.get("profile_id") or "--"
            message = f"{action} profile_id={pid} state={state or '--'} error={error or '--'}"
            self.audit.append("FIELD_REFERENCE", action, result.get("ok") is True, message)
        except Exception:
            logging.getLogger("WebUiServer").warning(
                "field reference audit append failed", exc_info=True
            )
