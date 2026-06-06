from __future__ import annotations

import json

from missions.common.actions.action_lab import action_lab_specs, create_action_lab_registry
from missions.common.actions.registry import default_registry


def test_create_action_lab_registry_lists_supported_actions() -> None:
    registry = create_action_lab_registry()

    assert registry.list() == [
        "align_descend",
        "goto_waypoint",
        "payload_release",
        "survey_area",
        "target_lock",
    ]


def test_action_lab_registry_can_create_each_action() -> None:
    registry = create_action_lab_registry()

    for name in registry.list():
        assert registry.create(name) is not None


def test_action_lab_specs_are_json_serializable() -> None:
    specs = action_lab_specs()

    json.dumps(specs)
    assert [item["name"] for item in specs] == [
        "goto_waypoint",
        "survey_area",
        "target_lock",
        "align_descend",
        "payload_release",
    ]


def test_payload_release_spec_defaults_to_rc13() -> None:
    payload_spec = next(item for item in action_lab_specs() if item["name"] == "payload_release")

    assert payload_spec["default_params"]["channels"] == [13]


def test_action_lab_does_not_auto_register_default_registry() -> None:
    create_action_lab_registry()

    for name in ("goto_waypoint", "survey_area", "target_lock", "align_descend", "payload_release"):
        assert name not in default_registry.list()
