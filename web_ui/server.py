from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictFloat

from app.mission_orchestrator import MissionActionStep
from app.app_config import ROOT_DIR, UiConfig
from app.completion_catalog import COMMAND_COMPLETIONS
from web_ui.audit import AuditLog
from web_ui.config_store import ConfigStore


class CommandRequest(BaseModel):
    command: str
    source: str = "CLI"


class ConfigWriteRequest(BaseModel):
    content: str
    action: str = "save"


class ManualHeadingRequest(BaseModel):
    yaw_deg: float


class ActionStartRequest(BaseModel):
    name: str
    params: dict = Field(default_factory=dict)
    send_actions: bool | None = None


class ActionMissionStepRequest(BaseModel):
    name: str
    params: dict = Field(default_factory=dict)
    save_as: str | None = None
    label: str | None = None
    on_failed: dict | None = None


class ActionMissionConfigureRequest(BaseModel):
    steps: list[ActionMissionStepRequest]


class ManualStepMoveRequest(BaseModel):
    direction: str
    step_m: float = Field(gt=0, le=5.0)


class RuntimeSamplingStartRequest(BaseModel):
    forward_marker_lat: StrictFloat
    forward_marker_lon: StrictFloat
    model_config = {"extra": "forbid"}


ACTION_MISSION_TEMPLATE_DIR = ROOT_DIR / "config" / "action_missions"
ACTION_MISSION_TEMPLATE_NAMES = {
    "drop_two_targets_v2": "投放任务 v2",
    "recon_inspect_5_targets_stepwise_v2": "侦察任务 v2",
    "rescue_2026_full_auto_v2": "完整流程 v2",
}


