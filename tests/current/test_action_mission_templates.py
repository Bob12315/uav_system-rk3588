from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.mission_orchestrator import MissionActionStep, MissionBlackboard
from missions.common.actions.action_lab import create_action_lab_registry
from scripts.validate_action_missions import validate_templates


TEMPLATE_PATHS = [
    Path("config/action_missions/drop_two_targets_v1.json"),
    Path("config/action_missions/recon_sequence_v1.json"),
    Path("config/action_missions/rescue_2026_full_auto.json"),
    Path("config/action_missions/rescue_2026_full_auto_v2.json"),
]
DROP_TEMPLATE_PATH = TEMPLATE_PATHS[0]
RECON_SEQUENCE_TEMPLATE_PATH = TEMPLATE_PATHS[1]
FULL_TEMPLATE_PATH = TEMPLATE_PATHS[2]
FULL_V2_TEMPLATE_PATH = TEMPLATE_PATHS[3]
DROP_V2_TEMPLATE_PATH = Path("config/action_missions/drop_two_targets_v2.json")
REQUIRED_REFERENCES = {
    "$drop_scan.localized_objects",
}
FULL_TEMPLATE_REQUIRED_REFERENCES = {
    "$drop_scan.localized_objects",
    "$drop_targets.target_slots",
    "$recon_scan.localized_objects",
    "$recon_targets.target_slots",
    "$recon_sequence.recon_result_items",
}
ALLOWED_FAILURE_ACTIONS = {"fail", "retry_current", "retry_current_then_jump_to", "jump_to", "continue"}


