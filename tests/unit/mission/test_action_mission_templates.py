from __future__ import annotations

import json
from pathlib import Path

from missions.engine import MissionActionStep
from missions.common.actions.action_lab import create_action_lab_registry
from scripts.validate_action_missions import DEFAULT_TEMPLATE_PATHS, validate_templates


ROOT = Path(__file__).parents[3]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_only_three_formal_v2_templates_are_shipped() -> None:
    paths = sorted((ROOT / "config/action_missions").glob("*.json"))
    assert [path.name for path in paths] == [
        "drop_two_targets.json", "recon_gps.json", "rescue_2026_full_auto.json",
    ]
    assert all(_load(path)["version"] == 2 for path in paths)


def test_formal_templates_validate_and_actions_are_registered() -> None:
    assert len(validate_templates(DEFAULT_TEMPLATE_PATHS)) == 3
    registered = set(create_action_lab_registry().list())
    for path in DEFAULT_TEMPLATE_PATHS:
        for step in _load(path)["steps"]:
            assert step["name"] in registered
            MissionActionStep(step["name"], step["params"], save_as=step.get("save_as"),
                              label=step.get("label"), on_failed=step.get("on_failed"))


def test_drop_flow_is_explicit_and_preserves_payload_order_and_stop_boundary() -> None:
    steps = _load(ROOT / "config/action_missions/drop_two_targets.json")["steps"]
    names = [step["name"] for step in steps]
    assert "gps_multi_view_localize" not in names
    assert "gps_drop_sequence" not in names
    assert names.count("gps_capture_view") == 4
    assert names.count("gps_target_lock") == 2
    assert names.count("align_descend") == 2
    captures = [index for index, step in enumerate(steps) if step["name"] == "gps_capture_view"]
    for capture_index in captures:
        scan_goto = steps[capture_index - 1]
        assert scan_goto["name"] == "goto_waypoint"
        assert scan_goto["params"]["require_velocity_valid"] is True
        assert scan_goto["params"]["max_horizontal_speed_mps"] == 0.15
        assert scan_goto["params"]["max_vertical_speed_mps"] == 0.1
        assert scan_goto["params"]["min_hold_updates"] == 3
    releases = [step for step in steps if step["name"] == "payload_release"]
    assert [step["params"]["payload_id"] for step in releases] == ["payload_1", "payload_2"]
    assert [step["params"]["servo_outputs"] for step in releases] == [
        [{"channel": 9, "release_pwm": 1800, "hold_pwm": 1600}],
        [{"channel": 10, "release_pwm": 1800, "hold_pwm": 1600}],
    ]
    for release in releases:
        index = steps.index(release)
        assert steps[index - 1]["name"] == "align_descend"
        assert steps[index + 1]["name"] == "goto_waypoint"


def test_recon_flow_contains_only_navigation_actions() -> None:
    steps = _load(ROOT / "config/action_missions/recon_gps.json")["steps"]
    names = [step["name"] for step in steps]
    assert "gps_recon_area_scan" not in names
    assert names == ["takeoff", "goto_waypoint", "goto_waypoint", "goto_waypoint", "goto_waypoint", "goto_waypoint", "goto_waypoint", "land"]


def test_full_flow_replaces_visual_land_composite_with_atomic_steps() -> None:
    steps = _load(ROOT / "config/action_missions/rescue_2026_full_auto.json")["steps"]
    names = [step["name"] for step in steps]
    assert "visual_land" not in names
    assert steps[-3]["label"] == "final_land_lock_h"
    assert steps[-2]["label"] == "final_land_align"
    assert steps[-1]["name"] == "land"
    final_h_lock = steps[-3]["params"]
    assert steps[-3]["save_as"] == "final_h_lock"
    assert final_h_lock["acquire_mode"] == "class_single"
    assert final_h_lock["class_names"] == ["H"]
    assert final_h_lock["require_unique_track"] is True
    assert final_h_lock["max_target_age_s"] == 0.5
    assert steps[-2]["params"]["track_id"] == "$final_h_lock.locked_track_id"
    captures = [index for index, step in enumerate(steps) if step["name"] == "gps_capture_view"]
    for capture_index in captures:
        scan_goto = steps[capture_index - 1]
        assert scan_goto["name"] == "goto_waypoint"
        assert scan_goto["params"]["require_velocity_valid"] is True
        assert scan_goto["params"]["max_horizontal_speed_mps"] == 0.15
        assert scan_goto["params"]["max_vertical_speed_mps"] == 0.1
        assert scan_goto["params"]["min_hold_updates"] == 3


def test_full_flow_uses_the_fixed_down_sitl_camera_and_payload_contract() -> None:
    steps = _load(ROOT / "config/action_missions/rescue_2026_full_auto.json")["steps"]
    camera = {
        "fov_x_deg": 114.591559,
        "fov_y_deg": 98.864783,
        "image_x_sign": 1,
        "image_y_sign": -1,
    }

    for step in steps:
        if step["name"] in {"gps_capture_view", "gps_target_lock", "target_lock"}:
            assert step["params"]["camera"] == camera
        if step["name"] == "align_descend" and "fov_x_deg" in step["params"].get("config", {}):
            assert step["params"]["config"].get("fov_x_deg") == camera["fov_x_deg"]
            assert step["params"]["config"].get("fov_y_deg") == camera["fov_y_deg"]
            assert step["params"]["config"].get("image_x_sign") == camera["image_x_sign"]
            assert step["params"]["config"].get("image_y_sign") == camera["image_y_sign"]

    releases = [step["params"] for step in steps if step["name"] == "payload_release"]
    assert [release["servo_outputs"] for release in releases] == [
        [{"channel": 9, "release_pwm": 1800, "hold_pwm": 1600}],
        [{"channel": 10, "release_pwm": 1800, "hold_pwm": 1600}],
    ]
