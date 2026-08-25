from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from web_ui.context import WebContext
from web_ui.dto import ActionStartRequest


def _source(mission, requested: str | None) -> str:
    source = requested or mission.active_telemetry_source()
    if source not in {"sitl", "real"}:
        raise HTTPException(status_code=400, detail="target_source must be sitl or real")
    if requested is not None and source != mission.active_telemetry_source():
        raise HTTPException(status_code=409, detail="target_source is not the active telemetry source")
    return source


def build_router(ctx: WebContext) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["actions"])
    mission = ctx.services.mission_control

    @router.get("/actions/list")
    def action_list():
        return {"ok": True, "actions": list(ctx.services.action_specs)}

    @router.get("/actions/status")
    def action_status():
        try:
            payload = mission.action_lab_status_payload()
            payload["enabled"] = ctx.services.action_lab_enabled
            return {"ok": True, "action_lab": payload}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/actions/start")
    def action_start(payload: ActionStartRequest, request: Request):
        try:
            logging.getLogger("WebUiServer").info(
                "/api/actions/start action=%s authorize=%s target_source=%s",
                payload.name, payload.authorize, payload.target_source,
            )
            source = _source(mission, payload.target_source)
            result = mission.action_lab_start_action(
                payload.name, dict(payload.params or {}), authorize=payload.authorize,
                operator=request.state.identity.operator, target_source=source,
            )
            if result.failed:
                return {"ok": False, "error": result.reason, "result": result.to_dict(),
                        "action_lab": mission.action_lab_status_payload()}
            mission.action_lab_tick()
            status = mission.action_lab_status_payload()
            return {"ok": True, "result": result.to_dict(), "status": status["status"],
                    "action_lab": status, "dispatch_effective": status["dispatch_effective"],
                    "note": status["note"]}
        except HTTPException:
            raise
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def action_transition(operation: str):
        try:
            result = getattr(mission, f"action_lab_{operation}_action")()
            status = mission.action_lab_status_payload()
            return {"ok": True, "result": result.to_dict(), "status": status["status"],
                    "action_lab": status, "dispatch_effective": status["dispatch_effective"],
                    "note": status["note"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/actions/stop")
    def action_stop():
        return action_transition("stop")

    @router.post("/actions/reset")
    def action_reset():
        return action_transition("reset")

    return router
