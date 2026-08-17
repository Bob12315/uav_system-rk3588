from __future__ import annotations

from types import SimpleNamespace

from contracts.effects import FlightCommand
from execution.authorization import RunAuthorization
from execution.dispatcher import ActionDispatcher


class _StatePort:
    def get_active_source(self) -> str:
        return "sitl"

    def get_latest_drone_state(self):
        return SimpleNamespace(connected=True, stale=False, control_allowed=True)


class _CommandPort:
    def __init__(self) -> None:
        self.commands: list[tuple[object, ...]] = []

    def send_velocity_command(self, *args: object, **kwargs: object) -> None:
        self.commands.append((*args, kwargs))


def _authorize(dispatcher: ActionDispatcher, source: str = "sitl") -> None:
    dispatcher.set_authorization(
        RunAuthorization.create(
            operator="test",
            scope_type="action",
            scope_name="align_descend",
            target_source=source,
            allowed_actions={"align_descend"},
        )
    )


def test_production_dispatch_reads_source_from_state_port_only() -> None:
    commands = _CommandPort()
    dispatcher = ActionDispatcher(state_port=_StatePort(), command_port=commands)
    _authorize(dispatcher)
    effect = FlightCommand(params={"valid": True, "vx_cmd": 0.0, "vy_cmd": 0.0, "vz_cmd": 0.0})
    result = dispatcher.dispatch_effects(
        [effect], action_name="align_descend", send_commands=True, link_manager=None
    )
    assert result["accepted"]
    assert commands.commands
    dispatcher.safety_pipeline.stop_continuous("test_cleanup", emit=False)
    dispatcher.safety_pipeline.continuous_guard.close()


def test_missing_state_port_fails_closed_and_never_infers_test_source() -> None:
    commands = _CommandPort()
    dispatcher = ActionDispatcher(command_port=commands)
    _authorize(dispatcher)
    effect = FlightCommand(params={"valid": True, "vx_cmd": 0.0, "vy_cmd": 0.0, "vz_cmd": 0.0})
    result = dispatcher.dispatch_effects(
        [effect], action_name="align_descend", send_commands=True, link_manager=None
    )
    assert result["skipped"][0]["reason"] == "telemetry_state_unavailable"
    assert commands.commands == []


def test_test_source_requires_explicit_fixture_context() -> None:
    dispatcher = ActionDispatcher(test_source="test")
    assert dispatcher._source_for(None) == "test"
