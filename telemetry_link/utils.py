from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(level: str, log_file: str | None = None) -> None:
    kwargs = {
        "level": getattr(logging, level.upper(), logging.INFO),
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    }
    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        kwargs["filename"] = log_file
    logging.basicConfig(**kwargs)
