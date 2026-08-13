"""FastAPI assembly: middleware, static assets and router mounting."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, UiConfig
from application.web_services import WebServices
from web_ui.audit import AuditLog
from web_ui.config_store import ConfigStore
from web_ui.context import WebContext
from web_ui.routers import actions, auth, config as config_router, control, field, missions, services, status, vision
from web_ui.security import WebSecurity


def create_router_app(web_services: WebServices, config: UiConfig) -> FastAPI:
    app = FastAPI(title="UAV Web Control")
    audit = AuditLog(config.audit_log_path)
    security = WebSecurity(config, audit)
    security.validate_startup()
    context = WebContext(web_services, audit, security, ConfigStore(ROOT_DIR))
    app.middleware("http")(security.middleware(web_services))

    for module in (auth, status, actions, missions, field, vision, config_router, services, control):
        app.include_router(module.build_router(context))

    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.websocket("/ws/status")
    async def status_socket(websocket: WebSocket):
        if security.auth_required and security.authenticate_websocket(websocket) is None:
            await websocket.close(code=4401)
            return
        origin = websocket.headers.get("origin")
        if origin and origin.rstrip("/") not in security.allowed_origins:
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            while True:
                snapshot = await asyncio.to_thread(web_services.status_snapshot)
                await websocket.send_json(snapshot)
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except (WebSocketDisconnect, RuntimeError):
            return

    return app
