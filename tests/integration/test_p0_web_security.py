from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from web_ui.server import create_app
from application.web_services import WebServices


class _Runner:
    def __init__(self) -> None:
        self.action_runtime = SimpleNamespace(dispatcher=SimpleNamespace(authorization=None))
        self.calls: list[tuple[object, ...]] = []

    def web_status_snapshot(self):
        return {"ok": True}

    def active_telemetry_source(self):
        return "sitl"

    def set_send(self, enabled: bool):
        self.calls.append(("send", enabled))
        return SimpleNamespace(ok=True, message="ok")


def _config(tmp_path):
    return SimpleNamespace(
        web_host="127.0.0.1",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        security_event_log_path=str(tmp_path / "security.jsonl"),
        auth_required=True,
        credential_env="UAV_WEB_OPERATOR_PASSWORD",
        credential_file_env="UAV_WEB_OPERATOR_PASSWORD_FILE",
        session_ttl_sec=60,
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _services(runner):
    unavailable = lambda *args: {"ok": False}
    return WebServices(
        system_control=runner,
        mission_control=runner,
        status_snapshot=runner.web_status_snapshot,
        field_reference_status=unavailable,
        field_reference_reset=unavailable,
        field_reference_freeze=unavailable,
        field_profile_list=unavailable,
        field_profile_get=unavailable,
        field_profile_validate=unavailable,
        runtime_sampling_start=unavailable,
        runtime_sampling_finalize=unavailable,
        runtime_sampling_cancel=unavailable,
        competition_sampling_start=unavailable,
        clear_localization=unavailable,
        action_specs=(),
        action_lab_enabled=False,
        authorization_snapshot=lambda: None,
    )


def _scenario(app):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.post("/api/control/send", json={"enabled": True})
            login = await client.post(
                "/api/auth/login",
                headers={"origin": "http://testserver"},
                json={"password": "test-only-operator-password"},
            )
            csrf = login.json()["csrf_token"]
            no_csrf = await client.post("/api/control/send", json={"enabled": True})
            allowed = await client.post(
                "/api/control/send",
                headers={"origin": "http://testserver", "x-uav-csrf": csrf},
                json={"enabled": True},
            )
            cross_origin = await client.post(
                "/api/control/send",
                headers={"origin": "http://attacker.invalid", "x-uav-csrf": csrf},
                json={"enabled": False},
            )
            return unauthenticated, login, no_csrf, allowed, cross_origin
    return asyncio.run(run())


def test_modifying_requests_require_auth_csrf_and_allowed_origin(tmp_path) -> None:
    runner = _Runner()
    app = create_app(_services(runner), _config(tmp_path))

    unauthenticated, login, no_csrf, allowed, cross_origin = _scenario(app)

    assert unauthenticated.status_code == 401
    assert login.status_code == 200
    assert no_csrf.status_code == 403
    assert allowed.status_code == 200
    assert cross_origin.status_code == 403
    assert runner.calls == [("send", True)]
    assert (tmp_path / "audit.jsonl").exists()
    assert (tmp_path / "security.jsonl").exists()