def _load_action_mission_template(name: str) -> dict:
    if name not in ACTION_MISSION_TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail="unknown action mission template")
    path = (ACTION_MISSION_TEMPLATE_DIR / f"{name}.json").resolve()
    template_dir = ACTION_MISSION_TEMPLATE_DIR.resolve()
    if path.parent != template_dir or path.suffix != ".json":
        raise HTTPException(status_code=404, detail="unknown action mission template")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="action mission template not found") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid template JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise HTTPException(status_code=500, detail="invalid action mission template structure")
    return data


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
    def _append_field_reference_audit(action: str, result: dict, *, pid: str | None = None):
        try:
            st = result.get("state")
            err = result.get("error")
            msg = f"{action} profile_id={pid or result.get('profile_id') or '--'} state={st or '--'} error={err or '--'}"
            audit.append("FIELD_REFERENCE", action, result.get("ok") is True, msg)
        except Exception:
            logging.getLogger("WebUiServer").warning("field reference audit append failed", exc_info=True)


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
            action_lab = runner.action_lab_status_payload()
            action_lab["enabled"] = bool(getattr(runner, "action_lab_enabled", False))
            return {"ok": True, "action_lab": action_lab}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/actions/start")
    def action_start(request: ActionStartRequest):
        try:
            logging.getLogger("WebUiServer").info(
                "/api/actions/start action=%s send_actions=%s",
                request.name,
                request.send_actions,
            )
            result = runner.action_lab_start_action(
                request.name,
                dict(request.params or {}),
                send_actions=request.send_actions,
            )
            if not result.failed:
                runner.action_lab_tick()
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

    @app.get("/api/action-mission/status")
    def action_mission_status():
        try:
            return {"ok": True, "action_mission": runner.action_mission_status_payload()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/action-mission/templates")
    def action_mission_templates():
        templates = []
        for name, label in ACTION_MISSION_TEMPLATE_NAMES.items():
            data = _load_action_mission_template(name)
            templates.append(
                {
                    "name": name,
                    "label": label,
                    "path": f"config/action_missions/{name}.json",
                    "description": str(data.get("description") or ""),
                    "step_count": len(data.get("steps") or []),
                }
            )
        return {"ok": True, "templates": templates}

    @app.get("/api/action-mission/template/{name}")
    def action_mission_template(name: str):
        template = _load_action_mission_template(name)
        return {"ok": True, "template": template}

    @app.post("/api/action-mission/configure")
    def action_mission_configure(request: ActionMissionConfigureRequest):
        try:
            runner.configure_action_mission([
                MissionActionStep(
                    step.name,
                    dict(step.params or {}),
                    save_as=step.save_as,
                    label=step.label,
                    on_failed=step.on_failed,
                )
                for step in request.steps
            ])
            return {"ok": True, "action_mission": runner.action_mission_status_payload()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/action-mission/start")
    def action_mission_start():
        try:
            return {"ok": True, "action_mission": runner.action_mission_start()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/action-mission/stop")
    def action_mission_stop():
        try:
            return {"ok": True, "action_mission": runner.action_mission_stop()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/action-mission/reset")
    def action_mission_reset():
        try:
            return {"ok": True, "action_mission": runner.action_mission_reset()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/action-mission/tick")
    def action_mission_tick():
        try:
            return {"ok": True, "action_mission": runner.action_mission_tick()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/action-mission/skip-current")
    def action_mission_skip_current():
        try:
            result = runner.action_mission_skip_current()
            audit.append("ACTION_MISSION", "skip_current", True, result.get("reason", "skip_current"))
            return {"ok": True, "action_mission": result}
        except Exception as exc:
            audit.append("ACTION_MISSION", "skip_current", False, str(exc))
            return {"ok": False, "error": str(exc)}

    @app.post("/api/manual-step-move")
    def manual_step_move(request: ManualStepMoveRequest):
        try:
            result = runner.manual_step_move(request.direction, request.step_m)
            audit.append("MANUAL_STEP", f"{request.direction} {request.step_m}", result.ok, result.message)
            return {"ok": result.ok, "message": result.message}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    # -- deprecated: legacy field-heading confirm (removed, centerline-only) ---
    @app.post("/api/field-heading/confirm")
    def confirm_field_heading():
        raise HTTPException(status_code=410, detail="field-heading/confirm removed — use /api/field-profiles/{id}/bind-current")

    # ------------------------------------------------------------------
    # Field Reference API — centerline only
    # ------------------------------------------------------------------

    @app.get("/api/field-reference/status")
    def field_reference_status():
        try:
            return runner.field_reference_status()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # -- deprecated: marker/set/manual routes (removed, centerline-only) -----
    @app.post("/api/field-reference/mark-origin")
    def field_reference_mark_origin():
        raise HTTPException(status_code=410, detail="mark-origin removed — use /api/field-profiles/{id}/bind-current")

    @app.post("/api/field-reference/mark-forward")
    def field_reference_mark_forward():
        raise HTTPException(status_code=410, detail="mark-forward removed — use /api/field-profiles/{id}/bind-current")

    @app.post("/api/field-reference/use-current-yaw")
    def field_reference_use_current_yaw():
        raise HTTPException(status_code=410, detail="use-current-yaw removed — yaw is display-only with centerline profiles")

    @app.post("/api/field-reference/set-manual-heading")
    def field_reference_set_manual_heading():
        raise HTTPException(status_code=410, detail="set-manual-heading removed — heading comes from centerline profile only")

    @app.post("/api/field-reference/confirm")
    def field_reference_confirm():
        raise HTTPException(status_code=410, detail="confirm removed — bind-current auto-confirms the reference")

    @app.post("/api/field-reference/reset")
    def field_reference_reset():
        try:
            return runner.field_reference_reset()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/field-reference/freeze")
    def field_reference_freeze():
        try:
            return runner.field_reference_freeze()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/field-profiles/{profile_id}/runtime-sampling/start")
    def runtime_sampling_start(profile_id: str):
        try:
            result = runner.field_profile_runtime_sampling_start(profile_id)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        _append_field_reference_audit("runtime_sampling_start", result, pid=profile_id)
        return result

    @app.post("/api/field-reference/runtime-sampling/finalize")
    def runtime_sampling_finalize():
        try:
            result = runner.field_profile_runtime_sampling_finalize()
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        _append_field_reference_audit("runtime_sampling_finalize", result)
        return result

    @app.post("/api/field-reference/runtime-sampling/cancel")
    def runtime_sampling_cancel():
        try:
            result = runner.field_profile_runtime_sampling_cancel()
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        _append_field_reference_audit("runtime_sampling_cancel", result)
        return result

    @app.post("/api/field-reference/runtime-sampling/start")
    def competition_runtime_sampling_start(request: RuntimeSamplingStartRequest):
        import math
        lat = request.forward_marker_lat
        lon = request.forward_marker_lon
        # Validate: finite, in range (bool already rejected by StrictFloat + extra='forbid')
        if not math.isfinite(lat) or not math.isfinite(lon):
            raise HTTPException(
                status_code=400,
                detail="forward_marker_lat/lon must be finite numbers",
            )
        if lat > 90.0 or lat < -90.0:
            raise HTTPException(
                status_code=400,
                detail="forward_marker_lat out of range [-90, 90]",
            )
        if lon > 180.0 or lon < -180.0:
            raise HTTPException(
                status_code=400,
                detail="forward_marker_lon out of range [-180, 180]",
            )
        result = runner.competition_runtime_sampling_start(lat, lon)
        ok = result.get("ok")
        if ok is True:
            _append_field_reference_audit("competition_runtime_sampling_start", result)
            return result
        state = result.get("state", "")
        error = result.get("error", "unknown error")
        if state in ("sampling", "sampling_failed", "apply_failed", "applied"):
            raise HTTPException(status_code=409, detail=error)
        elif "frozen" in str(error).lower():
            raise HTTPException(status_code=409, detail=error)
        elif "invalid" in str(error).lower() or "coordinate" in str(error).lower():
            raise HTTPException(status_code=400, detail=error)
        else:
            _append_field_reference_audit("competition_runtime_sampling_start", result)
            return result

    @app.get("/api/field-profiles")
    def field_profiles_list():
        try:
            return runner.field_profile_list()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/field-profiles/{profile_id}")
    def field_profiles_get(profile_id: str):
        try:
            return runner.field_profile_get(profile_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/field-profiles/{profile_id}/validate")
    def field_profiles_validate(profile_id: str):
        try:
            return runner.field_profile_validate(profile_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/field-profiles/{profile_id}/bind-current")
    def field_profiles_bind_current(profile_id: str):
        try:
            return runner.field_profile_bind_current(profile_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/field-profiles/{profile_id}/map-preview")
    def field_profiles_map_preview(profile_id: str):
        try:
            return runner.field_profile_map_preview(profile_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "profile_id": profile_id}

    @app.post("/api/localization/clear")
    def clear_localization():
        clear = getattr(runner, "clear_localization_result", None)
        if not callable(clear):
            return {"ok": False, "message": "localization clear is unavailable"}
        result = clear()
        audit.append("LOCALIZATION", "clear", result.ok, result.message)
        return {"ok": result.ok, "message": result.message}

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

    @app.get("/api/camera-recording/status")
    def camera_recording_status():
        status_getter = getattr(runner, "camera_recording_status", None)
        if not callable(status_getter):
            return {"ok": False, "error": "camera recording is unavailable"}
        return {"ok": True, "recording": status_getter()}

    @app.post("/api/camera-recording/toggle")
    def camera_recording_toggle():
        toggle = getattr(runner, "camera_recording_toggle", None)
        if not callable(toggle):
            return {"ok": False, "message": "camera recording is unavailable"}
        result = toggle()
        audit.append("CAMERA_RECORDING", "toggle", result.ok, result.message)
        status_getter = getattr(runner, "camera_recording_status", None)
        status = status_getter() if callable(status_getter) else {}
        return {"ok": result.ok, "message": result.message, "recording": status}

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
                snapshot = await asyncio.to_thread(runner.web_status_snapshot)
                await websocket.send_json(snapshot)
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
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
