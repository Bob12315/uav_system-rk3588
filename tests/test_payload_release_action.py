from __future__ import annotations

import json

import pytest

from missions.common.actions.payload_release import PayloadReleaseAction


def _params(**overrides):
    data = {
        "channel": 13,
        "release_pwm": 1900,
        "hold_pwm": 1100,
        "payload_id": "payload_1",
        "target_id": "target_a",
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "params",
    [
        {"hold_pwm": 1100, "payload_id": "p", "target_id": "t"},
        {"release_pwm": 1900, "payload_id": "p", "target_id": "t"},
        _params(release_pwm=499),
        _params(release_pwm=2501),
        _params(hold_pwm=499),
        _params(hold_pwm=2501),
        _params(channel=0),
        _params(channels=[]),
        _params(payload_id=""),
        _params(target_id=""),
        _params(release_wait_updates=0),
    ],
)
def test_start_rejects_invalid_params(params) -> None:
    action = PayloadReleaseAction()

    with pytest.raises(ValueError):
        action.start(params)


def test_update_before_start_fails() -> None:
    result = PayloadReleaseAction().update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_default_channel_is_rc13() -> None:
    action = PayloadReleaseAction()
    action.start(
        {
            "release_pwm": 1900,
            "hold_pwm": 1100,
            "payload_id": "payload_1",
            "target_id": "target_a",
        }
    )

    assert action.channels == [13]
    assert action.update({}).detail["channels"] == [13]


def test_single_channel_rc13_release_action() -> None:
    action = PayloadReleaseAction()
    action.start(_params(channel=13))

    result = action.update({"timestamp": 12.5})

    assert result.reason == "release_sent"
    assert result.done is False
    assert len(result.actions) == 1
    assert result.actions[0]["action_type"] == "set_servo"
    assert result.actions[0]["params"] == {"channel": 13, "pwm": 1900}
    assert result.actions[0]["once"] is True
    assert result.detail["release_time"] == pytest.approx(12.5)


def test_single_channel_rc14_release_action() -> None:
    action = PayloadReleaseAction()
    action.start(_params(channel=14))

    result = action.update({})

    assert result.actions[0]["action_type"] == "set_servo"
    assert result.actions[0]["params"]["channel"] == 14


def test_dual_channel_rc13_rc14_release_actions() -> None:
    action = PayloadReleaseAction()
    action.start(_params(channels=[13, 14], channel=99))

    result = action.update({})

    assert [item["params"]["channel"] for item in result.actions] == [13, 14]
    assert result.actions[0]["key"].endswith("_release_rc13")
    assert result.actions[1]["key"].endswith("_release_rc14")


def test_channels_are_deduplicated_in_order() -> None:
    action = PayloadReleaseAction()
    action.start(_params(channels=[13, 14, 13]))

    result = action.update({})

    assert result.detail["channels"] == [13, 14]


def test_wait_phase_does_not_repeat_release() -> None:
    action = PayloadReleaseAction()
    action.start(_params(release_wait_updates=3))

    first = action.update({})
    second = action.update({})

    assert first.reason == "release_sent"
    assert second.reason == "release_waiting"
    assert second.actions == []
    assert second.detail["wait_updates"] == 1


def test_wait_completion_sends_hold_pwm_once_and_finishes() -> None:
    action = PayloadReleaseAction()
    action.start(_params(release_wait_updates=2))

    action.update({})
    waiting = action.update({})
    done = action.update({})
    after = action.update({})

    assert waiting.reason == "release_waiting"
    assert done.done is True
    assert done.reason == "payload_released"
    assert done.actions[0]["action_type"] == "set_servo"
    assert done.actions[0]["params"] == {"channel": 13, "pwm": 1100}
    assert done.actions[0]["key"].endswith("_hold_rc13")
    assert after.done is True
    assert after.reason == "payload_released"
    assert after.actions == []


def test_release_time_param_takes_priority() -> None:
    action = PayloadReleaseAction()
    action.start(_params(release_time="planned_t"))

    result = action.update({"timestamp": 99.0})

    assert result.detail["release_time"] == "planned_t"


def test_release_time_falls_back_to_context_time() -> None:
    action = PayloadReleaseAction()
    action.start(_params())

    result = action.update({"time": 3.5})

    assert result.detail["release_time"] == pytest.approx(3.5)


def test_stop_then_update_returns_stopped_without_hold_action() -> None:
    action = PayloadReleaseAction()
    action.start(_params())
    action.stop()

    result = action.update({})

    assert result.done is True
    assert result.reason == "stopped"
    assert result.actions == []


def test_reset_then_update_returns_action_not_started() -> None:
    action = PayloadReleaseAction()
    action.start(_params())
    action.reset()

    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_priority_default_and_custom_priority() -> None:
    default_action = PayloadReleaseAction()
    default_action.start(_params())
    custom_action = PayloadReleaseAction()
    custom_action.start(_params(priority=7))

    default_result = default_action.update({})
    custom_result = custom_action.update({})

    assert default_result.actions[0]["priority"] == 3
    assert custom_result.actions[0]["priority"] == 7


def test_default_and_custom_key() -> None:
    default_action = PayloadReleaseAction()
    default_action.start(_params(payload_id="p1", target_id="t1"))
    custom_action = PayloadReleaseAction()
    custom_action.start(_params(key="custom_release"))

    default_result = default_action.update({})
    custom_result = custom_action.update({})

    assert default_result.actions[0]["key"] == "payload_release_p1_t1_release_rc13"
    assert custom_result.actions[0]["key"] == "custom_release_release_rc13"


def test_output_is_plain_json_serializable_set_servo_dict() -> None:
    action = PayloadReleaseAction()
    action.start(_params(channels=[13, 14]))

    result = action.update({"timestamp": 1.0})

    assert all(item["action_type"] == "set_servo" for item in result.actions)
    assert all(item["action_type"] != "release_payload" for item in result.actions)
    assert result.detail["payload_id"] == "payload_1"
    assert result.detail["target_id"] == "target_a"
    json.dumps(result.to_dict())
