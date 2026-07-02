from __future__ import annotations

import pytest

from app.mission_orchestrator import MissionBlackboard


def test_blackboard_set_and_get_path() -> None:
    blackboard = MissionBlackboard()

    blackboard.set("drop_scan", {"localized_objects": [{"local_x": 1.2}]})

    assert blackboard.get_path("drop_scan.localized_objects.0.local_x") == 1.2


def test_blackboard_resolve_recurses_dicts_and_lists() -> None:
    blackboard = MissionBlackboard()
    blackboard.set(
        "drop_scan",
        {
            "class_name": "bucket",
            "localized_objects": [
                {"local_x": 1.2, "local_y": 30.5},
            ],
        },
    )

    resolved = blackboard.resolve(
        {
            "target": {
                "x": "$drop_scan.localized_objects.0.local_x",
                "y": "$drop_scan.localized_objects.0.local_y",
            },
            "classes": ["bucket", "$drop_scan.class_name"],
            "altitude_m": 2.5,
        }
    )

    assert resolved == {
        "target": {"x": 1.2, "y": 30.5},
        "classes": ["bucket", "bucket"],
        "altitude_m": 2.5,
    }


def test_blackboard_missing_key_raises() -> None:
    blackboard = MissionBlackboard()

    with pytest.raises(KeyError):
        blackboard.resolve("$missing.value")


def test_blackboard_rejects_empty_name_and_path() -> None:
    blackboard = MissionBlackboard()

    with pytest.raises(ValueError):
        blackboard.set(" ", {})
    with pytest.raises(ValueError):
        blackboard.get_path("")
