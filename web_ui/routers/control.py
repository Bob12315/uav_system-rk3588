from __future__ import annotations

from fastapi import APIRouter, HTTPException

from web_ui.context import WebContext
from web_ui.dto import SendControlRequest, SourceSwitchRequest


def build_router(ctx: WebContext) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["control"])
    control = ctx.services.system_control

    @router.post("/control/send")
    def send(payload: SendControlRequest):
        result = control.set_send(payload.enabled)
        return {"ok": result.ok, "message": result.message}

    @router.post("/telemetry/source")
    def source(payload: SourceSwitchRequest):
        if payload.source not in {"sitl", "real"}:
            raise HTTPException(status_code=400, detail="source must be sitl or real")
        result = control.switch_source(payload.source)
        return {"ok": result.ok, "message": result.message}

    return router
