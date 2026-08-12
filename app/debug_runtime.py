"""Read-only Action runtime debug status.

The retired mission/stage command override hooks deliberately have no Action
equivalent.  P0 safety and Action send gates remain the only control path.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.app_config import ActionRuntimeDebugConfig


@dataclass(slots=True)
class DebugRuntime:
    config: ActionRuntimeDebugConfig
