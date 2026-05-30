from __future__ import annotations

import time


class RateController:
    def __init__(self, rate_hz: float) -> None:
        self.rate_hz = rate_hz
        self.period_sec = 0.0 if rate_hz <= 0 else 1.0 / rate_hz
        self._last_time = 0.0

    def ready(self) -> bool:
        now = time.time()
        if self.period_sec <= 0:
            self._last_time = now
            return True
        if (now - self._last_time) >= self.period_sec:
            self._last_time = now
            return True
        return False

    def remaining(self) -> float:
        if self.period_sec <= 0:
            return 0.0
        elapsed = time.time() - self._last_time
        return max(0.0, self.period_sec - elapsed)