def _template(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _references(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value.startswith("$") else set()
    if isinstance(value, dict):
        refs: set[str] = set()
        for item in value.values():
            refs.update(_references(item))
        return refs
    if isinstance(value, list):
        refs = set()
        for item in value:
            refs.update(_references(item))
        return refs
    return set()


def test_action_mission_templates_json_load() -> None:
    for path in TEMPLATE_PATHS:
        assert path.exists()

        data = _template(path)

        assert data["name"]
        assert isinstance(data["steps"], list)
        assert data["steps"]


def test_action_mission_template_steps_have_name_and_params() -> None:
    for path in TEMPLATE_PATHS:
        data = _template(path)

        for step in data["steps"]:
            assert isinstance(step["name"], str)
            assert isinstance(step.get("params", {}), dict)


def test_action_mission_waypoint_frames_are_explicit_and_match_coordinate_source() -> None:
    flight_actions = {"goto_waypoint", "multi_view_localize", "survey_area", "recon_scan"}
    for path in TEMPLATE_PATHS:
        for step in _template(path)["steps"]:
            if step["name"] not in flight_actions:
                continue
            params = step["params"]
            assert params["waypoint_mode"] in {"field", "absolute"}
            assert params["yaw_mode"] in {"field_heading", "hold"}
            if step["name"] == "goto_waypoint":
                uses_localized_target = str(params.get("x", "")).endswith(".local_x")
                assert params["waypoint_mode"] == ("absolute" if uses_localized_target else "field")
            else:
                assert params["waypoint_mode"] == "field"


def test_action_mission_template_actions_are_registered() -> None:
    registered = set(create_action_lab_registry().list())

    for path in TEMPLATE_PATHS:
        data = _template(path)

        for step in data["steps"]:
            assert step["name"] in registered


def test_drop_two_targets_template_save_as_names() -> None:
    data = _template(DROP_TEMPLATE_PATH)
    by_name = {step["name"]: step for step in data["steps"]}

    assert by_name["multi_view_localize"]["save_as"] == "drop_scan"
    assert by_name["select_drop_targets"]["save_as"] == "drop_targets"
    assert by_name["select_drop_targets"]["params"]["allow_fewer"] is True
    assert [
        item["channel"]
        for item in by_name["select_drop_targets"]["params"]["single_target_servo_outputs"]
    ] == [8, 9]
    return_home = next(step for step in data["steps"] if step.get("label") == "return_home")
    assert return_home["params"]["key"] == "return_home"


def test_action_mission_templates_contain_required_blackboard_refs() -> None:
    # Full template must contain all composite-action refs
    full_refs = _references(_template(FULL_TEMPLATE_PATH)["steps"])
    assert FULL_TEMPLATE_REQUIRED_REFERENCES <= full_refs

    # drop_two_targets template must have drop_scan ref
    drop_refs = _references(_template(DROP_TEMPLATE_PATH)["steps"])
    assert "$drop_scan.localized_objects" in drop_refs

    # recon_sequence template must have recon refs
    recon_refs = _references(_template(RECON_SEQUENCE_TEMPLATE_PATH)["steps"])
    assert "$recon_scan.localized_objects" in recon_refs
    assert "$recon_targets.target_slots" in recon_refs
    assert "$recon_sequence.recon_result_items" in recon_refs


def test_action_mission_templates_construct_mission_action_steps() -> None:
    for path in TEMPLATE_PATHS:
        data = _template(path)

        steps = [
            MissionActionStep(
                step["name"],
                dict(step.get("params") or {}),
                save_as=step.get("save_as"),
            )
            for step in data["steps"]
        ]

        assert len(steps) == len(data["steps"])
        by_save_as = {step.get("save_as", ""): step for step in data["steps"] if step.get("save_as")}
        if "drop_scan" in by_save_as:
            assert by_save_as["drop_scan"]["name"] in ("multi_view_localize", "fixed_view_localize", "gps_multi_view_localize")
            assert by_save_as["drop_targets"]["name"] == "select_drop_targets"


def test_action_mission_templates_blackboard_references_resolve() -> None:
    blackboard = MissionBlackboard()
    blackboard.set(
        "drop_scan",
        {
            "localized_objects": [
                {"id": "b1", "local_x": 1.0, "local_y": 30.0},
                {"id": "b2", "local_x": -1.0, "local_y": 31.0},
            ],
            "raw_estimates": [
                {"track_id": 1, "class_name": "bucket_1", "local_x": 1.0, "local_y": 30.0, "source": {"ex": 0.1, "ey": 0.05}},
                {"track_id": 2, "class_name": "bucket_2", "local_x": -1.0, "local_y": 31.0, "source": {"ex": -0.1, "ey": 0.08}},
            ],
        },
    )
    blackboard.set(
        "drop_center",
        {
            "resolved_targets": [
                {"valid": True, "source": "field", "local_x": 100.0, "local_y": 232.5, "z_down_m": -5.0},
            ],
        },
    )
    blackboard.set(
        "first_scan_point",
        {
            "resolved_targets": [
                {"valid": True, "source": "field", "local_x": 98.0, "local_y": 231.25, "z_down_m": -5.0},
            ],
        },
    )
    blackboard.set(
        "drop_buckets",
        {
            "resolved_targets": [
                {"valid": True, "source": "vision", "class_name": "bucket_1", "local_x": 101.0, "local_y": 230.0, "z_down_m": -5.0},
                {"valid": True, "source": "vision", "class_name": "bucket_2", "local_x": 99.0, "local_y": 231.0, "z_down_m": -5.0},
            ],
        },
    )
    blackboard.set(
        "home_waypoint",
        {
            "resolved_targets": [
                {"valid": True, "source": "home", "local_x": 100.0, "local_y": 200.0, "z_down_m": -5.0},
            ],
        },
    )
    blackboard.set(
        "drop_targets",
        {
            "target_slots": [
                {"valid": True, "id": "b1", "local_x": 1.0, "local_y": 30.0, "x": 1.0, "y": 30.0},
                {"valid": True, "id": "b2", "local_x": -1.0, "local_y": 31.0, "x": -1.0, "y": 31.0},
            ],
            "selected_targets": [
                {"id": "b1", "local_x": 1.0, "local_y": 30.0},
                {"id": "b2", "local_x": -1.0, "local_y": 31.0},
            ],
            "first_release_servo_outputs": [
                {"channel": 8, "release_pwm": 1750, "hold_pwm": 1250},
            ],
        },
    )
    blackboard.set(
        "drop_sequence",
        {"released_count": 2, "fallback_release_count": 0, "skipped_target_count": 0},
    )
    blackboard.set(
        "recon_scan",
        {
            "localized_objects": [
                {"id": "r1", "class_name": "bucket", "local_x": 1.0, "local_y": 5.0},
            ],
        },
    )
    blackboard.set(
        "recon_targets",
        {
            "selected_targets": [
                {"id": "r1", "target_id": "r1", "lat": 34.0, "lon": 108.0, "east_m": 1.0, "north_m": 5.0},
            ],
            "target_slots": [
                {"valid": True, "id": "r1", "class_name": "bucket", "local_x": 1.0, "local_y": 5.0, "x": 1.0, "y": 5.0, "rank": 1},
                {"valid": False, "id": "missing_1", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 2, "status": "missing"},
                {"valid": False, "id": "missing_2", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 3, "status": "missing"},
                {"valid": False, "id": "missing_3", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 4, "status": "missing"},
                {"valid": False, "id": "missing_4", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 5, "status": "missing"},
            ],
        },
    )
    blackboard.set(
        "recon_sequence",
        {
            "observations": [],
            "recon_result_items": [
                {"target_id": "r1", "content": "shenghua", "status": "detected"},
                {"target_id": "missing_1", "content": "blank", "status": "skipped_missing_target"},
            ],
        },
    )
    blackboard.set(
        "recon_report",
        {"recon_report": {"barrels": []}, "barrel_count": 5},
    )

    for path in TEMPLATE_PATHS:
        data = _template(path)

        for step in data["steps"]:
            blackboard.resolve(step.get("params") or {})


def test_full_rescue_template_contains_recon_scan_after_two_drops() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    steps = data["steps"]
    labels = [step.get("label", "") for step in steps]
    names = [step["name"] for step in steps]

    # Order: drop_scan → drop_targets → drop_sequence → recon_scan → recon_targets → recon_sequence → report → return → land
    drop_scan_idx = labels.index("drop_scan")
    drop_seq_idx = labels.index("drop_sequence")
    recon_scan_idx = labels.index("recon_scan")
    recon_seq_idx = labels.index("recon_sequence")
    report_idx = labels.index("build_recon_report")
    return_idx = labels.index("return_home")

    assert drop_scan_idx < drop_seq_idx < recon_scan_idx < recon_seq_idx
    assert recon_seq_idx < report_idx < return_idx
    assert steps[-1]["name"] == "land"
    assert "drop_sequence" in names
    assert "recon_sequence" in names


def test_full_rescue_template_save_as_names() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}

    assert by_label["drop_scan"]["save_as"] == "drop_scan"
    assert by_label["recon_scan"]["save_as"] == "recon_scan"
    assert by_label["select_recon_targets"]["save_as"] == "recon_targets"


def test_full_rescue_template_failure_policies_are_valid() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    steps = data["steps"]
    labels = [step["label"] for step in steps if step.get("label")]
    label_set = set(labels)

    assert len(labels) == len(label_set)
    for step in steps:
        policy = step.get("on_failed")
        if policy is None:
            continue
        assert policy["action"] in ALLOWED_FAILURE_ACTIONS
        if policy["action"] == "jump_to":
            assert policy["target"] in label_set


# ── Phase4 full mission template tests ─────────────────────────────────

def test_full_rescue_includes_drop_sequence() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    names = [step["name"] for step in data["steps"]]
    assert "drop_sequence" in names


def test_full_rescue_includes_recon_sequence() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    names = [step["name"] for step in data["steps"]]
    assert "recon_sequence" in names


def test_drop_sequence_after_select_drop_targets() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    labels = [step.get("label", "") for step in data["steps"]]
    select_idx = labels.index("select_drop_targets")
    drop_seq_idx = labels.index("drop_sequence")
    assert select_idx < drop_seq_idx


def test_recon_sequence_after_select_recon_targets() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    labels = [step.get("label", "") for step in data["steps"]]
    select_idx = labels.index("select_recon_targets")
    recon_seq_idx = labels.index("recon_sequence")
    assert select_idx < recon_seq_idx


def test_build_recon_report_uses_recon_sequence_items() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    items = by_label["build_recon_report"]["params"]["items"]
    assert items == "$recon_sequence.recon_result_items"


def test_drop_scan_center_waypoint_mode_field() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    step = by_label["goto_drop_scan_center"]
    assert step["params"]["waypoint_mode"] == "field"
    assert step["params"]["x"] == 0.0
    assert step["params"]["y"] == 32.5


def test_recon_scan_center_waypoint_mode_field() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    step = by_label["goto_recon_scan_center"]
    assert step["params"]["waypoint_mode"] == "field"
    assert step["params"]["x"] == 0.0
    assert step["params"]["y"] == 57.5


def test_return_home_waypoint_mode_field() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    step = by_label["return_home"]
    assert step["params"]["waypoint_mode"] == "field"
    assert step["params"]["x"] == 0.0
    assert step["params"]["y"] == 0.0


def test_drop_two_targets_v2_uses_gps_first_composite_runtime() -> None:
    data = _template(DROP_V2_TEMPLATE_PATH)
    names = [step["name"] for step in data["steps"]]
    assert names == [
        "takeoff", "gps_multi_view_localize",
        "select_drop_targets", "gps_drop_sequence", "goto_waypoint", "land",
    ]
    by_name = {step["name"]: step for step in data["steps"]}
    select_params = by_name["select_drop_targets"]["params"]
    assert select_params["objects"] == "$drop_scan.localized_objects"
    assert select_params["coordinate_mode"] == "gps_enu"
    assert select_params["min_seen_count"] == 2
    forbidden = {
        "resolve_gps_targets", "resolve_drop_buckets", "multi_view_localize",
        "drop_sequence", "target_lock", "align_descend", "payload_release",
    }
    assert not forbidden.intersection(names)
    return_home = by_name["goto_waypoint"]
    assert return_home["label"] == "return_home_gps"
    assert return_home["params"]["target_frame"] == "global"


def test_drop_sequence_goto_waypoint_mode_absolute() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    goto = by_label["drop_sequence"]["params"]["goto"]
    assert goto["waypoint_mode"] == "absolute"


def test_recon_sequence_goto_waypoint_mode_absolute() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    goto = by_label["recon_sequence"]["params"]["goto"]
    assert goto["waypoint_mode"] == "absolute"


def test_full_rescue_has_12_steps() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    assert len(data["steps"]) == 12


def test_drop_sequence_on_failed_is_continue() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["drop_sequence"]["on_failed"]["action"] == "continue"


def test_recon_sequence_on_failed_jumps_to_return_home() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    policy = by_label["recon_sequence"]["on_failed"]
    assert policy["action"] == "jump_to"
    assert policy["target"] == "return_home"


def test_build_recon_report_on_failed_is_continue() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["build_recon_report"]["on_failed"]["action"] == "continue"


def test_return_home_on_failed_is_continue() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["return_home"]["on_failed"]["action"] == "continue"


# ── Phase4 fix: drop candidate count tests ─────────────────────────────

def test_select_drop_targets_target_count_is_3() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["select_drop_targets"]["params"]["target_count"] == 3


def test_drop_sequence_max_target_candidates_is_3() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["drop_sequence"]["params"]["max_target_candidates"] == 3


def test_drop_sequence_max_payloads_is_2() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["drop_sequence"]["params"]["max_payloads"] == 2


def test_sitl_profile_matches_base_full_template() -> None:
    sitl_path = Path("config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto.json")
    base = _template(FULL_TEMPLATE_PATH)
    sitl = _template(sitl_path)
    assert sitl == base


# ── SITL 前安全修复：空中失败 fallback 测试 ─────────────────────────────

def test_takeoff_failed_jumps_to_land_home() -> None:
    """takeoff failed → jump_to land_home, not mission failed."""
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    policy = by_label["takeoff_5m"]["on_failed"]
    assert policy["action"] == "jump_to"
    assert policy["target"] == "land_home"


def test_drop_scan_failed_jumps_to_recon_scan_center() -> None:
    """drop fixed_view_localize failed → jump_to recon scan instead of mission failed."""
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    policy = by_label["drop_scan"]["on_failed"]
    assert policy["action"] == "jump_to"
    assert policy["target"] == "goto_recon_scan_center"


def test_select_drop_targets_failed_jumps_to_recon_scan_center() -> None:
    """select_drop_targets failed → jump_to recon scan instead of return_home."""
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    policy = by_label["select_drop_targets"]["on_failed"]
    assert policy["action"] == "jump_to"
    assert policy["target"] == "goto_recon_scan_center"


def test_recon_scan_failed_jumps_to_return_home() -> None:
    """recon fixed_view_localize failed → jump_to return_home."""
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    policy = by_label["recon_scan"]["on_failed"]
    assert policy["action"] == "jump_to"
    assert policy["target"] == "return_home"


def test_select_recon_targets_failed_jumps_to_return_home() -> None:
    """select_recon_targets failed → jump_to return_home."""
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    policy = by_label["select_recon_targets"]["on_failed"]
    assert policy["action"] == "jump_to"
    assert policy["target"] == "return_home"


def test_drop_sequence_failed_continues_to_recon() -> None:
    """drop_sequence failed → continue to recon scan (test via continue action)."""
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["drop_sequence"]["on_failed"]["action"] == "continue"


def test_return_home_failed_continues_to_land() -> None:
    """return_home failed → continue to land_home."""
    data = _template(FULL_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["return_home"]["on_failed"]["action"] == "continue"


# ── drop_two_targets_v2 安全兜底策略测试 ─────────────────────────────


def test_drop_two_targets_v2_multi_view_localize_retries_then_returns_home() -> None:
    """drop_two_targets_v2: multi_view_localize 失败后重试一次，再失败则返航。"""
    path = Path("config/action_missions/drop_two_targets_v2.json")
    data = _template(path)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    labels = {step.get("label", "") for step in data["steps"] if step.get("label")}

    policy = by_label["drop_gps_multi_view_scan"]["on_failed"]
    assert policy["action"] == "retry_current_then_jump_to"
    assert policy["max_attempts"] == 2
    assert policy["target"] == "return_home_gps"
    assert "return_home_gps" in labels
    assert "land_home" in labels


def test_drop_two_targets_v2_sitl_profile_matches_base() -> None:
    """rk3588-sitl profile 下的 drop_two_targets_v2 与 base 保持一致。"""
    base_path = Path("config/action_missions/drop_two_targets_v2.json")
    sitl_path = Path("config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json")
    assert _template(sitl_path) == _template(base_path)


# ── validator 错误场景测试 ─────────────────────────────────────────────


def _write_temp_template(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "test_template.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_validator_rejects_retry_current_then_jump_to_missing_target(tmp_path: Path) -> None:
    """retry_current_then_jump_to 指向不存在的 label 时 validator 必须报错。"""
    data = {
        "name": "bad_retry_jump",
        "steps": [
            {
                "name": "fixed_view_localize",
                "label": "scan",
                "params": {},
                "on_failed": {
                    "action": "retry_current_then_jump_to",
                    "max_attempts": 2,
                    "target": "missing_label",
                },
            }
        ],
    }
    path = _write_temp_template(tmp_path, data)
    with pytest.raises(ValueError, match="target not found"):
        validate_templates([path])


def test_validator_rejects_retry_current_then_jump_to_zero_max_attempts(tmp_path: Path) -> None:
    """retry_current_then_jump_to 的 max_attempts < 1 时 validator 必须报错。"""
    data = {
        "name": "bad_retry_attempts",
        "steps": [
            {
                "name": "fixed_view_localize",
                "label": "scan",
                "params": {},
                "on_failed": {
                    "action": "retry_current_then_jump_to",
                    "max_attempts": 0,
                    "target": "scan",
                },
            }
        ],
    }
    path = _write_temp_template(tmp_path, data)
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        validate_templates([path])


# ── rescue_2026_full_auto_v2 tests ─────────────────────────────────────


def test_recon_scan_v2_retries_then_returns_home() -> None:
    """rescue_2026_full_auto_v2: recon_scan failed → retry_current_then_jump_to return_home."""
    data = _template(FULL_V2_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    policy = by_label["recon_gps_multi_view_scan"]["on_failed"]
    assert policy["action"] == "retry_current_then_jump_to"
    assert policy["max_attempts"] == 2
    assert policy["target"] == "return_home_gps"


def test_recon_sequence_v2_target_lock_camera() -> None:
    """rescue_2026_full_auto_v2: recon_sequence target_lock has camera 85/69/1/-1."""
    data = _template(FULL_V2_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    camera = by_label["gps_recon_sequence"]["params"]["target_lock"]["camera"]
    assert camera["fov_x_deg"] == 68.15
    assert camera["fov_y_deg"] == 54.3
    assert camera["image_x_sign"] == 1.0
    assert camera["image_y_sign"] == -1.0


def test_select_recon_targets_v2_zone_center_mode_field() -> None:
    """rescue_2026_full_auto_v2: select_recon_targets zone_center_mode is field."""
    data = _template(FULL_V2_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["select_gps_recon_targets"]["params"]["coordinate_mode"] == "gps_enu"


def test_full_rescue_v2_has_12_steps() -> None:
    data = _template(FULL_V2_TEMPLATE_PATH)
    assert len(data["steps"]) == 12


def test_sitl_profile_matches_base_full_v2_template() -> None:
    """rk3588-sitl profile 下的 rescue_2026_full_auto_v2 与 base 保持一致。"""
    sitl_path = Path("config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json")
    base = _template(FULL_V2_TEMPLATE_PATH)
    sitl = _template(sitl_path)
    assert sitl == base


def test_validator_includes_rescue_2026_full_auto_v2_by_default() -> None:
    """validator 默认包含 rescue_2026_full_auto_v2。"""
    from scripts.validate_action_missions import DEFAULT_TEMPLATE_PATHS as v_paths
    v2_path = Path("config/action_missions/rescue_2026_full_auto_v2.json")
    assert any(p.name == v2_path.name for p in v_paths)


# ── zone_center_mode template tests ─────────────────────────────────────


def test_select_drop_targets_v2_zone_center_mode_field() -> None:
    """rescue_2026_full_auto_v2: select_drop_targets zone_center_mode is field."""
    data = _template(FULL_V2_TEMPLATE_PATH)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["select_gps_drop_targets"]["params"]["coordinate_mode"] == "gps_enu"
    assert by_label["select_gps_drop_targets"]["params"]["objects"] == "$drop_scan.localized_objects"
    assert by_label["select_gps_drop_targets"]["params"]["objects"] == "$drop_scan.localized_objects"
    assert by_label["select_gps_drop_targets"]["params"]["min_seen_count"] == 2


def test_drop_two_targets_v2_select_drop_targets_uses_gps_enu() -> None:
    data = _template(Path("config/action_missions/drop_two_targets_v2.json"))
    by_label = {step.get("label", ""): step for step in data["steps"]}
    params = by_label["select_gps_drop_targets"]["params"]
    assert params["coordinate_mode"] == "gps_enu"
    assert "zone_center_mode" not in params


# ── recon_inspect_5_targets_stepwise_v2 tests ────────────────────────────


def test_recon_inspect_stepwise_v2_loads() -> None:
    """recon_inspect_5_targets_stepwise_v2.json 能加载且有 8 个步骤。"""
    path = Path("config/action_missions/recon_inspect_5_targets_stepwise_v2.json")
    data = _template(path)
    assert data["name"] == "recon_inspect_5_targets_stepwise_v2"
    assert len(data["steps"]) == 8
    labels = [step.get("label", "") for step in data["steps"] if step.get("label")]
    assert "recon_scan" in labels
    assert "select_recon_targets" in labels
    assert "recon_sequence" in labels
    assert "build_recon_report" in labels
    assert "return_home" in labels
    assert "land_home" in labels


def test_recon_inspect_stepwise_v2_target_lock_camera() -> None:
    """recon_inspect_5_targets_stepwise_v2: recon_sequence target_lock.camera 85/69/1/-1。"""
    path = Path("config/action_missions/recon_inspect_5_targets_stepwise_v2.json")
    data = _template(path)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    camera = by_label["recon_sequence"]["params"]["target_lock"]["camera"]
    assert camera["fov_x_deg"] == 85.0
    assert camera["fov_y_deg"] == 69.0
    assert camera["image_x_sign"] == 1.0
    assert camera["image_y_sign"] == -1.0


def test_recon_inspect_stepwise_v2_zone_center_mode_field() -> None:
    """recon_inspect_5_targets_stepwise_v2: select_recon_targets zone_center_mode=field。"""
    path = Path("config/action_missions/recon_inspect_5_targets_stepwise_v2.json")
    data = _template(path)
    by_label = {step.get("label", ""): step for step in data["steps"]}
    assert by_label["select_recon_targets"]["params"]["zone_center_mode"] == "field"


def test_recon_inspect_stepwise_v2_sitl_matches_base() -> None:
    """recon_inspect_5_targets_stepwise_v2: SITL profile 与 base 一致。"""
    base = _template(Path("config/action_missions/recon_inspect_5_targets_stepwise_v2.json"))
    sitl = _template(Path("config/profiles/rk3588-sitl/action_missions/recon_inspect_5_targets_stepwise_v2.json"))
    assert sitl == base


def test_recon_inspect_stepwise_v2_validates() -> None:
    """recon_inspect_5_targets_stepwise_v2 能通过 validator。"""
    from scripts.validate_action_missions import validate_templates
    path = Path("config/action_missions/recon_inspect_5_targets_stepwise_v2.json")
    messages = validate_templates([path])
    assert len(messages) == 1
    assert "OK" in messages[0]
