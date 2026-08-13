from __future__ import annotations

from fastapi import APIRouter

from web_ui.context import WebContext


def build_router(ctx: WebContext) -> APIRouter:
    router = APIRouter(prefix="/api/services", tags=["services"])
    control = ctx.services.system_control

    @router.post("/telemetry/reconnect")
    def reconnect():
        result = control.reconnect()
        ctx.audit.append("SERVICE", "telemetry reconnect", result.ok, result.message)
        return {"ok": result.ok, "message": result.message}

    @router.post("/{service}/restart")
    def restart(service: str):
        result = control.restart_service(service)
        ctx.audit.append("SERVICE", f"{service} restart", result.ok, result.message)
        return {"ok": result.ok, "message": result.message}

    return router
