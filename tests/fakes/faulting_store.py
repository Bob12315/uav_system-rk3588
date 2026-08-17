from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class StoreFault(OSError):
    pass


@dataclass(slots=True)
class FaultingStore:
    """Append-only store double with explicit, reproducible failure modes."""

    mode: str = "ok"
    records: list[Any] | None = None

    def __post_init__(self) -> None:
        if self.records is None:
            self.records = []

    def set_mode(self, mode: str) -> None:
        if mode not in {"ok", "full", "readonly", "permission", "slow"}:
            raise ValueError(f"unknown store mode: {mode}")
        self.mode = mode

    def append(self, record: Any) -> None:
        if self.mode == "full":
            raise StoreFault("storage_full")
        if self.mode == "readonly":
            raise StoreFault("storage_readonly")
        if self.mode == "permission":
            raise PermissionError("storage_permission_denied")
        assert self.records is not None
        self.records.append(record)
