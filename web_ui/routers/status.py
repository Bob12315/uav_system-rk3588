from __future__ import annotations

from fastapi import APIRouter

from web_ui.context import WebContext


def build_router(ctx: WebContext) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["status"])

    @router.get("/status")
    def status():
        return ctx.services.status_snapshot()

    @router.get("/audit")
    def audit(limit: int = 100):
        return ctx.audit.read_latest(min(max(limit, 1), 500))

    @router.get("/events")
    def events():
        return ctx.services.status_snapshot().get("events", [])

    return router
