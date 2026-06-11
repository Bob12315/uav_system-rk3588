from __future__ import annotations

import json

import pytest

from missions.common.actions.multi_view_localize import MultiViewLocalizeAction
from missions.common.actions.result import ActionResult


def _params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "waypoint_mode": "absolute",
        "waypoints": [
            {"x": 1.0, "y": 2.0, "altitude_m": 3.0},
            {"x": 4.0, "y": 5.0, "altitude_m": 3.0},
        ],
        "capture_updates_per_waypoint": 1,
        "settle_updates_per_waypoint": 1,
        "max_updates_per_waypoint": 10,
        "yaw_mode": "hold",
    }
    params.update(overrides)
    return params


def _at_waypoint(x: float = 1.0, y: float = 2.0, altitude_m: float = 3.0) -> dict[str, object]:
    return {
        "local_position": {"x": x, "y": y, "z": -altitude_m},
        "drone": {
            "local_x": x,
            "local_y": y,
            "local_z": -altitude_m,
            "relative_altitude": altitude_m,
            "yaw": 0.0,
        },
        "arm_heading_yaw_rad": 0.0,
    }


def _scene_with_detection(
    track_id: int = 1,
    class_name: str = "bucket",
    ex: float = 0.0,
    ey: float = 0.0,
) -> dict[str, object]:
    return {
        "image_width": 640,
        "image_height": 480,
        "detections": [
            {
                "track_id": track_id,
                "class_name": class_name,
                "confidence": 0.9,
                "ex": ex,
                "ey": ey,
            }
        ],
    }


# ── start / validation ──────────────────────────────────────────────


def test_start_with_absolute_waypoints_parses_them() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[
            {"x": 10.0, "y": 20.0, "altitude_m": 5.0},
            {"x": 30.0, "y": 40.0, "altitude_m": 5.0},
        ]
    ))
    assert action.waypoints is not None
    assert len(action.waypoints) == 2
    assert action.waypoint_mode == "absolute"
    assert action.phase == "goto"


def test_start_rejects_invalid_waypoint_mode() -> None:
    action = MultiViewLocalizeAction()
    with pytest.raises(ValueError):
        action.start(_params(waypoint_mode="bad"))


def test_start_absolute_requires_non_empty_waypoints() -> None:
    action = MultiViewLocalizeAction()
    with pytest.raises(ValueError):
        action.start(_params(waypoints=[]))
    with pytest.raises(ValueError):
        action.start(_params(waypoints=None))


def test_update_before_start_fails() -> None:
    result = MultiViewLocalizeAction().update({})
    assert result.failed is True
    assert result.reason == "action_not_started"


# ── relative_to_start — waypoint generation ─────────────────────────


def test_relative_to_start_generates_four_waypoints_on_first_update() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoint_mode="relative_to_start",
        waypoints=None,
        radius_m=2.0,
        altitude_m=5.0,
    ))
    assert action.phase == "init"

    # first update provides the current position
    action.update({
        "drone": {"local_x": 10.0, "local_y": 20.0, "local_z": -5.0, "yaw": 0.0},
        "local_position": {"x": 10.0, "y": 20.0, "z": -5.0},
    })

    assert action.waypoints is not None
    assert len(action.waypoints) == 4
    # four cardinal points: E, W, N, S at radius 2.0
    xs = [wp["x"] for wp in action.waypoints]
    ys = [wp["y"] for wp in action.waypoints]
    assert 12.0 in xs  # center_x + 2
    assert 8.0 in xs   # center_x - 2
    assert 22.0 in ys
    assert 18.0 in ys
    for wp in action.waypoints:
        assert wp["altitude_m"] == 5.0


# ── goto phase ──────────────────────────────────────────────────────


def test_goto_phase_returns_local_position_action() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params())
    assert action.phase == "goto"

    result = action.update({"local_position": {"x": 0.0, "y": 0.0, "z": -3.0}})
    assert result.reason == "multi_view_goto"
    assert result.done is False
    assert len(result.actions) >= 1
    assert result.actions[0]["action_type"] == "local_position"


def test_goto_completes_and_transitions_to_settle() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        capture_updates_per_waypoint=1,
        settle_updates_per_waypoint=1,
    ))
    # reach the waypoint
    result = action.update(_at_waypoint(1.0, 2.0, 3.0))
    assert result.reason == "multi_view_settle"
    assert action.phase == "settle"


# ── capture phase ───────────────────────────────────────────────────


def test_capture_scene_detections_adds_estimates() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        capture_updates_per_waypoint=1,
        settle_updates_per_waypoint=1,
        class_names={"bucket"},
    ))

    # goto -> settle -> capture
    ctx = _at_waypoint(1.0, 2.0, 3.0)
    action.update(ctx)  # goto done -> settle
    action.update(ctx)  # settle done -> capture

    # now capture
    ctx["scene"] = _scene_with_detection(track_id=1, ex=0.0, ey=0.0)
    result = action.update(ctx)

    # single waypoint, so capture 1/1 -> done
    assert action.phase == "done"
    assert len(action.raw_estimates) >= 1


# ── done and fusion ─────────────────────────────────────────────────


