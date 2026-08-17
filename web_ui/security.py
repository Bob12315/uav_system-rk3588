from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse

from web_ui.audit import AuditLog, bind_audit_request_context


SESSION_COOKIE = "uav_session"
CSRF_HEADER = "x-uav-csrf"


def _loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1", "[::1]"}


@dataclass(frozen=True, slots=True)
class Identity:
    operator: str
    role: str = "operator"


@dataclass(slots=True)
class _Session:
    identity: Identity
    csrf_token: str
    expires_monotonic: float


class _RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], list[float]] = {}

    def allow(self, key: str, operation: str, *, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        marker = (key, operation)
        with self._lock:
            events = [value for value in self._events.get(marker, []) if now - value <= window_s]
            if len(events) >= limit:
                self._events[marker] = events
                return False
            events.append(now)
            self._events[marker] = events
            return True


class WebSecurity:
    def __init__(self, ui_config: object, audit: AuditLog) -> None:
        self.audit = audit
        testing_config = not hasattr(ui_config, "web_host")
        self.host = str(getattr(ui_config, "web_host", "127.0.0.1"))
        self.auth_required = bool(getattr(ui_config, "auth_required", not testing_config))
        self.credential_env = str(getattr(ui_config, "credential_env", "UAV_WEB_OPERATOR_PASSWORD"))
        self.credential_file_env = str(
            getattr(ui_config, "credential_file_env", "UAV_WEB_OPERATOR_PASSWORD_FILE")
        )
        self.session_ttl_sec = float(getattr(ui_config, "session_ttl_sec", 28800.0))
        configured_hosts = getattr(ui_config, "allowed_hosts", None)
        configured_origins = getattr(ui_config, "allowed_origins", None)
        self.allowed_hosts = {
            str(value).strip().lower().strip("[]")
            for value in (configured_hosts or {"127.0.0.1", "localhost", "::1"})
        }
        if testing_config:
            self.allowed_hosts.add("testserver")
        self.allowed_origins = {str(value).rstrip("/") for value in (configured_origins or ())}
        self.security_events = AuditLog(
            str(getattr(ui_config, "security_event_log_path", "runtime/logs/web_ui/security.jsonl"))
        )
        self._password = self._load_password()
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._rate = _RateLimiter()

    def validate_startup(self) -> None:
        if self.session_ttl_sec <= 0:
            raise RuntimeError("Web UI session_ttl_sec must be positive")
        if "*" in self.allowed_hosts or "*" in self.allowed_origins:
            raise RuntimeError("wildcard Web UI hosts/origins are not allowed")
        if self.auth_required and not self._password:
            raise RuntimeError(
                "Web UI authentication requires operator credentials via "
                f"{self.credential_env} or {self.credential_file_env}"
            )
        if not _loopback_host(self.host) and not self.auth_required:
            raise RuntimeError("non-loopback Web UI cannot disable authentication")

    def login(self, password: str, source_address: str) -> tuple[str, str] | None:
        if not self._rate.allow(source_address, "login", limit=5, window_s=60.0):
            self.security_events.append(
                "WEB_SECURITY", "login", False, "rate_limited",
                source_address=source_address, reason="rate_limited",
            )
            raise RuntimeError("rate_limited")
        if not self._password or not secrets.compare_digest(password, self._password):
            self.security_events.append(
                "WEB_SECURITY", "login", False, "invalid_credentials",
                source_address=source_address, reason="invalid_credentials",
            )
            return None
        session_id = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = _Session(
                identity=Identity("operator"),
                csrf_token=csrf,
                expires_monotonic=time.monotonic() + self.session_ttl_sec,
            )
        self.security_events.append(
            "WEB_SECURITY", "login", True, "authenticated",
            operator="operator", source_address=source_address,
        )
        return session_id, csrf

    def logout(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._sessions.pop(session_id, None)

    def authenticate_request(self, request: Request) -> tuple[Identity | None, _Session | None]:
        session_id = request.cookies.get(SESSION_COOKIE)
        if session_id:
            session = self._get_session(session_id)
            if session is not None:
                return session.identity, session
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer ") and self._password:
            token = authorization[7:]
            if secrets.compare_digest(token, self._password):
                return Identity("operator"), None
        return None, None

    def authenticate_websocket(self, websocket: WebSocket) -> Identity | None:
        session_id = websocket.cookies.get(SESSION_COOKIE)
        session = self._get_session(session_id) if session_id else None
        return session.identity if session else None

    def middleware(self, services: object):
        security = self

        async def _middleware(request: Request, call_next):
            path = request.url.path
            method = request.method.upper()
            source_address = request.client.host if request.client else ""
            supplied_request_id = request.headers.get("x-request-id", "").strip()
            request_id = supplied_request_id if 0 < len(supplied_request_id) <= 128 else uuid.uuid4().hex
            supplied_correlation_id = request.headers.get("x-correlation-id", "").strip()
            correlation_id = (
                supplied_correlation_id
                if 0 < len(supplied_correlation_id) <= 128
                else request_id
            )
            request.state.request_id = request_id
            request.state.correlation_id = correlation_id
            bind_audit_request_context(
                request_id=request_id,
                correlation_id=correlation_id,
                source_address=source_address,
            )
            host = str(request.url.hostname or "").lower().strip("[]")
            if host and host not in security.allowed_hosts:
                security._audit_rejection(path, source_address, "host_not_allowed")
                return JSONResponse({"detail": "host not allowed"}, status_code=400)

            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in security.allowed_origins:
                security._audit_rejection(path, source_address, "origin_not_allowed")
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)

            modifying = method in {"POST", "PUT", "PATCH", "DELETE"}
            login_path = path == "/api/auth/login"
            identity: Identity | None = None
            session: _Session | None = None
            protected_read = path in {"/api/audit"}
            if security.auth_required and (modifying or protected_read) and not login_path:
                identity, session = security.authenticate_request(request)
                if identity is None:
                    security._audit_rejection(path, source_address, "authentication_required")
                    return JSONResponse({"detail": "authentication required"}, status_code=401)
                if modifying and session is not None:
                    csrf = request.headers.get(CSRF_HEADER, "")
                    if not csrf or not secrets.compare_digest(csrf, session.csrf_token):
                        security._audit_rejection(
                            path, source_address, "csrf_failed", operator=identity.operator
                        )
                        return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
                if path in {
                    "/api/actions/start",
                    "/api/action-mission/start",
                    "/api/control/send",
                    "/api/telemetry/source",
                } and not security._rate.allow(source_address, path, limit=20, window_s=60.0):
                    security._audit_rejection(path, source_address, "rate_limited", operator=identity.operator)
                    return JSONResponse({"detail": "rate limited"}, status_code=429)
            request.state.identity = identity or Identity("anonymous", "observer")
            bind_audit_request_context(
                request_id=request_id,
                correlation_id=correlation_id,
                source_address=source_address,
                actor_id=request.state.identity.operator,
                actor_role=request.state.identity.role,
            )
            authorization_getter = getattr(services, "authorization_snapshot", None)
            before_auth = authorization_getter() if callable(authorization_getter) else None
            mission_control = getattr(services, "mission_control", None)
            source_getter = getattr(mission_control, "active_telemetry_source", None)
            before_source = source_getter() if callable(source_getter) else None
            response = await call_next(request)
            if modifying and not login_path:
                after_auth = authorization_getter() if callable(authorization_getter) else None
                run_auth = after_auth or before_auth
                target_source = source_getter() if callable(source_getter) else before_source
                security.audit.append(
                    "WEB",
                    f"{method} {path}",
                    response.status_code < 400,
                    f"HTTP {response.status_code}",
                    operator=request.state.identity.operator,
                    source_address=source_address,
                    run_id=getattr(run_auth, "run_id", None),
                    target_source=target_source,
                    reason=f"http_{response.status_code}",
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
            return response

        return _middleware

    def _get_session(self, session_id: str) -> _Session | None:
        now = time.monotonic()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.expires_monotonic <= now:
                self._sessions.pop(session_id, None)
                return None
            return session

    def _load_password(self) -> str | None:
        direct = os.environ.get(self.credential_env)
        if direct:
            return direct
        file_name = os.environ.get(self.credential_file_env)
        if not file_name:
            return None
        path = Path(file_name).expanduser()
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise RuntimeError("Web credential file must not be group/world accessible")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError("Web credential file is empty")
        return value

    def _audit_rejection(
        self,
        action: str,
        source_address: str,
        reason: str,
        *,
        operator: str = "unknown",
    ) -> None:
        self.security_events.append(
            "WEB_SECURITY",
            action,
            False,
            reason,
            operator=operator,
            source_address=source_address,
            reason=reason,
        )
