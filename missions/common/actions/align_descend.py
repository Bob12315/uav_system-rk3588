"""Thin Action adapter for the align/descend lifecycle."""
from __future__ import annotations

from guidance.align_descend import AlignDescendConfig, compute_align_descend_command
from missions.common.lifecycle.align_descend import AlignDescendLifecycle
from .base import ActionModule


class AlignDescendAction(AlignDescendLifecycle, ActionModule):
    """Public Action type; algorithms live in guidance and state in lifecycle."""


__all__ = ["AlignDescendAction", "AlignDescendConfig", "compute_align_descend_command"]
