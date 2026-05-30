from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StageDebugConfig:
    force_mode: str | None = None
    enable_gimbal: bool | None = None
    enable_body: bool | None = None
    enable_approach: bool | None = None
    dry_run: bool = True

