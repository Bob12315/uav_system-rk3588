from __future__ import annotations

import pytest

from missions.common.actions.takeoff import TakeoffAction


def test_takeoff_start_uses_default_params() -> None:
    action = TakeoffAction()

    action.start({})

    assert action.altitude_m == 3.0
    assert action.mode == "GUIDED"
    assert action.phase == "confirm_field_heading"
    assert action.auto_confirm_field_heading == "if_missing"
    assert action.hold_yaw_during_takeoff is True
    assert action.takeoff_yaw_mode == "field_heading"


def test_takeoff_update_before_start_fails() -> None:
    action = TakeoffAction()

    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_takeoff_set_mode_phase_outputs_set_mode_action() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0, "auto_confirm_field_heading": False})

    result = action.update({})

    assert result.reason == "set_mode_sent"
    assert result.actions[0]["action_type"] == "set_mode"
    assert result.actions[0]["params"]["mode"] == "GUIDED"
    assert result.actions[0]["once"] is True


def test_takeoff_arm_phase_outputs_arm_action() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0, "auto_confirm_field_heading": False})
    action.update({})

    result = action.update({})

    assert result.reason == "arm_sent"
    assert result.actions[0]["action_type"] == "arm"


def test_takeoff_phase_outputs_takeoff_action() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0, "auto_confirm_field_heading": False})
    action.update({})
    action.update({})

    result = action.update({})

    assert result.reason == "takeoff_sent"
    assert result.actions[0]["action_type"] == "takeoff"
    assert result.actions[0]["params"]["altitude_m"] == 3.0


def test_takeoff_wait_altitude_until_target_reached() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0, "auto_confirm_field_heading": False})
    action.update({})
    action.update({})
    action.update({})

    waiting = action.update({"relative_altitude": 1.0})
    reached = action.update({"relative_altitude": 2.8})

    assert waiting.done is False
    assert waiting.reason == "waiting_for_takeoff_altitude"
    assert reached.done is True
    assert reached.reason == "takeoff_altitude_reached"


def test_takeoff_reads_altitude_from_local_position_z() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0, "auto_confirm_field_heading": False})
    action.update({})
    action.update({})
    action.update({})

    result = action.update({"local_position": {"x": 0, "y": 0, "z": -2.9}})

    assert result.done is True
    assert result.reason == "takeoff_altitude_reached"
    assert result.detail["current_altitude_m"] == 2.9
    assert result.detail["altitude_source"] == "local_position.z"


def test_takeoff_skips_arm_when_require_armed_false() -> None:
    action = TakeoffAction()
    action.start({"require_armed": False, "auto_confirm_field_heading": False})

    set_mode = action.update({})
    takeoff = action.update({})

    assert set_mode.reason == "set_mode_sent"
    assert takeoff.reason == "takeoff_sent"
    assert takeoff.actions[0]["action_type"] == "takeoff"
    assert action.arm_sent is False


def test_takeoff_waits_for_altitude_data_without_immediate_failure() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0, "auto_confirm_field_heading": False})
    action.update({})
    action.update({})
    action.update({})

    result = action.update({})

    assert result.failed is False
    assert result.done is False
    assert result.reason == "waiting_for_altitude"


def test_takeoff_times_out_after_max_updates() -> None:
    action = TakeoffAction()
    action.start({"max_updates": 3, "auto_confirm_field_heading": False})

    action.update({})
    action.update({})
    action.update({})
    result = action.update({"relative_altitude": 0.2})

    assert result.failed is True
    assert result.reason == "takeoff_timeout"


def test_takeoff_default_auto_confirm_outputs_field_heading_action_first() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    result = action.update(
        {"drone": {"attitude_valid": True, "yaw": 1.2, "local_position_valid": True, "local_x": 10, "local_y": 20, "local_z": -1}}
    )

    assert result.reason == "field_heading_confirm_sent"
    assert result.actions[0]["action_type"] == "confirm_field_heading"
    assert result.actions[0]["params"]["yaw_rad"] == pytest.approx(1.2)
    assert result.actions[0]["params"]["source"] == "takeoff_auto"
    assert result.actions[0]["params"]["drone"]["local_x"] == pytest.approx(10)
    assert result.actions[0]["params"]["drone"]["local_y"] == pytest.approx(20)
    assert result.actions[0]["params"]["drone"]["local_z"] == pytest.approx(-1)
    assert action.phase == "set_mode"


def test_takeoff_skips_auto_confirm_when_field_heading_and_origin_already_confirmed() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    result = action.update(
        {
            "field_heading_confirmed": True,
            "field_origin_confirmed": True,
            "field_heading_yaw_rad": 0.8,
        }
    )

    assert result.reason == "set_mode_sent"
    assert result.actions[0]["action_type"] == "set_mode"
    assert result.detail["note"] == "field heading/origin already confirmed; skip takeoff auto confirm"


def test_takeoff_wait_altitude_holds_start_position_and_field_heading_yaw() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0, "auto_confirm_field_heading": False})
    context = {
        "local_position": {"x": 4.0, "y": -2.0, "z": 0.0},
        "field_heading_yaw_rad": 0.75,
    }
    action.update(context)
    action.update(context)
    action.update(context)

    result = action.update(
        {
            "relative_altitude": 1.0,
            "local_position": {"x": 4.2, "y": -1.8, "z": -1.0},
            "field_heading_yaw_rad": 1.1,
        }
    )

    assert result.reason == "waiting_for_takeoff_altitude"
    hold = result.actions[0]
    assert hold["action_type"] == "local_position"
    assert hold["params"] == {
        "x": pytest.approx(4.0),
        "y": pytest.approx(-2.0),
        "z": pytest.approx(-3.0),
        "frame": 1,
        "yaw": pytest.approx(0.75),
    }
    assert hold["once"] is False
    assert hold["key"] == "takeoff_yaw_hold"


def test_takeoff_after_confirm_outputs_set_mode_next() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    action.update(
        {"drone": {"attitude_valid": True, "yaw": -0.4, "local_position_valid": True, "local_x": 0, "local_y": 0, "local_z": 0}}
    )
    result = action.update({"field_heading_confirmed": True, "field_heading_yaw_rad": -0.4})

    assert result.reason == "set_mode_sent"
    assert result.actions[0]["action_type"] == "set_mode"
    assert result.detail["field_heading_confirmed"] is True
    assert result.detail["field_heading_yaw_rad"] == pytest.approx(-0.4)


def test_takeoff_auto_confirm_missing_yaw_fails_before_set_mode() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    result = action.update({"drone": {"attitude_valid": False, "yaw": 0.0}})

    assert result.failed is True
    assert result.reason == "missing_field_heading_yaw"
    assert result.actions == []
    assert result.detail["phase"] == "confirm_field_heading"
    assert result.detail["attitude_valid"] is False


def test_takeoff_auto_confirm_missing_local_position_fails_before_set_mode() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    result = action.update({"drone": {"attitude_valid": True, "yaw": 0.3, "local_position_valid": False}})

    assert result.failed is True
    assert result.reason == "missing_field_origin"
    assert result.actions == []
    assert result.detail["phase"] == "confirm_field_heading"


def test_takeoff_rejects_invalid_altitude() -> None:
    action = TakeoffAction()

    with pytest.raises(ValueError):
        action.start({"altitude_m": 0})


def test_takeoff_rejects_empty_mode() -> None:
    action = TakeoffAction()

    with pytest.raises(ValueError):
        action.start({"mode": " "})
