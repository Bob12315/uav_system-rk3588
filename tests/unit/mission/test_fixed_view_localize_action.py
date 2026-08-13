from __future__ import annotations

import pytest

from missions.common.actions.action_lab import create_action_lab_registry
from missions.common.actions.fixed_view_localize import FixedViewLocalizeAction


def _make_detection(ex: float = 0.0, ey: float = 0.0, class_name: str = "bucket_1", confidence: float = 0.8) -> dict:
    return {"ex": ex, "ey": ey, "class_name": class_name, "confidence": confidence}


def _make_drone(local_x: float = 0.0, local_y: float = 32.5, altitude: float = 5.0, yaw: float = 0.0) -> dict:
    return {"local_x": local_x, "local_y": local_y, "local_z": -altitude, "yaw": yaw, "relative_altitude": altitude}


def _make_context(detections: list[dict], drone: dict | None = None) -> dict:
    return {
        "scene": {"detections": detections, "image_width": 640, "image_height": 480},
        "drone": drone or _make_drone(),
    }


def _run_settle_and_capture(action: FixedViewLocalizeAction, settle: int, capture: int, detections: list[dict], drone: dict | None = None) -> None:
    """Drive the action through settle + capture phases."""
    for _ in range(settle + capture):
        action.update(_make_context(detections, drone))


# ── 1. Registry ─────────────────────────────────────────────────────


def test_registry_contains_fixed_view_localize() -> None:
    registry = create_action_lab_registry()
    assert "fixed_view_localize" in set(registry.list())


# ── 2. Single target fusion ────────────────────────────────────────


