"""Executable contracts for the GPS-first six-step V2 drop mission."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V1_PATH = ROOT / "config/action_missions/drop_two_targets_v1.json"
V2_PATH = ROOT / "config/action_missions/drop_two_targets_v2.json"
SITL_V2_PATH = ROOT / "config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json"
V1_EXPECTED_SHA256 = "6aa0e0f006248db11bc65de4e1a6e38fdc92e8a50e3e2cd135bc769e4de04257"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_drop_v1_file_is_unchanged() -> None:
    assert hashlib.sha256(V1_PATH.read_bytes()).hexdigest() == V1_EXPECTED_SHA256


def test_drop_v2_base_and_sitl_are_identical() -> None:
    assert V2_PATH.read_bytes() == SITL_V2_PATH.read_bytes()


def test_drop_v2_has_exact_six_step_gps_first_order() -> None:
    assert [step["name"] for step in _load(V2_PATH)["steps"]] == [
        "takeoff", "gps_multi_view_localize",
        "select_drop_targets", "gps_drop_sequence", "goto_waypoint", "land",
    ]


def test_drop_v2_selects_fused_gps_objects_for_composite_drop() -> None:
    steps = _load(V2_PATH)["steps"]
    select = next(step for step in steps if step["name"] == "select_drop_targets")
    drop = next(step for step in steps if step["name"] == "gps_drop_sequence")
    assert select["params"]["objects"] == "$drop_scan.localized_objects"
    assert select["params"]["coordinate_mode"] == "gps_enu"
    assert drop["params"]["targets"] == "$drop_targets.target_slots"


def test_drop_v2_has_no_deprecated_or_standalone_drop_actions() -> None:
    steps = _load(V2_PATH)["steps"]
    names = [step["name"] for step in steps]
    forbidden = {
        "resolve_gps_targets", "resolve_drop_buckets", "multi_view_localize",
        "drop_sequence", "target_lock", "align_descend", "payload_release",
        "local_position",
    }
    assert not forbidden.intersection(names)
    assert all(step.get("params", {}).get("target_frame") != "local" for step in steps)
    scan = next(step for step in steps if step["name"] == "gps_multi_view_localize")
    assert "waypoints" not in scan["params"]
    assert "lat" not in scan["params"] and "lon" not in scan["params"]


def test_drop_v2_align_payload_and_velocity_safety_contract() -> None:
    drop = next(step for step in _load(V2_PATH)["steps"] if step["name"] == "gps_drop_sequence")
    params = drop["params"]
    align = params["align_descend"]
    assert align["finish_policy"] == "require_alignment_or_timeout"
    assert align["config"]["yaw_control_mode"] == "hold_zero_rate"
    assert align["config"]["require_target_locked"] is True
    assert align["config"]["payload_offset_enabled"] is True
    assert [payload["payload_forward_m"] for payload in params["payloads"]] == [-0.06, 0.06]
    assert [payload["payload_right_m"] for payload in params["payloads"]] == [0.0, 0.0]
    assert params["goto"]["require_velocity_valid"] is True
    assert params["goto"]["max_horizontal_speed_mps"] == 0.15
    assert params["goto"]["max_vertical_speed_mps"] == 0.10


def test_drop_v2_return_home_is_global_field_origin() -> None:
    step = next(step for step in _load(V2_PATH)["steps"] if step.get("label") == "return_home_gps")
    assert step["name"] == "goto_waypoint"
    assert step["params"]["waypoint_mode"] == "field"
    assert step["params"]["target_frame"] == "global"
    assert (step["params"]["x"], step["params"]["y"]) == (0.0, 0.0)
