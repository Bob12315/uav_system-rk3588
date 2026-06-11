from __future__ import annotations

import json

from missions.common.actions.action_lab import action_lab_specs, create_action_lab_registry
from missions.common.actions.registry import default_registry


def test_create_action_lab_registry_lists_supported_actions() -> None:
    registry = create_action_lab_registry()

    assert registry.list() == [
        "align_descend",
        "goto_waypoint",
        "multi_view_localize",
        "payload_release",
        "single_view_localize",
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
        "single_view_localize",
        "target_lock",
        "align_descend",
        "payload_release",
        "multi_view_localize",
    ]


def test_payload_release_spec_defaults_to_servo_output_8() -> None:
    payload_spec = next(item for item in action_lab_specs() if item["name"] == "payload_release")

    assert payload_spec["default_params"]["servo_outputs"] == [
        {"channel": 8, "release_pwm": 1200, "hold_pwm": 1700},
        {"channel": 9, "release_pwm": 1700, "hold_pwm": 1200},
    ]
    assert "SERVO output" in payload_spec["description"]


def test_action_lab_does_not_auto_register_default_registry() -> None:
    create_action_lab_registry()

    for name in (
        "goto_waypoint",
        "survey_area",
        "single_view_localize",
        "target_lock",
        "align_descend",
        "payload_release",
        "multi_view_localize",
    ):
        assert name not in default_registry.list()
