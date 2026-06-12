from __future__ import annotations

import pytest

from missions.common.actions.takeoff import TakeoffAction


def test_takeoff_start_uses_default_params() -> None:
    action = TakeoffAction()

    action.start({})

    assert action.altitude_m == 3.0
    assert action.mode == "GUIDED"
    assert action.phase == "set_mode"


def test_takeoff_update_before_start_fails() -> None:
    action = TakeoffAction()

    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_takeoff_set_mode_phase_outputs_set_mode_action() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})

    result = action.update({})

    assert result.reason == "set_mode_sent"
    assert result.actions[0]["action_type"] == "set_mode"
    assert result.actions[0]["params"]["mode"] == "GUIDED"
    assert result.actions[0]["once"] is True


def test_takeoff_arm_phase_outputs_arm_action() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})
    action.update({})

    result = action.update({})

    assert result.reason == "arm_sent"
    assert result.actions[0]["action_type"] == "arm"


def test_takeoff_phase_outputs_takeoff_action() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})
    action.update({})
    action.update({})

    result = action.update({})

    assert result.reason == "takeoff_sent"
    assert result.actions[0]["action_type"] == "takeoff"
    assert result.actions[0]["params"]["altitude_m"] == 3.0


def test_takeoff_wait_altitude_until_target_reached() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})
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
    action.start({"altitude_m": 3.0})
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
    action.start({"require_armed": False})

    set_mode = action.update({})
    takeoff = action.update({})

    assert set_mode.reason == "set_mode_sent"
    assert takeoff.reason == "takeoff_sent"
    assert takeoff.actions[0]["action_type"] == "takeoff"
    assert action.arm_sent is False


def test_takeoff_waits_for_altitude_data_without_immediate_failure() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.0})
    action.update({})
    action.update({})
    action.update({})

    result = action.update({})

    assert result.failed is False
    assert result.done is False
    assert result.reason == "waiting_for_altitude"


def test_takeoff_times_out_after_max_updates() -> None:
    action = TakeoffAction()
    action.start({"max_updates": 3})

    action.update({})
    action.update({})
    action.update({})
    result = action.update({"relative_altitude": 0.2})

    assert result.failed is True
    assert result.reason == "takeoff_timeout"


def test_takeoff_rejects_invalid_altitude() -> None:
    action = TakeoffAction()

    with pytest.raises(ValueError):
        action.start({"altitude_m": 0})


def test_takeoff_rejects_empty_mode() -> None:
    action = TakeoffAction()

    with pytest.raises(ValueError):
        action.start({"mode": " "})