def test_multi_frame_single_target_fuses_to_one_object() -> None:
    action = FixedViewLocalizeAction()
    action.start({
        "detection_source": "scene",
        "class_names": ["bucket_1"],
        "min_confidence": 0.35,
        "settle_updates": 2,
        "capture_updates": 5,
        "max_updates": 30,
        "camera": {"fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0},
        "fusion": {"cluster_radius_m": 0.7, "outlier_radius_m": 0.8, "min_cluster_size": 2, "max_cluster_radius_m": 0.9, "center_weight_power": 1.0, "max_objects": 5},
    })

    det = _make_detection(ex=0.0, ey=0.0, class_name="bucket_1", confidence=0.8)
    for _ in range(20):
        result = action.update(_make_context([det]))

    assert result.done is True
    assert result.failed is False
    assert len(result.detail["localized_objects"]) == 1
    obj = result.detail["localized_objects"][0]
    assert obj["class_name"] == "bucket_1"
    assert obj["count"] >= 2


# ── 3. Two separated targets fuse to two objects ───────────────────


def test_multi_frame_two_separated_targets_fuse_to_two() -> None:
    action = FixedViewLocalizeAction()
    action.start({
        "detection_source": "scene",
        "class_names": ["bucket_1", "bucket_2"],
        "min_confidence": 0.35,
        "settle_updates": 2,
        "capture_updates": 5,
        "max_updates": 30,
        "camera": {"fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0},
        "fusion": {"cluster_radius_m": 0.7, "outlier_radius_m": 0.8, "min_cluster_size": 2, "max_cluster_radius_m": 0.9, "center_weight_power": 1.0, "max_objects": 5},
    })

    det1 = _make_detection(ex=-0.3, ey=-0.3, class_name="bucket_1", confidence=0.8)
    det2 = _make_detection(ex=0.3, ey=0.3, class_name="bucket_2", confidence=0.8)
    for _ in range(20):
        result = action.update(_make_context([det1, det2]))

    assert result.done is True
    assert result.failed is False
    assert len(result.detail["localized_objects"]) == 2
    class_names = sorted(obj["class_name"] for obj in result.detail["localized_objects"])
    assert class_names == ["bucket_1", "bucket_2"]


# ── 4. Low confidence filtered ─────────────────────────────────────


def test_low_confidence_detections_filtered() -> None:
    action = FixedViewLocalizeAction()
    action.start({
        "detection_source": "scene",
        "class_names": ["bucket_1"],
        "min_confidence": 0.5,
        "settle_updates": 2,
        "capture_updates": 5,
        "max_updates": 30,
        "camera": {"fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0},
        "fusion": {"cluster_radius_m": 0.7, "outlier_radius_m": 0.8, "min_cluster_size": 2, "max_cluster_radius_m": 0.9, "center_weight_power": 1.0, "max_objects": 5},
    })

    low_conf = _make_detection(ex=0.0, ey=0.0, class_name="bucket_1", confidence=0.2)
    for _ in range(20):
        result = action.update(_make_context([low_conf]))

    assert result.failed is True
    assert result.reason == "no_target_fused"


# ── 5. Timeout with no detections ──────────────────────────────────


def test_max_updates_timeout_no_detections_fails() -> None:
    action = FixedViewLocalizeAction()
    action.start({
        "detection_source": "scene",
        "class_names": ["bucket_1"],
        "min_confidence": 0.35,
        "settle_updates": 2,
        "capture_updates": 5,
        "max_updates": 10,
        "camera": {"fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0},
        "fusion": {"cluster_radius_m": 0.7, "outlier_radius_m": 0.8, "min_cluster_size": 2, "max_cluster_radius_m": 0.9, "center_weight_power": 1.0, "max_objects": 5},
    })

    result = None
    for _ in range(20):
        result = action.update(_make_context([]))
        if result.done or result.failed:
            break

    assert result is not None
    assert result.failed is True
    assert result.reason == "no_target_fused"


# ── 6. Missing drone context ───────────────────────────────────────


def test_missing_drone_altitude_fails() -> None:
    action = FixedViewLocalizeAction()
    action.start({
        "detection_source": "scene",
        "class_names": ["bucket_1"],
        "min_confidence": 0.35,
        "settle_updates": 2,
        "capture_updates": 5,
        "max_updates": 30,
        "camera": {"fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0},
        "fusion": {"cluster_radius_m": 0.7, "outlier_radius_m": 0.8, "min_cluster_size": 2, "max_cluster_radius_m": 0.9, "center_weight_power": 1.0, "max_objects": 5},
    })

    det = _make_detection()
    bad_drone = {"local_x": 0.0, "local_y": 32.5, "yaw": 0.0}  # no altitude
    result = None
    for _ in range(20):
        result = action.update(_make_context([det], bad_drone))
        if result.done or result.failed:
            break

    # The action should still complete (drone context errors are caught per-frame)
    # but no valid estimates should be produced, leading to no_target_fused
    assert result is not None
    assert result.failed is True
    assert result.reason == "no_target_fused"


def test_missing_drone_local_x_fails() -> None:
    action = FixedViewLocalizeAction()
    action.start({
        "detection_source": "scene",
        "class_names": ["bucket_1"],
        "min_confidence": 0.35,
        "settle_updates": 2,
        "capture_updates": 5,
        "max_updates": 30,
        "camera": {"fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0},
        "fusion": {"cluster_radius_m": 0.7, "outlier_radius_m": 0.8, "min_cluster_size": 2, "max_cluster_radius_m": 0.9, "center_weight_power": 1.0, "max_objects": 5},
    })

    det = _make_detection()
    bad_drone = {"local_y": 32.5, "yaw": 0.0, "relative_altitude": 5.0}  # no local_x
    result = None
    for _ in range(20):
        result = action.update(_make_context([det], bad_drone))
        if result.done or result.failed:
            break

    assert result is not None
    assert result.failed is True
    assert result.reason == "no_target_fused"


# ── 7. target_slots from select_drop_targets ───────────────────────


def test_select_drop_targets_produces_target_slots() -> None:
    from missions.common.actions.select_drop_targets import SelectDropTargetsAction

    action = SelectDropTargetsAction()
    action.start({
        "objects": [
            {"id": "b1", "class_name": "bucket_1", "local_x": 1.0, "local_y": 30.0, "seen_count": 3, "raw_count": 3, "weight": 2.0},
        ],
        "target_count": 3,
        "allow_fewer": True,
        "score_table": {"bucket_1": 500, "bucket_2": 300, "bucket_3": 100, "bucket": 50},
        "min_seen_count": 2,
        "min_raw_count": 0,
        "min_weight": 0.0,
        "deduplicate_radius_m": 0.8,
    })

    result = action.update({})
    assert result.done is True
    slots = result.detail["target_slots"]
    assert len(slots) == 3
    assert slots[0]["valid"] is True
    assert slots[0]["class_name"] == "bucket_1"
    assert slots[1]["valid"] is False
    assert slots[1]["status"] == "missing"
    assert slots[2]["valid"] is False
    assert slots[2]["status"] == "missing"


def test_select_drop_targets_all_slots_filled() -> None:
    from missions.common.actions.select_drop_targets import SelectDropTargetsAction

    action = SelectDropTargetsAction()
    action.start({
        "objects": [
            {"id": "b1", "class_name": "bucket_1", "local_x": 1.0, "local_y": 30.0, "seen_count": 3, "raw_count": 3, "weight": 2.0},
            {"id": "b2", "class_name": "bucket_2", "local_x": -1.0, "local_y": 31.0, "seen_count": 3, "raw_count": 3, "weight": 1.5},
        ],
        "target_count": 2,
        "allow_fewer": False,
        "score_table": {"bucket_1": 500, "bucket_2": 300},
        "min_seen_count": 2,
        "min_raw_count": 0,
        "min_weight": 0.0,
        "deduplicate_radius_m": 0.8,
    })

    result = action.update({})
    assert result.done is True
    slots = result.detail["target_slots"]
    assert len(slots) == 2
    assert all(s["valid"] for s in slots)
