from datetime import datetime, timezone

from application.core.runtime import build_core_runtime
from contracts.core.common import freeze_json
from contracts.core.input_state import FusionSnapshot, FusionState
from contracts.core.time import CoreTime, ManualCoreClock
from contracts.platform.common import LinkSessionId


class _Snapshot:
    def snapshot(self):
        return None


class _Fusion:
    def compute(self, vehicle, perception, field):
        return FusionSnapshot(FusionState.UNAVAILABLE, None, None, None, freeze_json({}))


class _VehicleCommands:
    def submit(self, command):
        raise AssertionError("idle SEND-off cycle must not submit")

    def cancel(self, request):
        raise AssertionError("idle cycle must not cancel")

    def status(self, command_id):
        raise KeyError(command_id)


class _VisionCommands:
    def submit(self, command):
        raise AssertionError("idle cycle must not submit")

    def status(self, command_id):
        raise KeyError(command_id)


def test_core_runtime_composes_one_idle_cycle_without_external_io() -> None:
    clock = ManualCoreClock(CoreTime(1, datetime(2026, 1, 1, tzinfo=timezone.utc), "test"))
    runtime = build_core_runtime(
        source="sitl", link_session_id=LinkSessionId("session"),
        vehicle_state=_Snapshot(), perception=_Snapshot(), field_reference=_Snapshot(),
        fusion=_Fusion(), vehicle_commands=_VehicleCommands(), vision_commands=_VisionCommands(),
        clock=clock,
    )
    assert runtime.send_state.snapshot().enabled is False
    cycle = runtime.scheduler.run_one_cycle_for_test()
    assert runtime.input_store.current() is cycle.input_snapshot
    assert runtime.cycle_store.current() is cycle
    assert cycle.run is None