def test_single_waypoint_with_detection_completes_with_localized_objects() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        capture_updates_per_waypoint=1,
        settle_updates_per_waypoint=1,
        class_names={"bucket"},
    ))

    ctx = _at_waypoint(1.0, 2.0, 3.0)
    action.update(ctx)  # goto done
    action.update(ctx)  # settle done
    ctx["scene"] = _scene_with_detection(track_id=1, ex=0.0, ey=0.0)
    result = action.update(ctx)

    assert result.done is True
    assert result.reason == "multi_view_localized"
    objects = result.detail.get("localized_objects")
    assert isinstance(objects, list)
    assert len(objects) >= 1
    assert "best_target" not in result.detail
    # each object must have required fields
    obj = objects[0]
    assert "x" in obj
    assert "y" in obj
    assert "local_x" in obj
    assert "local_y" in obj
    assert "target_id" in obj
    assert "seen_count" in obj


def test_no_detection_results_in_no_target_fused() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        capture_updates_per_waypoint=1,
        settle_updates_per_waypoint=1,
        class_names={"bucket"},
    ))

    ctx = _at_waypoint(1.0, 2.0, 3.0)
    action.update(ctx)  # goto done
    action.update(ctx)  # settle done
    # no scene detections
    result = action.update(ctx)

    assert result.failed is True
    assert result.reason == "no_target_fused"


# ── yaw_mode arm_heading ────────────────────────────────────────────


def test_yaw_mode_arm_heading_passes_yaw_to_goto() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        yaw_mode="arm_heading",
    ))

    result = action.update({
        "local_position": {"x": 10.0, "y": 10.0, "z": -3.0},
        "arm_heading_yaw_rad": 1.23,
    })

    assert result.reason == "multi_view_goto"
    assert result.actions[0]["params"]["yaw"] == pytest.approx(1.23)


# ── detail format ───────────────────────────────────────────────────


def test_done_detail_includes_required_fields() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        capture_updates_per_waypoint=1,
        settle_updates_per_waypoint=1,
        class_names={"bucket"},
    ))

    ctx = _at_waypoint(1.0, 2.0, 3.0)
    action.update(ctx)
    action.update(ctx)
    ctx["scene"] = _scene_with_detection(track_id=1, ex=0.0, ey=0.0)
    result = action.update(ctx)

    assert result.done is True
    detail = result.detail
    assert "run_id" in detail
    assert isinstance(detail["run_id"], str)
    assert len(detail["run_id"]) > 0
    assert detail.get("coordinate_frame") == "LOCAL_NED"
    assert isinstance(detail.get("localized_objects"), list)
    assert "object_count" in detail
    assert "raw_estimates_count" in detail
    assert "captures_count" in detail
    assert isinstance(detail.get("captures"), list)
    assert isinstance(detail.get("waypoints"), list)


def test_output_is_json_serializable() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        capture_updates_per_waypoint=1,
        settle_updates_per_waypoint=1,
        class_names={"bucket"},
    ))

    ctx = _at_waypoint(1.0, 2.0, 3.0)
    action.update(ctx)
    action.update(ctx)
    ctx["scene"] = _scene_with_detection(track_id=1, ex=0.0, ey=0.0)
    result = action.update(ctx)

    assert result.done is True
    json.dumps(result.detail)  # must not raise


# ── stop / reset ────────────────────────────────────────────────────


def test_stop_marks_done() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params())
    action.stop()
    result = action.update({})
    assert result.done is True
    assert result.reason == "stopped"
    assert result.actions == []


def test_reset_returns_to_not_started_state() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params())
    action.reset()
    result = action.update({})
    assert result.failed is True
    assert result.reason == "action_not_started"


def test_waypoint_timeout_stops_action() -> None:
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[{"x": 1.0, "y": 2.0, "altitude_m": 3.0}],
        max_updates_per_waypoint=2,
    ))

    action.update({"local_position": {"x": 10.0, "y": 10.0, "z": -3.0}})  # update 1
    action.update({"local_position": {"x": 10.0, "y": 10.0, "z": -3.0}})  # update 2
    result = action.update({"local_position": {"x": 10.0, "y": 10.0, "z": -3.0}})  # timeout

    assert result.failed is True
    assert result.reason == "waypoint_timeout"


# ── four-waypoint full cycle ────────────────────────────────────────


def test_four_points_complete_with_done() -> None:
    """Simulate a full four-waypoint capture cycle with detections at each point."""
    action = MultiViewLocalizeAction()
    action.start(_params(
        waypoints=[
            {"x": 1.0, "y": 2.0, "altitude_m": 3.0},
            {"x": 4.0, "y": 5.0, "altitude_m": 3.0},
        ],
        capture_updates_per_waypoint=1,
        settle_updates_per_waypoint=1,
        class_names={"bucket"},
    ))

    # point 0: goto -> settle -> capture
    ctx = _at_waypoint(1.0, 2.0, 3.0)
    action.update(ctx)  # goto done -> settle
    action.update(ctx)  # settle done -> capture
    ctx["scene"] = _scene_with_detection(track_id=1, ex=0.0, ey=0.0)
    result = action.update(ctx)  # capture done -> next waypoint
    assert result.reason == "multi_view_next_waypoint"

    # point 1: goto -> settle -> capture
    ctx2 = _at_waypoint(4.0, 5.0, 3.0)
    action.update(ctx2)  # goto done -> settle
    action.update(ctx2)  # settle done -> capture
    ctx2["scene"] = _scene_with_detection(track_id=2, ex=0.1, ey=0.1)
    result2 = action.update(ctx2)

    assert result2.done is True
    assert result2.reason == "multi_view_localized"
    assert len(result2.detail.get("localized_objects", [])) >= 1
    assert "best_target" not in result2.detail
