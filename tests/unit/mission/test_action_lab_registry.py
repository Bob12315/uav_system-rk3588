from __future__ import annotations

import json

from execution.policy import ACTION_DISPATCH_POLICY
from missions.common.actions.action_lab import (
    action_definitions,
    action_lab_specs,
    create_action_lab_registry,
)
from missions.common.actions.registry import default_registry


def test_action_definition_is_the_single_registry_and_web_catalog() -> None:
    definitions = action_definitions()
    registry = create_action_lab_registry()
    specs = action_lab_specs()
    names = [definition.name for definition in definitions]
    assert len(names) == len(set(names))
    assert registry.list() == sorted(names)
    assert [spec["name"] for spec in specs] == names
    json.dumps(specs)
    for definition, spec in zip(definitions, specs, strict=True):
        assert registry.create(definition.name).__class__ is definition.factory
        assert spec == definition.web_spec()
        assert spec["parameter_schema"]["type"] == "object"


def test_action_definition_defaults_keep_safe_global_field_and_send_boundaries() -> None:
    definitions = {definition.name: definition for definition in action_definitions()}
    goto = definitions["goto_waypoint"].default_params
    assert goto["waypoint_mode"] == "field"
    assert goto["target_frame"] == "global"
    assert definitions["manual_step"].default_params["step_m"] <= 0.5
    assert "payload_release" in definitions
    assert "set_servo" in ACTION_DISPATCH_POLICY


def test_action_lab_does_not_mutate_default_registry() -> None:
    create_action_lab_registry()
    assert not (set(default_registry.list()) & {d.name for d in action_definitions()})


def test_goto_waypoint_global_dispatch_policy_enabled() -> None:
    assert "goto_waypoint" in ACTION_DISPATCH_POLICY["global_goto"].allowed_actions
