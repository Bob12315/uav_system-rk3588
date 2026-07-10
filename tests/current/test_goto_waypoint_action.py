from __future__ import annotations

import math

import pytest

from missions.common.actions.goto_waypoint import GotoWaypointAction


def test_start_requires_target_coordinates_and_altitude() -> None:
    action = GotoWaypointAction()

    with pytest.raises(ValueError):
        action.start({"y": 2, "altitude_m": 5})
    with pytest.raises(ValueError):
        action.start({"x": 1, "altitude_m": 5})
    with pytest.raises(ValueError):
        action.start({"x": 1, "y": 2})
    with pytest.raises(ValueError):
        action.start({"x": "bad", "y": 2, "altitude_m": 5})


def test_start_rejects_invalid_altitude_and_yaw_options() -> None:
    action = GotoWaypointAction()

    with pytest.raises(ValueError):
        action.start({"x": 1, "y": 2, "altitude_m": 0})
    with pytest.raises(ValueError):
        action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "spin"})
    with pytest.raises(ValueError):
        action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "fixed"})
    with pytest.raises(ValueError):
        action.start({"x": 1, "y": 2, "altitude_m": 5, "target_frame": "mars"})


def test_default_arm_heading_yaw_outputs_context_yaw() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    result = action.update({"arm_heading_yaw_rad": 0.75})

    assert result.reason == "waiting_for_position"
    emitted = result.actions[0]
    assert emitted["params"] == {
        "x": 1.0, "y": 2.0, "z": -5.0, "frame": 1, "yaw": pytest.approx(0.75)
    }
    assert emitted["input_frame"] == "local_ned"
    assert emitted["input_target"] == {"x": 1.0, "y": 2.0, "z": -5.0}
    assert emitted["local_target"] == {"x": 1.0, "y": 2.0, "z": -5.0}
    assert emitted["key"] == "goto_waypoint_1.00_2.00_5.00"


def test_default_arm_heading_yaw_missing_context_fails_without_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    result = action.update({})

    assert result.failed is True
    assert result.reason == "missing_arm_heading_yaw"
    assert result.actions == []


def test_fixed_yaw_outputs_yaw_param() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "fixed", "yaw_rad": 1.57})

    result = action.update({})

    assert result.actions[0]["params"]["yaw"] == pytest.approx(1.57)


def test_arm_heading_yaw_outputs_context_arm_heading() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "arm_heading"})

    result = action.update({"arm_heading_yaw_rad": -0.75})

    assert result.reason == "waiting_for_position"
    assert result.actions[0]["params"] == {
        "x": 1.0,
        "y": 2.0,
        "z": -5.0,
        "frame": 1,
        "yaw": pytest.approx(-0.75),
    }
    assert result.detail["arm_heading_yaw_rad"] == pytest.approx(-0.75)


def test_arm_heading_yaw_missing_context_fails_without_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "arm_heading"})

    result = action.update({})

    assert result.failed is True
    assert result.reason == "missing_arm_heading_yaw"
    assert result.actions == []
    assert result.detail["target"]["z"] == pytest.approx(-5.0)
    assert "requires arm_heading_yaw_rad" in result.detail["note"]


def test_field_heading_yaw_outputs_context_field_heading() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "field_heading"})

    result = action.update(
        {
            "field_heading_yaw_rad": 1.25,
            "field_heading_confirmed": True,
            "field_heading_source": "takeoff_auto",
        }
    )

    assert result.reason == "waiting_for_position"
    assert result.actions[0]["action_type"] == "local_position"
    assert result.actions[0]["params"]["yaw"] == pytest.approx(1.25)
    assert result.detail["field_heading_yaw_rad"] == pytest.approx(1.25)
    assert result.detail["field_heading_confirmed"] is True
    assert result.detail["field_heading_source"] == "takeoff_auto"


def test_field_heading_yaw_missing_context_fails_without_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "field_heading"})

    result = action.update({})

    assert result.failed is True
    assert result.reason == "missing_field_heading_yaw"
    assert result.actions == []
    assert "requires field_heading_yaw_rad" in result.detail["note"]


