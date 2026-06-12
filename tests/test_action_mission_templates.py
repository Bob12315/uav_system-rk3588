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
            ]
        },
    )
    blackboard.set(
        "recon_scan",
        {
            "recon_report": {
                "barrels": [
                    {"id": "recon_1", "content": "danger_1", "confidence": 0.8}
                ]
            }
        },
    )

    for path in TEMPLATE_PATHS:
        data = _template(path)

        for step in data["steps"]:
            blackboard.resolve(step.get("params") or {})


def test_full_rescue_template_contains_recon_scan_after_two_drops() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    steps = data["steps"]
    names = [step["name"] for step in steps]
    payload_indices = [index for index, step in enumerate(steps) if step["name"] == "payload_release"]
    recon_index = names.index("recon_scan")
    land_index = names.index("land")

    assert len(payload_indices) == 2
    assert payload_indices[1] < recon_index < land_index
    assert land_index == len(steps) - 1


def test_full_rescue_template_save_as_names() -> None:
    data = _template(FULL_TEMPLATE_PATH)
    by_name = {step["name"]: step for step in data["steps"]}

    assert by_name["multi_view_localize"]["save_as"] == "drop_scan"
    assert by_name["select_drop_targets"]["save_as"] == "drop_targets"
    assert by_name["recon_scan"]["save_as"] == "recon_scan"


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
