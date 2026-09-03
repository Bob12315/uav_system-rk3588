from __future__ import annotations

import pytest

from contracts.action import ActionResult
from contracts.effects import FlightCommand
from missions.common.actions.action_lab import action_definitions, create_action_lab_registry
from missions.common.actions.base import ActionModule
from missions.common.actions.runner import ActionRunner


def test_production_actions_have_unique_v1_strict_contracts() -> None:
    definitions = action_definitions()
    assert len({item.name for item in definitions}) == len(definitions)
    assert set(create_action_lab_registry().list()) == {item.name for item in definitions}
    for definition in definitions:
        assert definition.revision == "v1"
        assert definition.parameter_schema["additionalProperties"] is False
        assert set(definition.default_params) <= set(definition.parameter_schema["properties"])
        assert not _has_open_object(definition.parameter_schema)


def test_legacy_aliases_normalize_before_defaults_without_override() -> None:
    definitions = {definition.name: definition for definition in action_definitions()}
    goto = definitions["goto_waypoint"]
    assert goto.merge_and_validate_params({"x": 4.0, "y": 5.0, "altitude_m": 3.0})["field_x_m"] == 4.0
    assert goto.merge_and_validate_params({"field_x_m": 6.0, "x": 4.0, "field_y_m": 5.0, "altitude_m": 3.0})["field_x_m"] == 6.0
    align = definitions["align_descend"]
    assert align.merge_and_validate_params({"target_altitude_m": 0.3})["target_altitude_m"] == 0.3


def test_runner_rejects_unknown_contract_parameter_before_start() -> None:
    runner = ActionRunner(create_action_lab_registry())
    result = runner.start("change_speed", {"speed_mps": 1.0, "speed_typo": "ground"})
    assert result.failed and result.reason == "action_params_invalid"
    assert result.detail["action_name"] == "change_speed"


def test_runner_blocks_effect_not_in_contract() -> None:
    class InvalidEffectAction(ActionModule):
        def start(self, params=None): pass
        def update(self, context=None):
            return ActionResult(effects=[FlightCommand(params={"valid": True, "active": True, "vx_cmd": 0, "vy_cmd": 0, "vz_cmd": 0})])
        def stop(self): pass
        def reset(self): pass

    registry = create_action_lab_registry()
    registry.register("gps_capture_view", InvalidEffectAction, overwrite=True)
    runner = ActionRunner(registry)
    assert not runner.start("gps_capture_view", {}).failed
    result = runner.update({})
    assert result.failed and result.reason == "action_effect_contract_violation"


def _has_open_object(value) -> bool:
    if isinstance(value, dict):
        if value.get("type") == "object" and value.get("additionalProperties") is not False:
            return True
        return any(_has_open_object(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_open_object(item) for item in value)
    return False
