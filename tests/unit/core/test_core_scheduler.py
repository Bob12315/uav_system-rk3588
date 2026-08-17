import time

from application.core.scheduler import CoreScheduler
from contracts.core.time import SystemCoreClock


class _Driver:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = []
        self.fail = fail

    def run_one_cycle(self, now, deadline, sequence):
        self.calls.append((now, deadline, sequence))
        if self.fail:
            raise RuntimeError("cycle failed")
        return sequence


def test_manual_cycle_has_one_advance_per_call() -> None:
    driver = _Driver()
    scheduler = CoreScheduler(SystemCoreClock("test"), driver, cadence_hz=20)
    assert scheduler.run_one_cycle_for_test() == 1
    assert scheduler.run_one_cycle_for_test() == 2
    assert [item[2] for item in driver.calls] == [1, 2]


def test_scheduler_captures_driver_exception_and_joins_bounded() -> None:
    driver = _Driver(fail=True)
    scheduler = CoreScheduler(SystemCoreClock("test"), driver, cadence_hz=100)
    scheduler.start()
    deadline = time.monotonic() + 1
    while scheduler.last_error is None and time.monotonic() < deadline:
        time.sleep(0.005)
    scheduler.stop(timeout_s=1)
    assert isinstance(scheduler.last_error, RuntimeError)
