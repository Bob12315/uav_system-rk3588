from __future__ import annotations

from fastapi import APIRouter, HTTPException

from web_ui.context import WebContext
from web_ui.dto import ConfigWriteRequest


def _apply(ctx: WebContext, path: str, action: str) -> dict[str, object]:
    control = ctx.services.system_control
    if action == "reconnect" and path == "config/telemetry.yaml":
        result = control.reconnect()
    elif action == "restart_yolo" and path == "config/yolo.yaml":
        result = control.restart_service("yolo")
    elif action == "restart_app" and path == "config/app.yaml":
        result = control.restart_service("app")
    else:
        return {"ok": True, "message": "configuration saved"}
    return {"ok": result.ok, "message": result.message}


def build_router(ctx: WebContext) -> APIRouter:
    router = APIRouter(prefix="/api/config", tags=["config"])
    store = ctx.config_store

    @router.get("/files")
    def files(): return store.files()

    @router.get("/file")
    def read(path: str):
        try: return store.read(path)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("/file")
    def save(path: str, payload: ConfigWriteRequest):
        try:
            diff = store.save(path, payload.content)
            result = _apply(ctx, path, payload.action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ctx.audit.append("CONFIG", f"{payload.action} {path}", result["ok"], result["message"])
        return {"diff": diff, **result}

    @router.post("/restore")
    def restore(path: str, action: str = "save"):
        try:
            diff = store.restore(path)
            result = _apply(ctx, path, action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ctx.audit.append("CONFIG", f"restore {path}", result["ok"], result["message"])
        return {"diff": diff, **result}

    return router
