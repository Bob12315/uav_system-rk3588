from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock


class ManualClock:
    """Thread-safe clock whose monotonic and wall domains are controlled by tests."""

    def __init__(
        self,
        *,
        monotonic_ns: int = 0,
        utc: datetime | None = None,
        clock_domain_id: str = "test-clock",
    ) -> None:
        if monotonic_ns < 0:
            raise ValueError("monotonic_ns must be non-negative")
        self._monotonic_ns = monotonic_ns
        self._utc = utc or datetime(2026, 1, 1, tzinfo=timezone.utc)
        if self._utc.tzinfo is None:
            raise ValueError("utc must be timezone-aware")
        self.clock_domain_id = clock_domain_id
        self._lock = Lock()

    def monotonic_ns(self) -> int:
        with self._lock:
            return self._monotonic_ns

    def monotonic(self) -> float:
        return self.monotonic_ns() / 1_000_000_000

    def utc_now(self) -> datetime:
        with self._lock:
            return self._utc

    def time(self) -> float:
        return self.utc_now().timestamp()

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("monotonic time cannot move backwards")
        delta_ns = round(seconds * 1_000_000_000)
        with self._lock:
            self._monotonic_ns += delta_ns
            self._utc += timedelta(seconds=seconds)

    def rollback_wall(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("rollback must be non-negative")
        with self._lock:
            self._utc -= timedelta(seconds=seconds)
