from __future__ import annotations

import json

import pytest

from missions.common.actions.result import ActionResult
from missions.common.actions.survey_area import SurveyAreaAction


def _params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "waypoints": [{"x": 1.0, "y": 2.0, "altitude_m": 5.0}],
        "capture_updates_per_waypoint": 1,
        "max_updates_per_waypoint": 10,
    }
    params.update(overrides)
    return params


def _at_waypoint(x: float = 1.0, y: float = 2.0, altitude_m: float = 5.0) -> dict[str, object]:
    return {
        "local_position": {"x": x, "y": y, "z": -altitude_m},
        "drone": {
            "local_x": x,
            "local_y": y,
            "local_z": -altitude_m,
            "relative_altitude": altitude_m,
            "yaw": 0.0,
        },
    }


def test_start_requires_valid_waypoints() -> None:
    action = SurveyAreaAction()

    with pytest.raises(ValueError):
        action.start({})
    with pytest.raises(ValueError):
        action.start({"waypoints": []})
    with pytest.raises(ValueError):
        action.start({"waypoints": [{"y": 2, "altitude_m": 5}]})
    with pytest.raises(ValueError):
        action.start({"waypoints": [{"x": 1, "altitude_m": 5}]})
    with pytest.raises(ValueError):
        action.start({"waypoints": [{"x": 1, "y": 2}]})
    with pytest.raises(ValueError):
        action.start({"waypoints": [{"x": 1, "y": 2, "altitude_m": 0}]})


def test_start_rejects_invalid_capture_timeout_and_detection_source() -> None:
    action = SurveyAreaAction()

    with pytest.raises(ValueError):
        action.start(_params(capture_updates_per_waypoint=0))
    with pytest.raises(ValueError):
        action.start(_params(capture_updates_per_waypoint=3, max_updates_per_waypoint=2))
    with pytest.raises(ValueError):
        action.start(_params(detection_source="bad"))


def test_update_before_start_fails_without_exception() -> None:
    result = SurveyAreaAction().update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_single_waypoint_without_detection_completes_with_empty_estimates() -> None:
    action = SurveyAreaAction()
    action.start(_params())

    first = action.update({})
    reached = action.update(_at_waypoint())
    done = action.update(_at_waypoint())

    assert first.reason == "survey_goto"
    assert first.actions[0]["action_type"] == "local_position"
    assert reached.reason == "survey_capture_started"
    assert done.done is True
    assert done.reason == "survey_done"
    assert done.detail["estimated_objects"] == []


def test_single_waypoint_scene_detection_outputs_estimated_object_under_drone() -> None:
    action = SurveyAreaAction()
    action.start(
        _params(
            waypoints=[{"x": 10.0, "y": 20.0, "altitude_m": 5.0}],
            class_names={"cylinder"},
        )
    )
    context = _at_waypoint(10.0, 20.0, 5.0)
    context["scene"] = {
        "image_width": 640,
        "image_height": 480,
        "detections": [
            {
                "track_id": 1,
                "class_name": "cylinder",
                "confidence": 0.9,
                "ex": 0.0,
                "ey": 0.0,
            }
        ],
    }

    action.update(context)
    done = action.update(context)

    estimates = done.detail["estimated_objects"]
    assert done.done is True
    assert len(estimates) == 1
    assert estimates[0]["x"] == pytest.approx(10.0)
    assert estimates[0]["y"] == pytest.approx(20.0)
    assert estimates[0]["class_name"] == "cylinder"


def test_perception_detection_source_uses_single_perception_detection() -> None:
    action = SurveyAreaAction()
    action.start(
        _params(
            waypoints=[{"x": 3.0, "y": 4.0, "altitude_m": 5.0}],
            detection_source="perception",
        )
    )
    context = _at_waypoint(3.0, 4.0, 5.0)
    context["perception"] = {
        "track_id": 7,
        "class_name": "cylinder",
        "confidence": 0.9,
        "ex": 0.0,
        "ey": 0.0,
        "image_width": 640,
        "image_height": 480,
    }

    action.update(context)
    done = action.update(context)

    assert done.done is True
    assert done.detail["estimated_objects"][0]["track_ids"] == [7]


def test_multiple_waypoints_advance_and_finish() -> None:
    action = SurveyAreaAction()
    action.start(
        _params(
            waypoints=[
                {"x": 1.0, "y": 2.0, "altitude_m": 5.0},
                {"x": 3.0, "y": 4.0, "altitude_m": 5.0},
            ]
        )
    )

    assert action.update(_at_waypoint(1.0, 2.0)).reason == "survey_capture_started"
    next_result = action.update(_at_waypoint(1.0, 2.0))
    assert next_result.reason == "survey_next_waypoint"
    assert next_result.detail["waypoint_index"] == 1

    assert action.update(_at_waypoint(3.0, 4.0)).reason == "survey_capture_started"
    done = action.update(_at_waypoint(3.0, 4.0))
    assert done.done is True
    assert done.reason == "survey_done"