def test_field_waypoint_mode_transforms_to_local_ned_heading_zero() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 3, "waypoint_mode": "field", "yaw_mode": "field_heading"})

    result = action.update(
        {
            "field_heading_yaw_rad": 0.0,
            "field_origin_local_x": 10.0,
            "field_origin_local_y": 20.0,
            "field_origin_local_z": -1.0,
                "field_origin_confirmed": True,
                "field_heading_confirmed": True,
        }
    )

    params = result.actions[0]["params"]
    assert params["x"] == pytest.approx(12.0)
    assert params["y"] == pytest.approx(21.0)
    assert params["z"] == pytest.approx(-3.0)
    assert params["yaw"] == pytest.approx(0.0)


def test_field_waypoint_mode_transforms_to_local_ned_heading_90_deg() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 3, "waypoint_mode": "field", "yaw_mode": "field_heading"})

    result = action.update(
        {
            "field_heading_yaw_rad": math.pi / 2.0,
            "field_origin_local_x": 10.0,
            "field_origin_local_y": 20.0,
            "field_origin_local_z": -1.0,
                "field_origin_confirmed": True,
                "field_heading_confirmed": True,
        }
    )

    params = result.actions[0]["params"]
    assert params["x"] == pytest.approx(9.0)
    assert params["y"] == pytest.approx(22.0)
    assert params["z"] == pytest.approx(-3.0)


@pytest.mark.parametrize(
    ("yaw", "field_x", "field_y", "expected_x", "expected_y"),
    [
        (0.0, 0.0, 1.0, 11.0, 20.0),
        (0.0, 1.0, 0.0, 10.0, 21.0),
        (math.pi / 2.0, 0.0, 1.0, 10.0, 21.0),
        (math.pi / 2.0, 1.0, 0.0, 9.0, 20.0),
    ],
)
def test_field_axes_convert_to_expected_local_ned(
    yaw: float, field_x: float, field_y: float, expected_x: float, expected_y: float,
) -> None:
    action = GotoWaypointAction()
    action.start({
        "x": field_x, "y": field_y, "altitude_m": 3.0,
        "waypoint_mode": "field", "yaw_mode": "field_heading",
    })
    result = action.update({
        "field_heading_yaw_rad": yaw,
        "field_heading_confirmed": True,
        "field_origin_local_x": 10.0,
        "field_origin_local_y": 20.0,
        "field_origin_confirmed": True,
    })

    assert result.failed is False
    assert result.actions[0]["params"]["x"] == pytest.approx(expected_x)
    assert result.actions[0]["params"]["y"] == pytest.approx(expected_y)
    assert result.detail["input_frame"] == "field"
    assert result.detail["local_target"] == pytest.approx({
        "x": expected_x, "y": expected_y, "z": -3.0,
    })
    assert result.detail["note"] == "field -> LOCAL_NED converted"


def test_field_waypoint_global_target_frame_converts_to_gps() -> None:
    action = GotoWaypointAction()
    action.start({
        "x": 0.0,
        "y": 10.0,
        "altitude_m": 5.0,
        "waypoint_mode": "field",
        "target_frame": "global",
        "yaw_mode": "field_heading",
    })

    result = action.update({
        "field_heading_yaw_rad": 0.0,
        "field_heading_confirmed": True,
        "field_origin_confirmed": True,
        "field_origin_lat": 34.0,
        "field_origin_lon": 108.0,
    })

    emitted = result.actions[0]
    assert emitted["action_type"] == "global_goto"
    assert emitted["input_frame"] == "field"
    assert emitted["params"]["lat"] == pytest.approx(34.0000899, rel=1e-5)
    assert emitted["params"]["lon"] == pytest.approx(108.0)
    assert emitted["params"]["alt"] == pytest.approx(5.0)
    assert emitted["params"]["frame"] != 1
    assert result.detail["global_target"] == pytest.approx(emitted["global_target"])
    assert result.detail["note"] == "field -> GPS converted"


def test_field_global_waypoint_uses_gps_origin_without_local_origin() -> None:
    action = GotoWaypointAction()
    action.start({
        "x": 0.0, "y": 0.0, "altitude_m": 5.0,
        "waypoint_mode": "field", "target_frame": "global", "yaw_mode": "hold",
    })
    result = action.update({
        "field_heading_yaw_rad": 0.25,
        "field_heading_confirmed": True,
        "field_origin_gps_confirmed": True,
        "field_origin_confirmed": False,
        "field_origin_lat": 34.0,
        "field_origin_lon": 108.0,
    })

    assert result.failed is False
    assert result.actions[0]["action_type"] == "global_goto"
    assert result.actions[0]["params"]["lat"] == pytest.approx(34.0)
    assert result.actions[0]["params"]["lon"] == pytest.approx(108.0)


