from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.main import setup_logging


def test_app_file_logging_is_bounded(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: captured.update(kwargs))

    setup_logging("INFO", str(tmp_path / "app.log"))

    handlers = captured["handlers"]
    assert len(handlers) == 1
    handler = handlers[0]
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 10 * 1024 * 1024
        assert handler.backupCount == 5
    finally:
        handler.close()
