"""Pure shared contracts. This package intentionally depends on stdlib only."""

from .action import ActionResult
from .state import RuntimeSnapshot

__all__ = ["ActionResult", "RuntimeSnapshot"]