def test_global_target_uses_gps_position_for_completion() -> None:
    action = GotoWaypointAction()
    action.start({
        "x": 34.0,
        "y": 108.0,
        "altitude_m": 5.0,
        "target_frame": "global",
        "yaw_mode": "hold",
    })

    result = action.update({
        "drone": {
            "global_position_valid": True,
            "lat": 34.0,
            "lon": 108.0,
            "relative_altitude": 5.0,
        }
    })

    assert result.done is True
    assert result.reason == "waypoint_reached"
    assert result.actions == []


def _global_velocity_context(*, vx=0.0, vy=0.0, vz=0.0, velocity_valid=True):
    return {
        "drone": {
            "global_position_valid": True,
            "lat": 34.0,
            "lon": 108.0,
            "relative_altitude": 5.0,
            "velocity_valid": velocity_valid,
            "vx": vx,
            "vy": vy,
            "vz": vz,
        }
    }


def test_global_velocity_gate_accepts_consecutive_low_speed_updates() -> None:
    action = GotoWaypointAction()
    action.start({
        "lat": 34.0, "lon": 108.0, "altitude_m": 5.0,
        "target_frame": "global", "yaw_mode": "hold",
        "require_velocity_valid": True,
        "max_horizontal_speed_mps": 0.15,
        "max_vertical_speed_mps": 0.10,
        "min_hold_updates": 2,
    })

    first = action.update(_global_velocity_context(vx=0.1, vy=0.05, vz=0.05))
    second = action.update(_global_velocity_context(vx=0.1, vy=0.05, vz=0.05))

    assert first.done is False
    assert second.done is True
    assert second.detail["velocity_required"] is True
    assert second.detail["velocity_valid"] is True
    assert second.detail["velocity_gate_passed"] is True
    assert second.detail["horizontal_speed_mps"] == pytest.approx(math.hypot(0.1, 0.05))
    assert second.detail["vertical_speed_mps"] == pytest.approx(0.05)


@pytest.mark.parametrize(
    "drone_update",
    [
        {"vx": 0.2, "vy": 0.0, "vz": 0.0},
        {"vx": 0.0, "vy": 0.0, "vz": 0.2},
        {"velocity_valid": False},
        {"vx": float("nan")},
    ],
)
def test_global_velocity_gate_rejects_high_or_invalid_velocity(drone_update) -> None:
    action = GotoWaypointAction()
    action.start({
        "lat": 34.0, "lon": 108.0, "altitude_m": 5.0,
        "target_frame": "global", "yaw_mode": "hold",
        "require_velocity_valid": True,
        "max_horizontal_speed_mps": 0.15,
        "max_vertical_speed_mps": 0.10,
    })
    context = _global_velocity_context()
    context["drone"].update(drone_update)

    result = action.update(context)

    assert result.done is False
    assert result.reason == "goto_active"
    assert result.detail["reached_updates"] == 0
    assert result.detail["velocity_gate_passed"] is False
    assert result.actions[0]["action_type"] == "global_goto"


def test_global_velocity_gate_resets_consecutive_hold_after_speed_spike() -> None:
    action = GotoWaypointAction()
    action.start({
        "lat": 34.0, "lon": 108.0, "altitude_m": 5.0,
        "target_frame": "global", "yaw_mode": "hold",
        "require_velocity_valid": True, "min_hold_updates": 2,
    })
    first = action.update(_global_velocity_context())
    spike = action.update(_global_velocity_context(vx=0.3))
    after_spike = action.update(_global_velocity_context())
    done = action.update(_global_velocity_context())
    assert first.detail["reached_updates"] == 1
    assert spike.detail["reached_updates"] == 0
    assert after_spike.done is False and after_spike.detail["reached_updates"] == 1
    assert done.done is True


