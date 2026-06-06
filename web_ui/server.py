from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.app_config import ROOT_DIR, UiConfig
from uav_ui.completion_catalog import COMMAND_COMPLETIONS
from web_ui.audit import AuditLog
from web_ui.config_store import ConfigStore


class CommandRequest(BaseModel):
    command: str
    source: str = "CLI"


class ConfigWriteRequest(BaseModel):
    content: str
    action: str = "save"


class ActionStartRequest(BaseModel):
    name: str
    params: dict = Field(default_factory=dict)
    send_actions: bool | None = None


class WebUiServer:
    def __init__(self, runner, config: UiConfig) -> None:
        self.runner = runner
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        app = create_app(self.runner, self.config)
        uvicorn_config = uvicorn.Config(
            app,
            host=self.config.web_host,
            port=self.config.web_port,
            log_level="warning",
        )
        self.server = uvicorn.Server(uvicorn_config)
        self.thread = threading.Thread(target=self.server.run, name="WebUiServer", daemon=True)
        self.thread.start()
        self.logger.info("web UI starting at http://%s:%s", self.config.web_host, self.config.web_port)

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)


def create_app(runner, config: UiConfig) -> FastAPI:
    app = FastAPI(title="UAV Web Control")
    audit = AuditLog(config.audit_log_path)
    store = ConfigStore(ROOT_DIR)
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/api/status")
    def status():
        return runner.web_status_snapshot()

    @app.get("/api/missions")
    def missions():
        return runner.web_missions()

    @app.get("/api/commands/completions")
    def completions():
        commands = set(COMMAND_COMPLETIONS)
        for mission in runner.web_missions():
            commands.add(f"mission switch {mission['name']}")
            for stage in mission.get("stage_modes", []):
                commands.add(f"mission stage {stage}")
        return {"commands": sorted(commands, key=str.lower)}

    @app.post("/api/commands/execute")
    def execute(request: CommandRequest):
        result = runner.web_execute_command(request.command)
        audit.append(request.source.upper(), request.command, result.ok, result.message)
        return {"ok": result.ok, "message": result.message}

    @app.get("/api/audit")
    def read_audit(limit: int = 100):
        return audit.read_latest(min(max(limit, 1), 500))

    @app.get("/api/events")
    def events():
        return runner.web_status_snapshot().get("events", [])

    @app.get("/api/actions/list")
    def action_list():
        try:
            return {"ok": True, "actions": list(getattr(runner, "action_lab_specs", []))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/actions/status")
    def action_status():
        try:
            status = runner.action_lab_tick()
            action_lab = runner.action_lab_status_payload()
            action_lab["enabled"] = bool(getattr(runner, "action_lab_enabled", False))
            action_lab["status"] = status
            return {"ok": True, "action_lab": action_lab}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/actions/start")
    def action_start(request: ActionStartRequest):
        try:
            result = runner.action_lab_start_action(
                request.name,
                dict(request.params or {}),
                send_actions=request.send_actions,
            )
            action_lab = runner.action_lab_status_payload()
            return {
                "ok": True,
                "result": result.to_dict(),
                "status": action_lab["status"],
                "action_lab": action_lab,
                "send_actions_effective": action_lab["send_actions_effective"],
                "note": action_lab["note"],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/actions/stop")
    def action_stop():
        try:
            result = runner.action_lab_stop_action()
            action_lab = runner.action_lab_status_payload()
            return {
                "ok": True,
                "result": result.to_dict(),
                "status": action_lab["status"],
                "action_lab": action_lab,
                "send_actions_effective": action_lab["send_actions_effective"],
                "note": action_lab["note"],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/actions/reset")
    def action_reset():
        try:
            result = runner.action_lab_reset_action()
            action_lab = runner.action_lab_status_payload()
            return {
                "ok": True,
                "result": result.to_dict(),
                "status": action_lab["status"],
                "action_lab": action_lab,
                "send_actions_effective": action_lab["send_actions_effective"],
                "note": action_lab["note"],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/yolo/stream")
    def yolo_stream():
        port = 8081
        try:
            data = yaml.safe_load((ROOT_DIR / "config" / "yolo.yaml").read_text(encoding="utf-8")) or {}
            web_stream = data.get("web_stream", {})
            if isinstance(web_stream, dict):
                port = int(web_stream.get("port", port))
        except (OSError, ValueError, yaml.YAMLError):
            pass
        return {"port": port, "path": "/video/yolo.mjpeg"}

    @app.post("/api/yolo/target/{action}")
    def yolo_target_action(action: str, track_id: int | None = None):
        commands = {
            "unlock": "target unlock",
            "next": "target next",
            "prev": "target prev",
        }
        command = f"target lock {track_id}" if action == "lock" and track_id is not None else commands.get(action)
        if command is None:
            raise HTTPException(status_code=400, detail="invalid target action or missing track_id")
        result = runner.web_execute_command(command)
        audit.append("TARGET", command, result.ok, result.message)
        return {"ok": result.ok, "message": result.message}

    @app.get("/api/config/files")
    def config_files():
        return store.files()

    @app.get("/api/config/file")
    def config_file(path: str):
        try:
            return store.read(path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/config/file")
    def save_config(path: str, request: ConfigWriteRequest):
        try:
            diff = store.save(path, request.content)
            result = _apply_config_action(runner, path, request.action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit.append("CONFIG", f"{request.action} {path}", result["ok"], result["message"])
        return {"diff": diff, **result}

    @app.post("/api/config/restore")
    def restore_config(path: str, action: str = "save"):
        try:
            diff = store.restore(path)
            result = _apply_config_action(runner, path, action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit.append("CONFIG", f"restore {path}", result["ok"], result["message"])
        return {"diff": diff, **result}

    @app.post("/api/services/telemetry/reconnect")
    def reconnect_telemetry():
        result = runner.reconnect_telemetry_from_saved_config()
        audit.append("SERVICE", "telemetry reconnect", result.ok, result.message)
        return {"ok": result.ok, "message": result.message}

    @app.post("/api/services/{service}/restart")
    def restart_service(service: str):
        result = runner.restart_external_service(service)
        audit.append("SERVICE", f"{service} restart", result.ok, result.message)
        return {"ok": result.ok, "message": result.message}

    @app.websocket("/ws/status")
    async def status_socket(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(runner.web_status_snapshot())
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


def _apply_config_action(runner, path: str, action: str) -> dict[str, object]:
    if action == "apply" and path.startswith("missions/"):
        result = runner.apply_active_mission_config(path)
    elif action == "reconnect" and path == "config/telemetry.yaml":
        result = runner.reconnect_telemetry_from_saved_config()
    elif action == "restart" and path == "config/yolo.yaml":
        result = runner.restart_external_service("yolo")
    elif action == "restart" and path == "config/app.yaml":
        result = runner.restart_external_service("app")
    else:
        return {"ok": True, "message": "configuration saved"}
    return {"ok": result.ok, "message": result.message}
