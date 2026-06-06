from __future__ import annotations

import json

import pytest

from missions.common.actions.align_descend import (
    AlignDescendAction,
    AlignDescendConfig,
    compute_align_descend_command,
)


def _valid_inputs(**overrides):
    data = {
        "target_valid": True,
        "target_locked": True,
        "control_allowed": True,
        "ex_cam": 0.02,
        "ey_cam": 0.03,
    }
    data.update(overrides)
    return data


def _active_context(**overrides):
    data = _valid_inputs(**overrides)
    data.setdefault("drone", {"relative_altitude": 5.0})
    return data


def test_align_descend_config_defaults() -> None:
    config = AlignDescendConfig()
    assert config.kp_vx == pytest.approx(0.8)
    assert config.descend_speed_mps == pytest.approx(0.2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kp_vx": -0.1},
        {"kp_vy": -0.1},
        {"max_vx_mps": 0.0},
        {"max_vy_mps": 0.0},
        {"descend_speed_mps": 0.0},
        {"max_ex_cam": 0.0},
        {"max_ey_cam": 0.0},
        {"deadband_ex_cam": -0.1},
        {"deadband_ey_cam": -0.1},
        {"deadband_ex_cam": 0.2, "max_ex_cam": 0.1},
        {"deadband_ey_cam": 0.2, "max_ey_cam": 0.1},
        {"vx_sign": 0.0},
        {"vy_sign": 0.0},
    ],
)
def test_align_descend_config_rejects_invalid_values(kwargs) -> None:
    with pytest.raises(ValueError):
        AlignDescendConfig(**kwargs)


def test_helper_maps_camera_error_to_body_velocity_with_signs() -> None:
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        AlignDescendConfig(),
    )

    assert detail["enabled"] is True
    assert command["vx_cmd"] == pytest.approx(-0.16)
    assert command["vy_cmd"] == pytest.approx(0.08)
    assert command["vz_cmd"] == pytest.approx(0.0)


def test_helper_clamps_velocity() -> None:
    command, _ = compute_align_descend_command(
        _valid_inputs(ex_cam=10.0, ey_cam=-10.0),
        AlignDescendConfig(),
    )

    assert command["vx_cmd"] == pytest.approx(0.4)
    assert command["vy_cmd"] == pytest.approx(0.4)


def test_helper_deadband_zeroes_corresponding_axis() -> None:
    command, _ = compute_align_descend_command(
        _valid_inputs(ex_cam=0.01, ey_cam=0.01),
        AlignDescendConfig(),
    )

    assert command["vx_cmd"] == pytest.approx(0.0)
    assert command["vy_cmd"] == pytest.approx(0.0)


def test_helper_descends_only_when_aligned() -> None:
    aligned_command, aligned_detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        AlignDescendConfig(descend_speed_mps=0.3),
    )
    unaligned_command, unaligned_detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.2, ey_cam=0.02),
        AlignDescendConfig(descend_speed_mps=0.3),
    )

    assert aligned_detail["aligned"] is True
    assert aligned_command["vz_cmd"] == pytest.approx(0.3)
    assert unaligned_detail["aligned"] is False
    assert unaligned_command["vz_cmd"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("inputs", "reason"),
    [
        (_valid_inputs(control_allowed=False), "control_not_allowed"),
        (_valid_inputs(target_valid=False, vision_valid=False), "target_not_valid"),
        (_valid_inputs(target_locked=False), "target_not_locked"),
        ({"target_valid": True, "target_locked": True}, "missing_error"),
    ],
)
def test_helper_invalid_inputs_return_inactive_command(inputs, reason) -> None:
    command, detail = compute_align_descend_command(inputs, AlignDescendConfig())

    assert detail["enabled"] is False
    assert detail["aligned"] is False
    assert detail["hold_reason"] == reason
    assert command["active"] is False
    assert command["vx_cmd"] == pytest.approx(0.0)
    assert command["vy_cmd"] == pytest.approx(0.0)
    assert command["vz_cmd"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "params",
    [
        {"lost_timeout_updates": 0},
        {"hold_updates_required": 0},
        {"max_retries": -1},
        {"max_updates": 0},
        {"expected_dt_s": 0.0},
        {"finish_altitude_m": 0.0},
        {"min_altitude_m": 0.0},
    ],
)
def test_start_rejects_invalid_params(params) -> None:
    action = AlignDescendAction()
    with pytest.raises(ValueError):
        action.start(params)


def test_start_converts_seconds_to_update_counts() -> None:
    action = AlignDescendAction()
    action.start(
        {
            "expected_dt_s": 0.2,
            "lost_timeout_s": 0.41,
            "hold_time_s": 0.61,
        }
    )

    assert action.lost_timeout_updates == 3
    assert action.hold_updates_required == 4


