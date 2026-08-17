from __future__ import annotations

import pytest

from missions.common.actions.land import LandAction


def test_land_start_uses_default_params() -> None:
    action = LandAction()

    action.start({})

    assert action.land_altitude_threshold_m == 0.25
    assert action.max_updates == 200
    assert action.phase == "send_land"


def test_land_update_before_start_fails() -> None:
    action = LandAction()

    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_land_send_land_phase_outputs_land_action() -> None:
    action = LandAction()
    action.start({})

    result = action.update({})

    assert result.reason == "land_sent"
    assert result.actions[0]["action_type"] == "land"
    assert result.actions[0]["once"] is True
    assert result.actions[0]["priority"] == 2


def test_land_wait_landed_when_altitude_high_and_armed() -> None:
    action = LandAction()
    action.start({})
    action.update({})

    result = action.update({"relative_altitude": 1.2, "drone": {"armed": True}})

    assert result.done is False
    assert result.reason == "waiting_for_landing"


def test_land_done_when_altitude_below_threshold() -> None:
    action = LandAction()
    action.start({})
    action.update({})

    result = action.update({"relative_altitude": 0.2, "drone": {"armed": True}})

    assert result.done is True
    assert result.reason == "landed"


def test_land_done_when_disarmed_even_if_altitude_high() -> None:
    action = LandAction()
    action.start({})
    action.update({})

    result = action.update({"relative_altitude": 1.0, "drone": {"armed": False}})

    assert result.done is True
    assert result.reason == "landed"


def test_land_reads_altitude_from_local_position_z() -> None:
    action = LandAction()
    action.start({})
    action.update({})

    result = action.update({"local_position": {"x": 0, "y": 0, "z": -0.1}})

    assert result.done is True
    assert result.reason == "landed"
    assert result.detail["current_altitude_m"] == 0.1
    assert result.detail["altitude_source"] == "local_position.z"


def test_land_waits_for_landing_state_when_altitude_and_armed_missing() -> None:
    action = LandAction()
    action.start({})
    action.update({})

    result = action.update({})

    assert result.done is False
    assert result.failed is False
    assert result.reason == "waiting_for_landing_state"


def test_land_times_out_after_max_updates() -> None:
    action = LandAction()
    action.start({"max_updates": 3})

    action.update({"relative_altitude": 1.0, "armed": True})
    action.update({"relative_altitude": 1.0, "armed": True})
    action.update({"relative_altitude": 1.0, "armed": True})
    result = action.update({"relative_altitude": 1.0, "armed": True})

    assert result.failed is True
    assert result.reason == "land_timeout"


def test_land_rejects_invalid_threshold() -> None:
    action = LandAction()

    with pytest.raises(ValueError):
        action.start({"land_altitude_threshold_m": -0.1})


def test_land_rejects_invalid_max_updates() -> None:
    action = LandAction()

    with pytest.raises(ValueError):
        action.start({"max_updates": 0})


def test_land_accepts_armed_string_false() -> None:
    action = LandAction()
    action.start({})
    action.update({})

    result = action.update({"vehicle": {"armed": "false"}})

    assert result.done is True
    assert result.reason == "landed"
