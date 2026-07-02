from __future__ import annotations

import json

import pytest

from missions.common.actions.target_lock import TargetLockAction


def _params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {"target": {"x": 10.0, "y": 20.0}}
    params.update(overrides)
    return params


def _context(
    *,
    x: float = 10.0,
    y: float = 20.0,
    altitude_m: float = 5.0,
    detections: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "drone": {
            "local_x": x,
            "local_y": y,
            "local_z": -altitude_m,
            "relative_altitude": altitude_m,
            "yaw": 0.0,
        },
        "scene": {
            "image_width": 640,
            "image_height": 480,
            "detections": detections if detections is not None else [],
        },
    }


def test_start_requires_valid_params() -> None:
    action = TargetLockAction()

    with pytest.raises(ValueError):
        action.start({})
    with pytest.raises(ValueError):
        action.start({"target": {"x": 1.0}})
    with pytest.raises(ValueError):
        action.start(_params(max_match_distance_m=0.0))
    with pytest.raises(ValueError):
        action.start(_params(min_confidence=-0.1))
    with pytest.raises(ValueError):
        action.start(_params(detection_source="bad"))
    with pytest.raises(ValueError):
        action.start(_params(max_updates=0))


def test_update_before_start_fails_without_exception() -> None:
    result = TargetLockAction().update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_scene_detection_locks_target_under_drone() -> None:
    action = TargetLockAction()
    action.start(_params())
    context = _context(
        detections=[
            {"track_id": 7, "class_name": "cylinder", "confidence": 0.9, "ex": 0.0, "ey": 0.0}
        ]
    )

    result = action.update(context)

    assert result.done is True
    assert result.reason == "target_locked"
    assert result.actions == [
        {
            "action_type": "yolo_lock_target",
            "params": {"track_id": 7},
            "key": "target_lock",
            "once": True,
            "priority": 5,
        }
    ]


def test_perception_detection_locks_target() -> None:
    action = TargetLockAction()
    action.start(_params(detection_source="perception"))
    context = {
        "drone": {
            "local_x": 10.0,
            "local_y": 20.0,
            "local_z": -5.0,
            "relative_altitude": 5.0,
            "yaw": 0.0,
        },
        "perception": {
            "track_id": 8,
            "class_name": "cylinder",
            "confidence": 0.9,
            "ex": 0.0,
            "ey": 0.0,
            "image_width": 640,
            "image_height": 480,
        },
    }

    result = action.update(context)

    assert result.done is True
    assert result.actions[0]["params"]["track_id"] == 8


def test_class_names_filter_controls_locking() -> None:
    context = _context(
        detections=[
            {"track_id": 1, "class_name": "hazard", "confidence": 0.9, "ex": 0.0, "ey": 0.0}
        ]
    )
    action = TargetLockAction()
    action.start(_params(class_names={"cylinder"}))

    missing = action.update(context)

    assert missing.reason == "target_not_found"
    assert missing.actions == []

    action.reset()
    action.start(_params(class_names={"hazard"}))
    locked = action.update(context)
    assert locked.reason == "target_locked"
    assert locked.actions[0]["params"]["track_id"] == 1


def test_min_confidence_filter_controls_locking() -> None:
    action = TargetLockAction()
    action.start(_params(min_confidence=0.8))
    context = _context(
        detections=[
            {"track_id": 1, "class_name": "cylinder", "confidence": 0.5, "ex": 0.0, "ey": 0.0}
        ]
    )

    result = action.update(context)

    assert result.reason == "target_not_found"
    assert result.actions == []


def test_nearest_estimate_is_selected() -> None:
    action = TargetLockAction()
    action.start(_params(target={"x": 10.0, "y": 20.0}, max_match_distance_m=20.0))
    context = _context(
        detections=[
            {"track_id": 1, "confidence": 0.9, "ex": 0.5, "ey": 0.0},
            {"track_id": 2, "confidence": 0.9, "ex": 0.0, "ey": 0.0},
        ]
    )

    result = action.update(context)

    assert result.reason == "target_locked"
    assert result.actions[0]["params"]["track_id"] == 2


def test_target_outside_max_match_distance_is_not_locked() -> None:
    action = TargetLockAction()
    action.start(_params(target={"x": 100.0, "y": 100.0}, max_match_distance_m=1.0))
    context = _context(
        detections=[
            {"track_id": 1, "class_name": "cylinder", "confidence": 0.9, "ex": 0.0, "ey": 0.0}
        ]
    )

    result = action.update(context)

    assert result.reason == "target_not_found"
    assert result.actions == []
    assert result.detail["best_distance_m"] is not None


def test_matched_estimate_without_track_id_does_not_lock() -> None:
    action = TargetLockAction()
    action.start(_params())
    context = _context(detections=[{"confidence": 0.9, "ex": 0.0, "ey": 0.0}])

    result = action.update(context)

    assert result.reason == "target_without_track_id"
    assert result.actions == []