def test_goto_not_finished_returns_local_position_action() -> None:
    action = SurveyAreaAction()
    action.start(_params())

    result = action.update({"local_position": {"x": 10.0, "y": 10.0, "z": -5.0}})

    assert result.reason == "survey_goto"
    assert result.done is False
    assert result.actions[0]["action_type"] == "local_position"


def test_stop_makes_later_update_done_without_actions() -> None:
    action = SurveyAreaAction()
    action.start(_params())

    action.stop()
    result = action.update({})

    assert result.done is True
    assert result.reason == "stopped"
    assert result.actions == []


def test_reset_returns_to_not_started_state() -> None:
    action = SurveyAreaAction()
    action.start(_params())

    action.reset()
    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_waypoint_timeout_stops_later_actions() -> None:
    action = SurveyAreaAction()
    action.start(_params(max_updates_per_waypoint=1))

    first = action.update({"local_position": {"x": 10.0, "y": 10.0, "z": -5.0}})
    timeout = action.update({"local_position": {"x": 10.0, "y": 10.0, "z": -5.0}})
    after = action.update({"local_position": {"x": 10.0, "y": 10.0, "z": -5.0}})

    assert first.actions[0]["action_type"] == "local_position"
    assert timeout.failed is True
    assert timeout.reason == "waypoint_timeout"
    assert timeout.actions == []
    assert after.failed is True
    assert after.reason == "waypoint_timeout"
    assert after.actions == []


def test_goto_failed_enters_failed_state_and_stops_later_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    action = SurveyAreaAction()
    action.start(_params())
    calls = {"count": 0}

    def fail_update(context: dict[str, object]) -> ActionResult:
        calls["count"] += 1
        return ActionResult(failed=True, reason="simulated_goto_failure")

    monkeypatch.setattr(action.goto_action, "update", fail_update)

    first = action.update({})
    second = action.update({})

    assert first.failed is True
    assert first.reason == "goto_failed"
    assert first.actions == []
    assert second.failed is True
    assert second.reason == "goto_failed"
    assert second.actions == []
    assert calls["count"] == 1


def test_localization_unexpected_exception_enters_failed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = SurveyAreaAction()
    action.start(_params())
    context = _at_waypoint()
    context["scene"] = {
        "image_width": 640,
        "image_height": 480,
        "detections": [{"track_id": 1, "confidence": 1.0, "ex": 0.0, "ey": 0.0}],
    }
    action.update(context)

    def raise_boom(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("boom")

    monkeypatch.setattr(action.localizer, "localize_detections", raise_boom)

    failed = action.update(context)
    after = action.update(context)

    assert failed.failed is True
    assert failed.reason == "localization_failed"
    assert failed.actions == []
    assert failed.detail["error"] == "boom"
    assert after.failed is True
    assert after.reason == "localization_failed"
    assert after.actions == []


def test_missing_yaw_defaults_to_zero_and_marks_detail() -> None:
    action = SurveyAreaAction()
    action.start(_params())
    context = {
        "local_position": {"x": 1.0, "y": 2.0, "z": -5.0},
        "drone": {"local_position": {"x": 1.0, "y": 2.0, "z": -5.0}},
        "scene": {
            "image_width": 640,
            "image_height": 480,
            "detections": [{"track_id": 1, "confidence": 1.0, "ex": 0.0, "ey": 0.0}],
        },
    }

    action.update(context)
    done = action.update(context)

    assert done.done is True
    assert done.detail["yaw_defaulted"] is True
    assert done.detail["estimated_objects"][0]["x"] == pytest.approx(1.0)


def test_outputs_plain_dicts_and_json_serializable_estimates() -> None:
    action = SurveyAreaAction()
    action.start(_params())
    first = action.update({})
    context = _at_waypoint()
    context["scene"] = {
        "image_width": 640,
        "image_height": 480,
        "detections": [{"track_id": 1, "class_name": "cylinder", "confidence": 1, "ex": 0, "ey": 0}],
    }

    action.update(context)
    done = action.update(context)

    assert isinstance(first.actions[0], dict)
    json.dumps(done.detail["estimated_objects"])


def test_yaw_mode_arm_heading_passes_yaw_to_action() -> None:
    action = SurveyAreaAction()
    action.start(
        _params(
            waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 5.0}],
            yaw_mode="arm_heading",
        )
    )

    result = action.update({
        "local_position": {"x": 10.0, "y": 10.0, "z": -5.0},
        "arm_heading_yaw_rad": 1.23,
    })

    assert result.reason == "survey_goto"
    assert result.actions[0]["params"]["yaw"] == pytest.approx(1.23)