@pytest.mark.parametrize("name,value", [("max_horizontal_speed_mps", -0.1), ("max_vertical_speed_mps", float("nan"))])
def test_global_velocity_gate_rejects_invalid_thresholds(name, value) -> None:
    with pytest.raises(ValueError):
        GotoWaypointAction().start({
            "lat": 34.0, "lon": 108.0, "altitude_m": 5.0,
            "target_frame": "global", "yaw_mode": "hold", name: value,
        })


def test_field_waypoint_without_confirmation_never_emits_action() -> None:
    action = GotoWaypointAction()
    action.start({
        "x": 0.0, "y": 1.0, "altitude_m": 3.0,
        "waypoint_mode": "field", "yaw_mode": "field_heading",
    })
    result = action.update({
        "field_heading_yaw_rad": 0.0,
        "field_origin_local_x": 10.0,
        "field_origin_local_y": 20.0,
    })

    assert result.failed is True
    assert result.actions == []
    assert "confirm field heading/origin" in result.detail["note"]


def test_field_waypoint_mode_missing_origin_fails() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 3, "waypoint_mode": "field", "yaw_mode": "field_heading"})

    result = action.update({"field_heading_yaw_rad": 0.0})

    assert result.failed is True
    assert result.reason == "missing_field_origin"
    assert result.actions == []


def test_missing_position_waits_and_keeps_outputting_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "hold"})

    result = action.update({})

    assert result.reason == "waiting_for_position"
    assert result.done is False
    assert result.failed is False
    assert result.actions[0]["action_type"] == "local_position"
    assert result.detail["current"] is None


def test_not_reached_outputs_action_and_error_detail() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "hold"})

    result = action.update({"local_position": {"x": 10, "y": 2, "z": -4}})

    assert result.reason == "goto_active"
    assert result.done is False
    assert result.actions[0]["action_type"] == "local_position"
    assert result.detail["distance_xy_m"] == pytest.approx(9.0)
    assert result.detail["z_error_m"] == pytest.approx(1.0)


def test_reached_completes_without_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "hold"})

    result = action.update({"local_position": {"x": 1.1, "y": 2.1, "z": -5.1}})

    assert result.done is True
    assert result.reason == "waypoint_reached"
    assert result.actions == []
    assert result.detail["reached_updates"] == 1


def test_min_hold_updates_requires_consecutive_reached_updates() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "min_hold_updates": 2, "yaw_mode": "hold"})

    first = action.update({"local_position": {"x": 1.0, "y": 2.0, "z": -5.0}})
    second = action.update({"local_position": {"x": 1.0, "y": 2.0, "z": -5.0}})

    assert first.done is False
    assert first.reason == "goto_active"
    assert first.detail["reached_updates"] == 1
    assert second.done is True
    assert second.reason == "waypoint_reached"
    assert second.detail["reached_updates"] == 2


def test_supports_drone_local_position_context() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "hold"})

    result = action.update(
        {"drone": {"local_position": {"x": 1.0, "y": 2.0, "z": -5.0}}}
    )

    assert result.done is True
    assert result.reason == "waypoint_reached"


def test_stop_makes_later_update_done_without_actions() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    action.stop()
    result = action.update({"local_position": {"x": 10, "y": 10, "z": 0}})

    assert result.done is True
    assert result.reason == "stopped"
    assert result.actions == []


def test_reset_returns_to_not_started_state() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    action.reset()
    result = action.update({"local_position": {"x": 1, "y": 2, "z": -5}})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_action_output_is_plain_dict_not_mission_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "hold"})

    result = action.update({})

    assert isinstance(result.actions[0], dict)


# ---------------------------------------------------------------------------
# Phase 4B parity: adapter matches direct field_to_local_ned() call
# ---------------------------------------------------------------------------

