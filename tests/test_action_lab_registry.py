from __future__ import annotations

import json

from app.dispatch_policy import ACTION_DISPATCH_POLICY
from missions.common.actions.action_lab import action_lab_specs, create_action_lab_registry
from missions.common.actions.registry import default_registry


def test_create_action_lab_registry_lists_supported_actions() -> None:
    registry = create_action_lab_registry()

    assert registry.list() == [
        "align_descend",
        "goto_waypoint",
        "land",
        "multi_view_localize",
        "payload_release",
        "recon_scan",
        "select_drop_targets",
        "single_view_localize",
        "survey_area",
        "takeoff",
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
        "takeoff",
        "land",
        "goto_waypoint",
        "survey_area",
        "single_view_localize",
        "target_lock",
        "align_descend",
        "payload_release",
        "multi_view_localize",
        "select_drop_targets",
        "recon_scan",
    ]


def test_payload_release_spec_defaults_to_servo_output_8() -> None:
    payload_spec = next(item for item in action_lab_specs() if item["name"] == "payload_release")

    assert payload_spec["default_params"]["servo_outputs"] == [
        {"channel": 8, "release_pwm": 1440, "hold_pwm": 1800},
    ]
    assert "SERVO output" in payload_spec["description"]


def test_localize_specs_default_to_flipped_image_y() -> None:
    specs = {item["name"]: item for item in action_lab_specs()}
    multi_view_params = specs["multi_view_localize"]["default_params"]

    assert specs["single_view_localize"]["default_params"]["camera"]["fov_x_deg"] == 75.0
    assert specs["single_view_localize"]["default_params"]["camera"]["fov_y_deg"] == 60.0
    assert specs["single_view_localize"]["default_params"]["camera"]["image_x_sign"] == 1.0
    assert specs["single_view_localize"]["default_params"]["camera"]["image_y_sign"] == -1.0
    assert "horizontal_fov_deg" not in specs["single_view_localize"]["default_params"]["camera"]
    assert "vertical_fov_deg" not in specs["single_view_localize"]["default_params"]["camera"]
    assert "model" not in specs["single_view_localize"]["default_params"]["camera"]
    assert multi_view_params["camera"]["fov_x_deg"] == 75.0
    assert multi_view_params["camera"]["fov_y_deg"] == 60.0
    assert multi_view_params["camera"]["image_x_sign"] == 1.0
    assert multi_view_params["camera"]["image_y_sign"] == -1.0


def test_multi_view_localize_spec_defaults_to_drop_zone_field_waypoints() -> None:
    spec = next(item for item in action_lab_specs() if item["name"] == "multi_view_localize")
    params = spec["default_params"]

    assert params["waypoint_mode"] == "field"
    assert params["yaw_mode"] == "field_heading"
    assert params["altitude_m"] == 5.0
    assert isinstance(params["waypoints"], list)
    assert len(params["waypoints"]) == 4
    assert params["waypoints"] == [
        {"x": -1.0, "y": 4.8, "altitude_m": 5.0},
        {"x": 1.0, "y": 4.8, "altitude_m": 5.0},
        {"x": 1.0, "y": 6.2, "altitude_m": 5.0},
        {"x": -1.0, "y": 6.2, "altitude_m": 5.0},
    ]
    for waypoint in params["waypoints"]:
        assert {"x", "y", "altitude_m"} <= waypoint.keys()
    assert params["camera"]["fov_x_deg"] == 75.0
    assert params["camera"]["fov_y_deg"] == 60.0
    assert params["camera"]["image_y_sign"] == -1.0
    assert params["fusion"]["cluster_radius_m"] == 0.8
    assert params["fusion"]["min_cluster_size"] == 2


def test_align_descend_spec_defaults_to_low_altitude_descent_profile() -> None:
    spec = next(item for item in action_lab_specs() if item["name"] == "align_descend")
    params = spec["default_params"]
    config = params["config"]

    assert params["expected_dt_s"] == 0.1
    assert params["finish_altitude_m"] == 0.8
    assert config["kp_vx"] == 0.55
    assert config["kp_vy"] == 0.55
    assert params["max_updates"] == 220
    assert config["max_vx_mps"] == 0.35
    assert config["max_vy_mps"] == 0.35
    assert config["descend_speed_mps"] == 0.32
    assert config["slow_descend_speed_mps"] == 0.18
    assert config["max_ex_cam"] == 0.10
    assert config["max_ey_cam"] == 0.10
    assert config["slow_descend_max_ex_cam"] == 0.28
    assert config["slow_descend_max_ey_cam"] == 0.28
    assert config["deadband_ex_cam"] == 0.018
    assert config["deadband_ey_cam"] == 0.018
    assert config["min_altitude_m"] == 0.8
    assert config["require_target_locked"] is False
    assert config["height_gain_enabled"] is True
    assert config["height_gain_mode"] == "points"
    assert len(config["height_scale_points"]) == 5


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
        "takeoff",
        "land",
        "select_drop_targets",
        "recon_scan",
    ):
        assert name not in default_registry.list()


def test_recon_scan_local_position_dispatch_policy_enabled() -> None:
    assert "recon_scan" in ACTION_DISPATCH_POLICY["local_position"].allowed_actions
