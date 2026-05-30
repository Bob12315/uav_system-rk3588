from __future__ import annotations

from pathlib import Path

import pytest

from app.app_config import UiConfig
from telemetry_link.command_dispatcher import CommandResult
from web_ui.audit import AuditLog
from web_ui.config_store import ConfigStore
from web_ui.server import create_app


def test_config_store_saves_and_restores_approved_yaml(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "yolo_app").mkdir()
    (tmp_path / "missions" / "demo").mkdir(parents=True)
    app_file = tmp_path / "config" / "app.yaml"
    app_file.write_text("runtime:\n  loop_hz: 20\n", encoding="utf-8")
    (tmp_path / "config" / "telemetry.yaml").write_text("value: 1\n", encoding="utf-8")
    (tmp_path / "yolo_app" / "config.yaml").write_text("value: 1\n", encoding="utf-8")
    (tmp_path / "missions" / "demo" / "config.yaml").write_text("name: demo\n", encoding="utf-8")
    store = ConfigStore(tmp_path)

    diff = store.save("config/app.yaml", "runtime:\n  loop_hz: 30\n")

    assert "loop_hz: 30" in diff
    assert app_file.with_suffix(".yaml.bak").read_text(encoding="utf-8") == "runtime:\n  loop_hz: 20\n"

    store.restore("config/app.yaml")

    assert app_file.read_text(encoding="utf-8") == "runtime:\n  loop_hz: 20\n"


def test_config_store_rejects_arbitrary_paths_and_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "yolo_app").mkdir()
    (tmp_path / "missions").mkdir()
    (tmp_path / "config" / "app.yaml").write_text("runtime: {}\n", encoding="utf-8")
    (tmp_path / "config" / "telemetry.yaml").write_text("value: 1\n", encoding="utf-8")
    (tmp_path / "yolo_app" / "config.yaml").write_text("value: 1\n", encoding="utf-8")
    store = ConfigStore(tmp_path)

    with pytest.raises(ValueError):
        store.resolve("../secret.yaml")
    with pytest.raises(ValueError):
        store.save("config/app.yaml", "- invalid root\n")


def test_audit_log_is_persistent(tmp_path: Path) -> None:
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    log.append("BUTTON", "control send off", True, "disabled")

    entries = AuditLog(str(tmp_path / "audit.jsonl")).read_latest()

    assert entries[0]["source"] == "BUTTON"
    assert entries[0]["action"] == "control send off"


class _FakeRunner:
    def web_status_snapshot(self):
        return {"mission": "visual_tracking", "events": []}

    def web_missions(self):
        return [{"name": "visual_tracking", "active": True}]

    def web_execute_command(self, command: str):
        return CommandResult(True, f"sent: {command}")

    def reconnect_telemetry_from_saved_config(self):
        return CommandResult(True, "reconnecting")

    def restart_external_service(self, service: str):
        return CommandResult(True, f"restart {service}")

    def apply_active_mission_config(self, _path: str):
        return CommandResult(True, "applied")


def test_web_api_executes_command_and_records_audit(tmp_path: Path) -> None:
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    app = create_app(
        _FakeRunner(),
        UiConfig(True, False, "127.0.0.1", 8080, str(tmp_path / "audit.jsonl")),
    )
    client = TestClient(app)

    response = client.post("/api/commands/execute", json={"command": "target next", "source": "BUTTON"})

    assert response.json()["ok"] is True
    audit = client.get("/api/audit").json()
    assert audit[0]["action"] == "target next"