def test_local_target_matches_direct_field_to_local_ned() -> None:
    """The _local_target() adapter must produce the same result as calling
    field_to_local_ned() directly with an equivalent FieldReference."""
    from app.coordinate_transform import field_to_local_ned as direct_convert
    from app.field_reference import FieldReference

    action = GotoWaypointAction()
    action.start({
        "x": 3.0, "y": 4.0, "altitude_m": 5.0,
        "waypoint_mode": "field", "yaw_mode": "field_heading",
    })

    context = {
        "field_heading_yaw_rad": 0.5,
        "field_heading_confirmed": True,
        "field_origin_local_x": 10.0,
        "field_origin_local_y": 20.0,
        "field_origin_confirmed": True,
    }

    # via adapter
    target = action._local_target(context)
    assert target is not None

    # via direct call
    ref = FieldReference()
    ref.is_confirmed = True
    ref.origin_local_n_m = 10.0
    ref.origin_local_e_m = 20.0
    ref.field_heading_yaw_rad = 0.5
    expected = direct_convert(3.0, 4.0, 5.0, reference=ref)

    assert target["x"] == pytest.approx(expected.north_m)
    assert target["y"] == pytest.approx(expected.east_m)
    assert target["z"] == pytest.approx(expected.z_down_m)


@pytest.mark.parametrize("yaw_rad", [0.0, math.pi / 2.0, math.pi])
def test_local_target_matches_direct_at_cardinal_yaws(yaw_rad: float) -> None:
    """Adapter parity at cardinal yaw angles."""
    from app.coordinate_transform import field_to_local_ned as direct_convert
    from app.field_reference import FieldReference

    action = GotoWaypointAction()
    action.start({
        "x": 2.0, "y": 3.0, "altitude_m": 2.0,
        "waypoint_mode": "field", "yaw_mode": "field_heading",
    })

    context = {
        "field_heading_yaw_rad": yaw_rad,
        "field_heading_confirmed": True,
        "field_origin_local_x": 0.0,
        "field_origin_local_y": 0.0,
        "field_origin_confirmed": True,
    }

    target = action._local_target(context)
    assert target is not None

    ref = FieldReference()
    ref.is_confirmed = True
    ref.origin_local_n_m = 0.0
    ref.origin_local_e_m = 0.0
    ref.field_heading_yaw_rad = yaw_rad
    expected = direct_convert(2.0, 3.0, 2.0, reference=ref)

    assert target["x"] == pytest.approx(expected.north_m)
    assert target["y"] == pytest.approx(expected.east_m)
    assert target["z"] == pytest.approx(expected.z_down_m)


def test_skip_if_invalid_target_true_skips_on_target_valid_false():
    action = GotoWaypointAction()
    action.start({
        "x": 1.0, "y": 2.0, "altitude_m": 2.5,
        "skip_if_invalid_target": True,
        "target": {"valid": False, "local_x": 1.0, "local_y": 2.0},
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"
    assert result.actions == []


def test_skip_if_invalid_target_true_skips_on_target_valid_param_false():
    action = GotoWaypointAction()
    action.start({
        "x": 1.0, "y": 2.0, "altitude_m": 2.5,
        "skip_if_invalid_target": True,
        "target_valid": False,
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"
    assert result.actions == []


def test_skip_if_invalid_target_true_skips_on_x_none():
    action = GotoWaypointAction()
    action.start({
        "x": None, "y": 2.0, "altitude_m": 2.5,
        "skip_if_invalid_target": True,
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"


def test_skip_if_invalid_target_true_skips_on_x_nan():
    action = GotoWaypointAction()
    action.start({
        "x": float("nan"), "y": 2.0, "altitude_m": 2.5,
        "skip_if_invalid_target": True,
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"


def test_skip_invalid_altitude_none():
    action = GotoWaypointAction()
    action.start({
        "x": 1.0, "y": 2.0, "altitude_m": None,
        "skip_if_invalid_target": True,
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"
    assert result.actions == []


def test_skip_invalid_altitude_nan():
    action = GotoWaypointAction()
    action.start({
        "x": 1.0, "y": 2.0, "altitude_m": float("nan"),
        "skip_if_invalid_target": True,
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"
    assert result.actions == []


def test_skip_invalid_altitude_inf():
    action = GotoWaypointAction()
    action.start({
        "x": 1.0, "y": 2.0, "altitude_m": float("inf"),
        "skip_if_invalid_target": True,
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"
    assert result.actions == []


def test_skip_invalid_altitude_neginf():
    action = GotoWaypointAction()
    action.start({
        "x": 1.0, "y": 2.0, "altitude_m": float("-inf"),
        "skip_if_invalid_target": True,
    })
    result = action.update({})
    assert result.done is True
    assert result.reason == "skipped_missing_target"
    assert result.actions == []