def test_invalid_track_id_does_not_lock() -> None:
    action = TargetLockAction()
    action.start(_params())
    context = _context(detections=[{"track_id": "bad", "confidence": 0.9, "ex": 0.0, "ey": 0.0}])

    result = action.update(context)

    assert result.reason == "invalid_track_id"
    assert result.actions == []


def test_timeout_is_stable_and_sends_no_actions() -> None:
    action = TargetLockAction()
    action.start(_params(max_updates=1))

    first = action.update(_context())
    timeout = action.update(_context())
    after = action.update(_context(detections=[{"track_id": 1, "ex": 0.0, "ey": 0.0}]))

    assert first.reason == "target_not_found"
    assert timeout.failed is True
    assert timeout.reason == "target_lock_timeout"
    assert timeout.actions == []
    assert after.failed is True
    assert after.reason == "target_lock_timeout"
    assert after.actions == []


def test_stop_makes_later_update_done_without_actions() -> None:
    action = TargetLockAction()
    action.start(_params())

    action.stop()
    result = action.update({})

    assert result.done is True
    assert result.reason == "stopped"
    assert result.actions == []


def test_reset_returns_to_not_started_state() -> None:
    action = TargetLockAction()
    action.start(_params())

    action.reset()
    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_missing_yaw_defaults_to_zero_and_marks_detail() -> None:
    action = TargetLockAction()
    action.start(_params())
    context = {
        "drone": {"local_position": {"x": 10.0, "y": 20.0, "z": -5.0}},
        "scene": {
            "image_width": 640,
            "image_height": 480,
            "detections": [{"track_id": 1, "confidence": 1.0, "ex": 0.0, "ey": 0.0}],
        },
    }

    result = action.update(context)

    assert result.reason == "target_locked"
    assert result.detail["yaw_defaulted"] is True


def test_missing_drone_context_does_not_crash() -> None:
    action = TargetLockAction()
    action.start(_params())
    context = {
        "scene": {
            "image_width": 640,
            "image_height": 480,
            "detections": [{"track_id": 1, "confidence": 1.0, "ex": 0.0, "ey": 0.0}],
        }
    }

    result = action.update(context)

    assert result.reason == "target_not_found"
    assert result.actions == []
    assert "localization_error" in result.detail


def test_no_detection_does_not_require_localization_error() -> None:
    action = TargetLockAction()
    action.start(_params())

    result = action.update({"scene": {"detections": []}})

    assert result.reason == "target_not_found"
    assert result.actions == []
    assert "localization_error" not in result.detail


def test_drone_local_position_missing_z_reports_localization_error() -> None:
    action = TargetLockAction()
    action.start(_params())
    context = {
        "drone": {"local_position": {"x": 10.0, "y": 20.0}},
        "scene": {
            "detections": [{"track_id": 1, "confidence": 1.0, "ex": 0.0, "ey": 0.0}],
        },
    }

    result = action.update(context)

    assert result.reason == "target_not_found"
    assert result.actions == []
    assert "localization_error" in result.detail


def test_localization_exception_is_reported_as_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    action = TargetLockAction()
    action.start(_params())

    def raise_boom(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("boom")

    monkeypatch.setattr(action.localizer, "localize_detections", raise_boom)

    result = action.update(
        _context(detections=[{"track_id": 1, "confidence": 1.0, "ex": 0.0, "ey": 0.0}])
    )

    assert result.reason == "target_not_found"
    assert result.detail["localization_error"] == "boom"


def test_done_update_does_not_repeat_lock_action() -> None:
    action = TargetLockAction()
    action.start(_params())
    result = action.update(
        _context(detections=[{"track_id": 7, "confidence": 0.9, "ex": 0.0, "ey": 0.0}])
    )

    after = action.update(_context(detections=[{"track_id": 8, "confidence": 0.9, "ex": 0.0, "ey": 0.0}]))

    assert result.actions[0]["params"]["track_id"] == 7
    assert after.done is True
    assert after.reason == "target_locked"
    assert after.actions == []
    assert after.detail["locked_track_id"] == 7


def test_output_is_plain_dict_and_json_serializable() -> None:
    action = TargetLockAction()
    action.start(_params(key="custom_lock", lock_once=False, priority=9))

    result = action.update(
        _context(detections=[{"track_id": 7, "class_name": "cylinder", "confidence": 1, "ex": 0, "ey": 0}])
    )

    assert isinstance(result.actions[0], dict)
    assert result.actions[0]["key"] == "custom_lock"
    assert result.actions[0]["once"] is False
    assert result.actions[0]["priority"] == 9
    json.dumps(result.to_dict())
