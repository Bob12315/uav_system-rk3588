from __future__ import annotations

from app.runtime_context import RuntimeContextBuilder


def test_build_action_context_includes_new_fields() -> None:
    builder = RuntimeContextBuilder()
    snapshot: dict[str, object] = {
        "drone": {"armed": False, "yaw": 1.0},
        "gimbal": {"pitch": 0.1, "yaw": 0.2},
        "link": {"connected": True},
        "health": {"hold_reason": "ok"},
        "command": {"vx_cmd": 0.5},
        "mission_detail": {"name": "test"},
    }
    context = builder.build_action_context(snapshot)

    # new pass-through fields
    assert context["gimbal"] == {"pitch": 0.1, "yaw": 0.2}
    assert context["link"] == {"connected": True}
    assert context["health"] == {"hold_reason": "ok"}
    assert context["command"] == {"vx_cmd": 0.5}
    assert context["mission_detail"] == {"name": "test"}


def test_build_action_context_new_fields_default_to_empty_dict() -> None:
    builder = RuntimeContextBuilder()
    context = builder.build_action_context({})

    assert context["gimbal"] == {}
    assert context["link"] == {}
    assert context["health"] == {}
    assert context["command"] == {}
    assert context["mission_detail"] == {}


def test_build_action_context_retains_existing_fields() -> None:
    builder = RuntimeContextBuilder()
    snapshot: dict[str, object] = {
        "drone": {
            "armed": False,
            "yaw": 1.5,
            "local_x": 1.0,
            "local_y": 2.0,
            "local_z": -3.0,
            "relative_altitude": 5.0,
            "control_allowed": True,
        },
        "perception": {
            "target_valid": True,
            "tracking_state": "locked",
            "track_id": 7,
            "ex": 0.01,
            "ey": -0.02,
        },
        "scene": {"detections": []},
    }
    context = builder.build_action_context(snapshot)

    # existing field checks
    assert context["local_position"] == {"x": 1.0, "y": 2.0, "z": -3.0}
    assert context["target_valid"] is True
    assert context["tracking_state"] == "locked"
    assert context["track_id"] == 7
    assert context["ex_cam"] == 0.01
    assert context["ey_cam"] == -0.02
    assert context["target_locked"] is True
    assert context["control_allowed"] is True
    assert context["relative_altitude"] == 5.0
    assert "timestamp" in context
    assert "drone" in context
    assert "scene" in context
