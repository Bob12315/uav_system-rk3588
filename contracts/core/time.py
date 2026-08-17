from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Protocol


@dataclass(frozen=True, slots=True, order=True)
class CoreTime:
    monotonic_ns: int
    utc: datetime
    clock_domain_id: str

    def __post_init__(self) -> None:
        if self.monotonic_ns < 0:
            raise ValueError("monotonic_ns must be non-negative")
        if self.utc.tzinfo is None or self.utc.utcoffset() is None:
            raise ValueError("utc must be timezone-aware")
        if not self.clock_domain_id:
            raise ValueError("clock_domain_id must not be empty")

    def elapsed_ns_since(self, earlier: "CoreTime") -> int:
        if self.clock_domain_id != earlier.clock_domain_id:
            raise ValueError("cannot compare different monotonic clock domains")
        return self.monotonic_ns - earlier.monotonic_ns


class CoreClock(Protocol):
    def now(self) -> CoreTime: ...


class SystemCoreClock:
    def __init__(self, clock_domain_id: str) -> None:
        if not clock_domain_id:
            raise ValueError("clock_domain_id must not be empty")
        self._clock_domain_id = clock_domain_id

    def now(self) -> CoreTime:
        return CoreTime(time.monotonic_ns(), datetime.now(timezone.utc), self._clock_domain_id)


class ManualCoreClock:
    def __init__(self, initial: CoreTime) -> None:
        self._now = initial

    def now(self) -> CoreTime:
        return self._now

    def advance_ns(self, delta_ns: int) -> CoreTime:
        if delta_ns < 0:
            raise ValueError("manual clock cannot move backwards")
        from datetime import timedelta

        self._now = CoreTime(
            self._now.monotonic_ns + delta_ns,
            self._now.utc + timedelta(microseconds=delta_ns / 1000),
            self._now.clock_domain_id,
        )
        return self._now
