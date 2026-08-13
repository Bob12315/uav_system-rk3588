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


def test_require_track_id_true_with_track_id():
    """require_track_id=True (default): detection with track_id → done with yolo_lock_target."""
    action = GpsTargetLockAction()
    action.start({
        "target": {"lat": 34.100001, "lon": 108.100001},
        "max_match_distance_m": 50.0,
        "max_updates": 10,
        "class_names": ["bucket"],
        "require_track_id": True,
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
