"""Thin Web process adapter: app creation and server lifecycle only."""
from __future__ import annotations

import logging
import threading

import uvicorn
from fastapi import FastAPI

from app.config import UiConfig
from application.web_services import WebServices
from web_ui.api_routers import create_router_app


def create_app(services: WebServices, config: UiConfig) -> FastAPI:
    return create_router_app(services, config)


class WebUiServer:
    def __init__(self, services: WebServices, config: UiConfig) -> None:
        self.services = services
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        uvicorn_config = uvicorn.Config(
            create_app(self.services, self.config),
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
