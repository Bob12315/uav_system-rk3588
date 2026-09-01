"""Tests for GpsTargetLockAction require_track_id parameter."""
from __future__ import annotations

import pytest
from missions.common.actions.gps_target_lock import GpsTargetLockAction
from missions.common.actions.result import ActionResult


def _lock_context(track_id=None):
    """Build minimal context for GpsTargetLockAction.update() with a detection."""
    det = {
        "class_name": "bucket",
        "confidence": 0.9,
        "cx": 320, "cy": 240,
        "capture_telemetry": {
            "drone_lat": 34.1,
            "drone_lon": 108.1,
            "drone_yaw_rad": 1.5,
            "relative_altitude_m": 2.5,
        },
    }
    if track_id is not None:
        det["track_id"] = track_id
    return {
        "scene": {
            "detections": [det],
            "image_width": 640,
            "image_height": 480,
        },
        "drone": {"lat": 34.1, "lon": 108.1, "yaw": 1.5, "relative_altitude": 2.5},
    }


def _confirmed_context(track_id=42):
    context = _lock_context(track_id=track_id)
    context["perception"] = {
        "target_valid": True,
        "tracking_state": "locked",
        "track_id": track_id,
        "target_age_s": 0.1,
    }
    return context


def test_require_track_id_true_with_track_id():
    """require_track_id=True (default): detection with track_id → done with yolo_lock_target."""
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001},
        "max_match_distance_m": 50.0,
        "max_updates": 10,
        "class_names": ["bucket"],
        "require_track_id": True,
        "require_lock_confirmation": False,
    })
    result = action.update(_lock_context(track_id=42))
    assert result.done
    assert result.reason == "gps_target_locked"
    assert any(a["action_type"] == "yolo_lock_target" for a in result.actions)
    assert result.detail["locked_track_id"] == 42
    assert result.detail["best_distance_m"] is not None
    assert "matched_without_track_id" not in result.detail


def test_require_track_id_true_without_track_id():
    """require_track_id=True (default): detection without track_id → still searching."""
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001},
        "max_match_distance_m": 50.0,
        "max_updates": 10,
        "class_names": ["bucket"],
        "require_track_id": True,
        "require_lock_confirmation": False,
    })
    result = action.update(_lock_context(track_id=None))
    assert not result.done
    assert not result.failed
    assert result.reason == "gps_target_lock_searching"


def test_require_track_id_false_with_track_id():
    """require_track_id=False: detection with track_id → done with yolo_lock_target."""
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001},
        "max_match_distance_m": 50.0,
        "max_updates": 10,
        "class_names": ["bucket"],
        "require_track_id": False,
        "require_lock_confirmation": False,
    })
    result = action.update(_lock_context(track_id=42))
    assert result.done
    assert result.reason == "gps_target_locked"
    assert any(a["action_type"] == "yolo_lock_target" for a in result.actions)
    assert result.detail["locked_track_id"] == 42
    assert result.detail["best_distance_m"] is not None
    assert "matched_without_track_id" not in result.detail


def test_require_track_id_false_without_track_id():
    """require_track_id=False: detection without track_id → done without yolo_lock_target."""
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001},
        "max_match_distance_m": 50.0,
        "max_updates": 10,
        "class_names": ["bucket"],
        "require_track_id": False,
        "require_lock_confirmation": False,
    })
    result = action.update(_lock_context(track_id=None))
    assert result.done
    assert result.reason == "gps_target_locked"
    # Should NOT emit yolo_lock_target since no track_id
    assert not any(a["action_type"] == "yolo_lock_target" for a in result.actions)
    assert result.detail["matched_without_track_id"] is True
    assert result.detail["best_distance_m"] is not None
    assert result.detail["matched_detection_gps"] is not None
    assert "locked_track_id" not in result.detail


def test_lock_confirmation_waits_for_matching_yolo_track_and_outputs_identity():
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001, "class_name": "bucket"},
        "max_match_distance_m": 50.0,
        "max_updates": 10,
        "class_names": ["bucket"],
        "require_track_id": True,
        "require_class_match": True,
        "require_lock_confirmation": True,
    })

    requested = action.update(_lock_context(track_id=42))
    assert not requested.done and not requested.failed
    assert requested.reason == "gps_target_lock_requested"
    assert requested.actions[0]["params"]["track_id"] == 42

    waiting = action.update(_confirmed_context(track_id=7))
    assert not waiting.done and waiting.reason == "gps_target_lock_waiting"
    assert waiting.detail["lock_error"] == "target_track_id_mismatch"

    confirmed = action.update(_confirmed_context(track_id=42))
    assert confirmed.done and not confirmed.failed
    assert confirmed.reason == "gps_target_locked"
    assert confirmed.output == {"locked_track_id": 42}


def test_required_class_match_rejects_nearer_wrong_class():
    context = _lock_context(track_id=7)
    context["scene"]["detections"][0]["class_name"] = "bucket_2"
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001, "class_name": "bucket_1"},
        "max_match_distance_m": 50.0,
        "max_updates": 3,
        "class_names": ["bucket_1", "bucket_2"],
        "require_track_id": True,
        "require_class_match": True,
        "require_lock_confirmation": False,
    })

    result = action.update(context)
    assert not result.done and not result.failed
    assert result.reason == "gps_target_lock_searching"


def test_invalid_target_slot_is_rejected_before_search():
    action = GpsTargetLockAction()
    with pytest.raises((TypeError, ValueError)):
        action.start({
            "target": {"valid": False, "lat": None, "lon": None, "class_name": ""},
            "require_track_id": True,
            "require_lock_confirmation": True,
        })


def test_close_competing_matches_are_rejected_as_ambiguous():
    context = _lock_context(track_id=7)
    context["scene"]["detections"].append(
        dict(context["scene"]["detections"][0], track_id=8)
    )
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001, "class_name": "bucket"},
        "max_match_distance_m": 50.0,
        "min_match_margin_m": 0.25,
        "max_updates": 3,
        "class_names": ["bucket"],
        "require_track_id": True,
        "require_class_match": True,
        "require_lock_confirmation": True,
    })

    result = action.update(context)
    assert not result.done and not result.failed
    assert result.reason == "gps_target_lock_ambiguous"
    assert result.detail["second_best_distance_m"] == result.detail["best_distance_m"]


def test_nearest_image_center_does_not_require_gps_projection():
    context = _lock_context(track_id=42)
    context["scene"]["detections"][0]["class_name"] = "bucket_2"
    context["scene"]["detections"].append(
        dict(context["scene"]["detections"][0], track_id=99, cx=500)
    )
    for detection in context["scene"]["detections"]:
        detection.pop("capture_telemetry")
    context["drone"] = {}
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.1, "lon": 108.1, "class_name": "bucket_1"},
        "selection_mode": "nearest_image_center",
        "max_updates": 3,
        "class_names": ["bucket_1", "bucket_2"],
        "require_track_id": True,
        "require_class_match": False,
        "require_lock_confirmation": False,
    })

    result = action.update(context)

    assert result.done and result.output["locked_track_id"] == 42
    assert result.detail["selection_mode"] == "nearest_image_center"
    assert result.detail["best_center_distance_norm"] == 0.0
    assert result.detail["best_distance_m"] is None