def test_update_before_start_fails() -> None:
    result = AlignDescendAction().update(_active_context())

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_normal_unaligned_update_outputs_active_zero_descent() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(_active_context(ex_cam=0.2, ey_cam=0.02))

    assert result.done is False
    assert result.actions == []
    assert result.detail["command"]["active"] is True
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.0)
    assert result.reason == "aligning"


def test_normal_aligned_update_descends_without_finishing_when_no_altitude_threshold() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(_active_context(ex_cam=0.02, ey_cam=0.02))

    assert result.done is False
    assert result.detail["command"]["active"] is True
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.2)
    assert result.reason == "align_descending"


def test_aligned_low_altitude_finishes_after_required_hold() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 1.0, "hold_updates_required": 2})

    first = action.update(_active_context(ex_cam=0.02, ey_cam=0.02, drone={"relative_altitude": 0.9}))
    second = action.update(_active_context(ex_cam=0.02, ey_cam=0.02, drone={"relative_altitude": 0.8}))

    assert first.done is False
    assert second.done is True
    assert second.reason == "align_descend_done"
    assert second.detail["command"]["active"] is False


def test_finish_altitude_uses_safer_max_of_finish_and_min_altitude() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 0.8, "min_altitude_m": 1.2, "hold_updates_required": 1})

    result = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, drone={"relative_altitude": 1.0}))

    assert action.finish_altitude_m == pytest.approx(1.2)
    assert result.done is True


def test_hold_counter_resets_when_alignment_is_lost() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 1.0, "hold_updates_required": 2})

    first = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, drone={"relative_altitude": 0.8}))
    second = action.update(_active_context(ex_cam=0.2, ey_cam=0.0, drone={"relative_altitude": 0.8}))
    third = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, drone={"relative_altitude": 0.8}))

    assert first.detail["hold_updates"] == 1
    assert second.detail["hold_updates"] == 0
    assert third.detail["hold_updates"] == 1
    assert third.done is False


def test_lost_timeout_retries_before_failure() -> None:
    action = AlignDescendAction()
    action.start({"lost_timeout_updates": 1, "max_retries": 1})

    first = action.update(_active_context(target_valid=False, vision_valid=False))
    second = action.update(_active_context(target_valid=False, vision_valid=False))

    assert first.failed is False
    assert second.failed is False
    assert second.reason == "align_retry"
    assert second.detail["retries"] == 1
    assert second.detail["command"]["active"] is False


def test_lost_timeout_fails_after_retries_are_exhausted() -> None:
    action = AlignDescendAction()
    action.start({"lost_timeout_updates": 1, "max_retries": 0})

    action.update(_active_context(target_valid=False, vision_valid=False))
    failed = action.update(_active_context(target_valid=False, vision_valid=False))
    after = action.update(_active_context())

    assert failed.failed is True
    assert failed.reason == "target_lost_timeout"
    assert after.failed is True
    assert after.reason == "target_lost_timeout"
    assert after.detail["command"]["active"] is False


def test_max_updates_timeout() -> None:
    action = AlignDescendAction()
    action.start({"max_updates": 1})

    action.update(_active_context())
    result = action.update(_active_context())

    assert result.failed is True
    assert result.reason == "align_descend_timeout"
    assert result.detail["command"]["active"] is False


def test_stop_then_update_returns_stopped_with_inactive_command() -> None:
    action = AlignDescendAction()
    action.start()
    action.stop()

    result = action.update(_active_context())

    assert result.done is True
    assert result.reason == "stopped"
    assert result.actions == []
    assert result.detail["command"]["active"] is False


def test_reset_then_update_returns_action_not_started() -> None:
    action = AlignDescendAction()
    action.start()
    action.reset()

    result = action.update(_active_context())

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_context_perception_input_is_supported() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(
        {
            "perception": {
                "target_valid": True,
                "tracking_state": "locked",
                "ex": 0.02,
                "ey": 0.02,
            }
        }
    )

    assert result.detail["enabled"] is True
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.2)


def test_context_target_input_is_supported() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(
        {
            "target": {
                "target_valid": True,
                "target_locked": True,
                "ex_cam": 0.02,
                "ey_cam": 0.02,
            }
        }
    )

    assert result.detail["enabled"] is True
    assert result.detail["command"]["active"] is True


def test_height_priority_and_local_z_fallback() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 1.0, "hold_updates_required": 1})

    result = action.update(
        _active_context(
            ex_cam=0.0,
            ey_cam=0.0,
            drone={"local_position": {"x": 0.0, "y": 0.0, "z": -0.7}},
        )
    )

    assert result.done is True
    assert result.detail["height_m"] == pytest.approx(0.7)


def test_output_is_plain_json_serializable_dict() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(_active_context(ex_cam=0.02, ey_cam=0.02))

    assert result.actions == []
    assert isinstance(result.detail["command"], dict)
    assert result.detail["command"]["type"] == "flight_command"
    json.dumps(result.to_dict())
