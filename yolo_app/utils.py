from __future__ import annotations

from pathlib import Path


def ensure_parent_dir(path: str) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def normalize_error(center: float, size: int) -> float:
    if size <= 0:
        return 0.0
    half = size / 2.0
    return (center - half) / half


def is_camera_source(source: str) -> bool:
    return source.startswith("/dev/video") or source.isdigit()
