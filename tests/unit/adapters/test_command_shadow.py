from __future__ import annotations

from telemetry_link.command_shadow import LegacyOneShotShadow
from telemetry_link.models import ActionCommand, ActionType


def test_legacy_shadow_observes_supported_one_shot_without_wire_write() -> None:
    shadow = LegacyOneShotShadow(source="sitl", session_id=lambda: "session-1")
    command_id = shadow.observe(ActionCommand(ActionType.SET_SERVO, {"channel": 8, "pwm": 1500}))
    assert command_id is not None
    assert shadow.broker.status(command_id).reason_code == "shadow_observed"
    assert shadow.broker.write_count == 0


def test_legacy_shadow_ignores_non_contract_command() -> None:
    shadow = LegacyOneShotShadow(source="sitl", session_id=lambda: "session-1")
    assert shadow.observe(ActionCommand(ActionType.SET_RELAY, {"relay_id": 1})) is None
    assert shadow.broker.write_count == 0
