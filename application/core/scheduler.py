from __future__ import annotations

import threading
import time


class CoreScheduler:
    """The only cadence owner.  Stall recovery advances once with a fresh snapshot."""

    def __init__(self, clock, driver, *, cadence_hz: float = 20.0) -> None:
        if cadence_hz <= 0:
            raise ValueError("scheduler cadence must be positive")
        self._clock = clock
        self._driver = driver
        self._cadence_ns = int(1_000_000_000 / cadence_hz)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sequence = 0
        self._last_error: BaseException | None = None
        self._cycles_completed = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("CoreScheduler is already started")
        self._stop = threading.Event()
        self._last_error = None
        self._thread = threading.Thread(target=self._run, name="CoreScheduler", daemon=False)
        self._thread.start()

    def stop(self, timeout_s: float = 3.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout_s))
            if thread.is_alive():
                raise TimeoutError("CoreScheduler did not stop within its budget")
        self._thread = None

    @property
    def last_error(self) -> BaseException | None:
        return self._last_error

    @property
    def cycles_completed(self) -> int:
        return self._cycles_completed

    def run_one_cycle_for_test(self):
        now = self._clock.now()
        self._sequence += 1
        return self._driver.run_one_cycle(now, now.monotonic_ns, self._sequence)

    def _run(self) -> None:
        deadline = self._clock.now().monotonic_ns
        while not self._stop.is_set():
            now = self._clock.now()
            if now.monotonic_ns < deadline:
                self._stop.wait((deadline - now.monotonic_ns) / 1_000_000_000)
                continue
            self._sequence += 1
            try:
                self._driver.run_one_cycle(now, deadline, self._sequence)
            except BaseException as exc:
                self._last_error = exc
                self._stop.set()
                return
            self._cycles_completed += 1
            # Never replay missed business ticks.
            deadline = max(deadline + self._cadence_ns, now.monotonic_ns + self._cadence_ns)
