from __future__ import annotations

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


def test_hold_yaw_default_outputs_local_position_without_yaw() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    result = action.update({})

    assert result.reason == "waiting_for_position"
    assert result.actions[0] == {
        "action_type": "local_position",
        "params": {"x": 1.0, "y": 2.0, "z": -5.0, "frame": 1},
        "key": "goto_waypoint_1.00_2.00_5.00",
        "once": False,
        "priority": 4,
    }
    assert "yaw" not in result.actions[0]["params"]


def test_fixed_yaw_outputs_yaw_param() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "yaw_mode": "fixed", "yaw_rad": 1.57})

    result = action.update({})

    assert result.actions[0]["params"]["yaw"] == pytest.approx(1.57)


def test_missing_position_waits_and_keeps_outputting_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    result = action.update({})

    assert result.reason == "waiting_for_position"
    assert result.done is False
    assert result.failed is False
    assert result.actions[0]["action_type"] == "local_position"
    assert result.detail["current"] is None


def test_not_reached_outputs_action_and_error_detail() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    result = action.update({"local_position": {"x": 10, "y": 2, "z": -4}})

    assert result.reason == "goto_active"
    assert result.done is False
    assert result.actions[0]["action_type"] == "local_position"
    assert result.detail["distance_xy_m"] == pytest.approx(9.0)
    assert result.detail["z_error_m"] == pytest.approx(1.0)


def test_reached_completes_without_action() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    result = action.update({"local_position": {"x": 1.1, "y": 2.1, "z": -5.1}})

    assert result.done is True
    assert result.reason == "waypoint_reached"
    assert result.actions == []
    assert result.detail["reached_updates"] == 1


def test_min_hold_updates_requires_consecutive_reached_updates() -> None:
    action = GotoWaypointAction()
    action.start({"x": 1, "y": 2, "altitude_m": 5, "min_hold_updates": 2})

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
    action.start({"x": 1, "y": 2, "altitude_m": 5})

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
    action.start({"x": 1, "y": 2, "altitude_m": 5})

    result = action.update({})

    assert isinstance(result.actions[0], dict)
