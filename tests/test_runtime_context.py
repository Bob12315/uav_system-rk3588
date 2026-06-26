from __future__ import annotations

import math

import pytest

from app.runtime_context import RuntimeContextBuilder


def test_build_action_context_includes_new_fields() -> None:
    builder = RuntimeContextBuilder()
    snapshot: dict[str, object] = {
        "drone": {"armed": False, "attitude_valid": True, "yaw": 1.0},
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
    assert context["pre_arm_yaw_rad"] == pytest.approx(1.0)
    assert context["field_heading_confirmed"] is False


def test_build_action_context_new_fields_default_to_empty_dict() -> None:
    builder = RuntimeContextBuilder()
    context = builder.build_action_context({})

    assert context["gimbal"] == {}
    assert context["link"] == {}
    assert context["health"] == {}
    assert context["command"] == {}
    assert context["mission_detail"] == {}
    assert context["field_heading_confirmed"] is False


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


def test_disarmed_valid_attitude_records_pre_arm_yaw() -> None:
    builder = RuntimeContextBuilder()

    context = builder.build_action_context(
        {"drone": {"armed": False, "attitude_valid": True, "yaw": math.pi + 0.25}}
    )

    assert context["pre_arm_yaw_rad"] == pytest.approx(-math.pi + 0.25)
    assert builder.pre_arm_yaw_rad == pytest.approx(-math.pi + 0.25)


def test_confirm_field_heading_records_normalized_yaw() -> None:
    builder = RuntimeContextBuilder()

    ok = builder.confirm_field_heading(
        yaw_rad=math.pi + 0.1,
        drone={"local_position_valid": True, "local_x": 10.0, "local_y": 20.0, "local_z": -1.0},
        source="test",
    )
    context = builder.build_action_context({"drone": {}})

    assert ok is True
    assert builder.field_heading_yaw_rad == pytest.approx(-math.pi + 0.1)
    assert context["field_heading_yaw_rad"] == pytest.approx(-math.pi + 0.1)
    assert context["field_heading_confirmed"] is True
    assert context["field_heading_source"] == "test"
    assert context["field_origin_confirmed"] is True
    assert context["field_origin_local_x"] == pytest.approx(10.0)
    assert context["field_origin_local_y"] == pytest.approx(20.0)
    assert context["field_origin_local_z"] == pytest.approx(-1.0)


def test_confirm_field_heading_rejects_invalid_yaw() -> None:
    builder = RuntimeContextBuilder()

    assert builder.confirm_field_heading(yaw_rad=float("nan")) is False
    assert builder.field_heading_yaw_rad is None


def test_confirm_field_heading_rejects_invalid_local_position() -> None:
    builder = RuntimeContextBuilder()

    assert builder.confirm_field_heading(yaw_rad=0.5, drone={"local_position_valid": False}) is False
    assert builder.field_heading_yaw_rad is None
    assert builder.field_origin_confirmed is False


def test_arm_heading_prefers_pre_arm_yaw_on_armed_transition() -> None:
    builder = RuntimeContextBuilder()

    builder.build_action_context({"drone": {"armed": False, "attitude_valid": True, "yaw": 0.4}})
    context = builder.build_action_context({"drone": {"armed": True, "attitude_valid": True, "yaw": 1.2}})

    assert context["arm_heading_yaw_rad"] == pytest.approx(0.4)
    assert "arm_heading_fallback" not in context
