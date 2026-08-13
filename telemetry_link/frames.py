"""Transport-facing re-export of dependency-free MAVLink frame constants."""

from __future__ import annotations

from contracts.frames import BODY_NED, GLOBAL, GLOBAL_RELATIVE_ALT_INT, LOCAL_NED

__all__ = ["BODY_NED", "GLOBAL", "GLOBAL_RELATIVE_ALT_INT", "LOCAL_NED"]
