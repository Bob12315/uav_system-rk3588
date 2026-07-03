from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.mission_orchestrator import MissionActionStep, MissionBlackboard
from missions.common.actions.action_lab import create_action_lab_registry


TEMPLATE_PATHS = [
    Path("config/action_missions/drop_two_targets_v1.json"),
    Path("config/action_missions/rescue_2026_full_auto.json"),
]
DROP_TEMPLATE_PATH = TEMPLATE_PATHS[0]
FULL_TEMPLATE_PATH = TEMPLATE_PATHS[1]
REQUIRED_REFERENCES = {
    "$drop_scan.localized_objects",
    "$drop_targets.selected_targets.0.local_x",
    "$drop_targets.selected_targets.0.local_y",
    "$drop_targets.selected_targets.1.local_x",
    "$drop_targets.selected_targets.1.local_y",
}
ALLOWED_FAILURE_ACTIONS = {"fail", "retry_current", "jump_to", "continue"}


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
            assert params["yaw_mode"] == "field_heading"
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
    for path in TEMPLATE_PATHS:
        data = _template(path)
        refs = _references(data["steps"])

        assert REQUIRED_REFERENCES <= refs


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
        assert steps[1].save_as == "drop_scan"
        assert steps[2].save_as == "drop_targets"


def test_action_mission_templates_blackboard_references_resolve() -> None:
    blackboard = MissionBlackboard()
    blackboard.set(
        "drop_scan",
        {
            "localized_objects": [
                {"id": "b1", "local_x": 1.0, "local_y": 30.0},
                {"id": "b2", "local_x": -1.0, "local_y": 31.0},
            ]
        },
    )
    blackboard.set(
        "drop_targets",
        {
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
            "target_slots": [
                {"valid": True, "id": "r1", "class_name": "bucket", "local_x": 1.0, "local_y": 5.0, "x": 1.0, "y": 5.0, "rank": 1},
                {"valid": False, "id": "missing_1", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 2, "status": "missing"},
                {"valid": False, "id": "missing_2", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 3, "status": "missing"},
                {"valid": False, "id": "missing_3", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 4, "status": "missing"},
                {"valid": False, "id": "missing_4", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "rank": 5, "status": "missing"},
            ],
        },
    )
    for i in range(5):
        blackboard.set(
            f"recon_result_{i}",
            {"target_id": f"recon_{i}", "content": "blank", "status": "blank_or_uncertain"},
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
    payload_indices = [index for index, step in enumerate(steps) if step["name"] == "payload_release"]
    recon_index = labels.index("recon_scan")
    land_index = labels.index("return_home")

    assert len(payload_indices) == 2
    assert payload_indices[1] < recon_index < land_index
    assert steps[-1]["name"] == "land"
    assert land_index == len(steps) - 2  # return_home is second-to-last, land is last


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
