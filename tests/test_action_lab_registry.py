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


def test_localize_specs_default_to_flipped_image_y() -> None:
    specs = {item["name"]: item for item in action_lab_specs()}
    multi_view_params = specs["multi_view_localize"]["default_params"]

    assert specs["single_view_localize"]["default_params"]["camera"]["fov_x_deg"] == 113.0
    assert specs["single_view_localize"]["default_params"]["camera"]["fov_y_deg"] == 93.0
    assert specs["single_view_localize"]["default_params"]["camera"]["image_x_sign"] == 1
    assert specs["single_view_localize"]["default_params"]["camera"]["image_y_sign"] == -1
    assert "horizontal_fov_deg" not in specs["single_view_localize"]["default_params"]["camera"]
    assert "vertical_fov_deg" not in specs["single_view_localize"]["default_params"]["camera"]
    assert "model" not in specs["single_view_localize"]["default_params"]["camera"]
    assert multi_view_params["camera"]["fov_x_deg"] == 113.0
    assert multi_view_params["camera"]["fov_y_deg"] == 93.0
    assert multi_view_params["camera"]["image_x_sign"] == 1.0
    assert multi_view_params["camera"]["image_y_sign"] == -1.0


def test_multi_view_localize_spec_defaults_to_drop_zone_absolute_waypoints() -> None:
    spec = next(item for item in action_lab_specs() if item["name"] == "multi_view_localize")
    params = spec["default_params"]

    assert params["waypoint_mode"] == "absolute"
    assert params["yaw_mode"] == "hold"
    assert params["altitude_m"] == 3.5
    assert isinstance(params["waypoints"], list)
    assert len(params["waypoints"]) == 4
    assert params["waypoints"] == [
        {"x": -1.2, "y": 28, "altitude_m": 3},
        {"x": 1.2, "y": 28, "altitude_m": 3},
        {"x": 1.2, "y": 32, "altitude_m": 3},
        {"x": -1.2, "y": 32, "altitude_m": 3},
    ]
    for waypoint in params["waypoints"]:
        assert {"x", "y", "altitude_m"} <= waypoint.keys()
    assert params["camera"]["fov_x_deg"] == 113.0
    assert params["camera"]["fov_y_deg"] == 93.0
    assert params["camera"]["image_y_sign"] == -1.0
    assert params["fusion"]["cluster_radius_m"] == 1.0
    assert params["fusion"]["min_cluster_size"] == 3


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
