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
    assert config.yaw_control_mode == "hold"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kp_vx": -0.1},
        {"kp_vy": -0.1},
        {"max_vx_mps": 0.0},
        {"max_vy_mps": 0.0},
        {"descend_speed_mps": 0.0},
        {"slow_descend_speed_mps": -0.01},
        {"max_ex_cam": 0.0},
        {"max_ey_cam": 0.0},
        {"slow_descend_max_ex_cam": 0.0},
        {"slow_descend_max_ey_cam": 0.0},
        {"slow_descend_max_ex_cam": 0.05, "max_ex_cam": 0.1},
        {"slow_descend_max_ey_cam": 0.05, "max_ey_cam": 0.1},
        {"deadband_ex_cam": -0.1},
        {"deadband_ey_cam": -0.1},
        {"deadband_ex_cam": 0.2, "max_ex_cam": 0.1},
        {"deadband_ey_cam": 0.2, "max_ey_cam": 0.1},
        {"vx_sign": 0.0},
        {"vy_sign": 0.0},
        {"gain_low_altitude_m": 0.0},
        {"gain_low_altitude_m": -0.1},
        {"gain_low_altitude_m": 1.0, "gain_high_altitude_m": 1.0},
        {"gain_low_altitude_m": 1.0, "gain_high_altitude_m": 0.9},
        {"gain_high_scale": 0.0},
        {"gain_high_scale": -0.1},
        {"gain_high_scale": 1.1},
        {"descent_gate_policy": "invalid"},
        {"yaw_control_mode": "invalid"},
        {"unaligned_descend_speed_mps": -0.01},
        {"descent_gate_policy": "allow_unaligned", "unaligned_descend_speed_mps": 0.5, "descend_speed_mps": 0.2},
        {"unaligned_descend_speed_mps": float("nan")},
        {"unaligned_descend_speed_mps": float("inf")},
        {"descend_speed_mps": float("nan")},
        {"descend_speed_mps": float("inf")},
        {"slow_descend_speed_mps": float("nan")},
        {"slow_descend_speed_mps": float("inf")},
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


def test_height_gain_disabled_by_default_keeps_existing_behavior() -> None:
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        AlignDescendConfig(),
        altitude_m=3.0,
    )

    assert command["vx_cmd"] == pytest.approx(-0.16)
    assert command["vy_cmd"] == pytest.approx(0.08)
    assert detail["height_gain_scale"] == pytest.approx(1.0)
    assert detail["kp_vx_eff"] == pytest.approx(0.8)
    assert detail["kp_vy_eff"] == pytest.approx(0.8)
    assert detail["max_vx_eff"] == pytest.approx(0.4)
    assert detail["max_vy_eff"] == pytest.approx(0.4)


def test_height_gain_scales_kp_and_max_velocity_at_high_altitude() -> None:
    config = AlignDescendConfig(
        height_gain_enabled=True,
        gain_low_altitude_m=1.0,
        gain_high_altitude_m=3.0,
        gain_high_scale=0.25,
        kp_vx=0.8,
        kp_vy=0.8,
        max_vx_mps=0.4,
        max_vy_mps=0.4,
    )

    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        config,
        altitude_m=3.0,
    )

    assert detail["height_gain_scale"] == pytest.approx(0.25)
    assert command["vx_cmd"] == pytest.approx(-0.04)
    assert command["vy_cmd"] == pytest.approx(0.02)
    assert detail["max_vx_eff"] == pytest.approx(0.1)
    assert detail["max_vy_eff"] == pytest.approx(0.1)


def test_height_gain_restores_original_kp_at_low_altitude() -> None:
    config = AlignDescendConfig(
        height_gain_enabled=True,
        gain_low_altitude_m=1.0,
        gain_high_altitude_m=3.0,
        gain_high_scale=0.25,
    )

    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        config,
        altitude_m=1.0,
    )

    assert detail["height_gain_scale"] == pytest.approx(1.0)
    assert command["vx_cmd"] == pytest.approx(-0.16)
    assert command["vy_cmd"] == pytest.approx(0.08)


def test_height_gain_interpolates_linearly_between_altitudes() -> None:
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        AlignDescendConfig(
            height_gain_enabled=True,
            gain_low_altitude_m=1.0,
            gain_high_altitude_m=3.0,
            gain_high_scale=0.25,
        ),
        altitude_m=2.0,
    )

    assert detail["height_gain_scale"] == pytest.approx(0.625)


def test_height_gain_can_leave_max_velocity_unscaled() -> None:
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=1.0, ey_cam=1.0),
        AlignDescendConfig(
            height_gain_enabled=True,
            gain_low_altitude_m=1.0,
            gain_high_altitude_m=3.0,
            gain_high_scale=0.25,
            kp_vx=0.8,
            kp_vy=0.8,
            max_vx_mps=0.4,
            max_vy_mps=0.4,
            scale_max_velocity_with_height=False,
        ),
        altitude_m=3.0,
    )

    assert detail["height_gain_scale"] == pytest.approx(0.25)
    assert detail["kp_vx_eff"] == pytest.approx(0.2)
    assert detail["kp_vy_eff"] == pytest.approx(0.2)
    assert detail["max_vx_eff"] == pytest.approx(0.4)
    assert detail["max_vy_eff"] == pytest.approx(0.4)
    assert command["vx_cmd"] == pytest.approx(-0.2)
    assert command["vy_cmd"] == pytest.approx(0.2)


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


def test_helper_allows_configured_slow_descent_near_alignment() -> None:
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.08, ey_cam=0.02),
        AlignDescendConfig(
            max_ex_cam=0.05,
            max_ey_cam=0.05,
            slow_descend_speed_mps=0.06,
            slow_descend_max_ex_cam=0.10,
            slow_descend_max_ey_cam=0.10,
        ),
    )

    assert detail["aligned"] is False
    assert detail["slow_descending"] is True
    assert detail["hold_reason"] == "descending_slow"
    assert command["vz_cmd"] == pytest.approx(0.06)


def test_helper_does_not_slow_descend_outside_configured_window() -> None:
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.12, ey_cam=0.02),
        AlignDescendConfig(
            max_ex_cam=0.05,
            max_ey_cam=0.05,
            slow_descend_speed_mps=0.06,
            slow_descend_max_ex_cam=0.10,
            slow_descend_max_ey_cam=0.10,
        ),
    )

    assert detail["slow_descending"] is False
    assert detail["hold_reason"] == "aligning"
    assert command["vz_cmd"] == pytest.approx(0.0)


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
    assert result.detail["ex_cam"] == pytest.approx(0.2)
    assert result.detail["ey_cam"] == pytest.approx(0.02)
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

    assert first.done is True
    assert first.reason == "min_altitude_reached"
    assert first.detail["command"]["active"] is False
    assert first.detail["command"]["vz_cmd"] == pytest.approx(0.0)


def test_finish_altitude_uses_safer_max_of_finish_and_min_altitude() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 0.8, "min_altitude_m": 1.2, "hold_updates_required": 1})

    result = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, drone={"relative_altitude": 1.0}))

    assert action.finish_altitude_m == pytest.approx(1.2)
    assert result.done is True


def test_hold_counter_resets_when_alignment_is_lost() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 1.0, "hold_updates_required": 2})

    first = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, drone={"relative_altitude": 3.0}))
    second = action.update(_active_context(ex_cam=0.2, ey_cam=0.0, drone={"relative_altitude": 3.0}))
    third = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, drone={"relative_altitude": 3.0}))

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
            "relative_altitude": 5.0,
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
            "relative_altitude": 5.0,
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


def test_align_descend_uses_arm_heading_yaw_before_current_drone_yaw() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(
        _active_context(
            arm_heading_yaw_rad=1.7,
            drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": 0.2},
        )
    )

    assert result.detail["yaw_hold_active"] is True
    assert result.detail["yaw_hold_rad"] == pytest.approx(1.7)
    assert result.detail["yaw_hold_source"] == "arm_heading"
    assert result.detail["command"]["yaw_hold_rad"] == pytest.approx(1.7)
    assert result.detail["command"]["velocity_yaw_rad"] == pytest.approx(0.2)


def test_legacy_default_yaw_control_mode_holds_valid_yaw() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(
        _active_context(
            ex_cam=0.03,
            ey_cam=0.04,
            drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": 0.6},
        )
    )

    assert action.config.yaw_control_mode == "hold"
    assert result.detail["command"]["yaw_hold_rad"] == pytest.approx(0.6)
    assert result.detail["command"]["velocity_yaw_rad"] == pytest.approx(0.6)


def test_ignore_yaw_control_active_command_is_pure_body_ned() -> None:
    action = AlignDescendAction()
    action.start(
        {
            "finish_altitude_m": 1.3,
            "config": {"min_altitude_m": 1.3, "yaw_control_mode": "ignore"},
        }
    )

    result = action.update(
        _active_context(
            ex_cam=0.03,
            ey_cam=0.04,
            relative_altitude=5.0,
            drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": 0.8},
        )
    )
    command = result.detail["command"]

    assert command["valid"] is True
    assert command["active"] is True
    assert any(abs(command[name]) > 0.0 for name in ("vx_cmd", "vy_cmd", "vz_cmd"))
    assert "yaw_hold_rad" not in command
    assert "velocity_yaw_rad" not in command


def test_ignore_yaw_control_finish_altitude_commands_have_no_yaw() -> None:
    action = AlignDescendAction()
    action.start(
        {
            "finish_altitude_m": 1.3,
            "finish_policy": "require_alignment_or_timeout",
            "hold_updates_required": 2,
            "config": {"min_altitude_m": 1.3, "yaw_control_mode": "ignore"},
        }
    )
    yaw_context = {
        "relative_altitude": 1.3,
        "drone": {"relative_altitude": 1.3, "attitude_valid": True, "yaw": 1.1},
    }

    correcting = action.update(_active_context(ex_cam=0.2, ey_cam=0.0, **yaw_context))
    correcting_command = correcting.detail["command"]
    assert correcting.reason == "aligning_at_finish_altitude"
    assert correcting_command["vz_cmd"] == pytest.approx(0.0)
    assert abs(correcting_command["vy_cmd"]) > 0.0
    assert "yaw_hold_rad" not in correcting_command
    assert "velocity_yaw_rad" not in correcting_command

    holding = action.update(_active_context(ex_cam=0.02, ey_cam=0.02, **yaw_context))
    assert holding.done is False
    done = action.update(_active_context(ex_cam=0.02, ey_cam=0.02, **yaw_context))
    assert done.done is True
    assert done.reason == "aligned_at_finish_altitude"
    assert "yaw_hold_rad" not in done.detail["command"]
    assert "velocity_yaw_rad" not in done.detail["command"]


def test_align_descend_prefers_field_heading_over_arm_heading() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(
        _active_context(
            field_heading_yaw_rad=-1.1,
            field_heading_confirmed=True,
            field_heading_source="takeoff_auto",
            arm_heading_yaw_rad=1.7,
            drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": 0.2},
        )
    )

    assert result.detail["yaw_hold_active"] is True
    assert result.detail["yaw_hold_rad"] == pytest.approx(-1.1)
    assert result.detail["yaw_hold_source"] == "field_heading"
    assert result.detail["field_heading_yaw_rad"] == pytest.approx(-1.1)
    assert result.detail["field_heading_confirmed"] is True
    assert result.detail["field_heading_source"] == "takeoff_auto"
    assert result.detail["command"]["yaw_hold_rad"] == pytest.approx(-1.1)


def test_align_descend_does_not_lock_default_yaw_when_attitude_invalid() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(
        _active_context(
            drone={"relative_altitude": 5.0, "attitude_valid": False, "yaw": 0.0},
        )
    )

    assert result.detail["yaw_hold_active"] is False
    assert result.detail["yaw_hold_rad"] is None
    assert "yaw_hold_rad" not in result.detail["command"]


def test_align_descend_keeps_initial_yaw_hold_across_updates() -> None:
    action = AlignDescendAction()
    action.start()

    action.update(_active_context(drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": 1.25}))
    result = action.update(_active_context(drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": -0.5}))

    assert result.detail["yaw_hold_rad"] == pytest.approx(1.25)
    assert result.detail["command"]["yaw_hold_rad"] == pytest.approx(1.25)


def test_entry_attitude_yaw_uses_only_valid_drone_or_vehicle_attitude() -> None:
    action = AlignDescendAction()
    action.start({"config": {"yaw_control_mode": "hold_entry_attitude"}})

    waiting = action.update(
        _active_context(
            field_heading_yaw_rad=-1.0,
            arm_heading_yaw_rad=2.0,
            drone={"relative_altitude": 5.0, "attitude_valid": False, "yaw": 0.3},
        )
    )
    assert waiting.reason == "waiting_for_entry_attitude_yaw"
    assert waiting.detail["command"]["vx_cmd"] == pytest.approx(0.0)
    assert waiting.detail["command"]["vy_cmd"] == pytest.approx(0.0)
    assert waiting.detail["command"]["vz_cmd"] == pytest.approx(0.0)

    captured = action.update(
        _active_context(
            field_heading_yaw_rad=-1.0,
            arm_heading_yaw_rad=2.0,
            vehicle={"attitude_valid": True, "yaw": 3.13},
        )
    )
    assert captured.detail["command"]["yaw_hold_rad"] == pytest.approx(3.13)
    assert captured.detail["command"]["yaw_hold_source"] == "entry_attitude"

    frozen = action.update(
        _active_context(
            vehicle={"attitude_valid": True, "yaw": -3.13},
            target_valid=False,
            vision_valid=False,
        )
    )
    assert frozen.detail["yaw_hold_rad"] == pytest.approx(3.13)


def test_entry_attitude_yaw_is_new_for_each_align_instance() -> None:
    first = AlignDescendAction()
    first.start({"config": {"yaw_control_mode": "hold_entry_attitude"}})
    first.update(_active_context(drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": 1.2}))
    assert first.yaw_hold_rad == pytest.approx(1.2)
    first.reset()

    second = AlignDescendAction()
    second.start({"config": {"yaw_control_mode": "hold_entry_attitude"}})
    result = second.update(_active_context(drone={"relative_altitude": 5.0, "attitude_valid": True, "yaw": 0.7}))
    assert result.detail["command"]["yaw_hold_rad"] == pytest.approx(0.7)


def test_above_finish_altitude_allows_descent_when_aligned() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 3.0, "config": {"min_altitude_m": 2.5}})

    result = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, relative_altitude=4.0))

    assert result.done is False
    assert result.reason == "align_descending"
    assert result.detail["current_altitude_m"] == pytest.approx(4.0)
    assert result.detail["finish_altitude_m"] == pytest.approx(3.0)
    assert result.detail["min_altitude_m"] == pytest.approx(2.5)
    assert result.detail["altitude_source"] == "relative_altitude"
    assert result.detail["reached_finish_altitude"] is False
    assert result.detail["command"]["active"] is True
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.2)


def test_finish_altitude_reached_stops_and_done() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 3.0, "config": {"min_altitude_m": 2.5}})

    result = action.update(_active_context(ex_cam=0.2, ey_cam=0.0, relative_altitude=3.0))

    assert result.done is True
    assert result.reason == "finish_altitude_reached"
    assert result.detail["current_altitude_m"] == pytest.approx(3.0)
    assert result.detail["finish_altitude_m"] == pytest.approx(3.0)
    assert result.detail["min_altitude_m"] == pytest.approx(2.5)
    assert result.detail["altitude_source"] == "relative_altitude"
    assert result.detail["reached_finish_altitude"] is True
    assert result.detail["command"]["active"] is False
    assert result.detail["command"]["enable_approach"] is False
    assert result.detail["command"]["vx_cmd"] == pytest.approx(0.0)
    assert result.detail["command"]["vy_cmd"] == pytest.approx(0.0)
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.0)


def test_aligned_at_finish_altitude_uses_specific_reason() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 3.0, "hold_updates_required": 1, "config": {"min_altitude_m": 2.5}})

    result = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, relative_altitude=3.0))

    assert result.done is True
    assert result.reason == "aligned_at_finish_altitude"
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.0)


def test_min_altitude_reached_stops_and_done() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 3.0, "config": {"min_altitude_m": 2.5}})

    result = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, relative_altitude=2.4))

    assert result.done is True
    assert result.reason == "min_altitude_reached"
    assert result.detail["current_altitude_m"] == pytest.approx(2.4)
    assert result.detail["min_altitude_m"] == pytest.approx(2.5)
    assert result.detail["command"]["active"] is False
    assert result.detail["command"]["enable_approach"] is False
    assert result.detail["command"]["vx_cmd"] == pytest.approx(0.0)
    assert result.detail["command"]["vy_cmd"] == pytest.approx(0.0)
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.0)


def test_missing_altitude_fails_without_descent() -> None:
    action = AlignDescendAction()
    action.start()

    result = action.update(_valid_inputs())

    assert result.failed is True
    assert result.reason == "missing_altitude"
    assert result.detail["current_altitude_m"] is None
    assert result.detail["finish_altitude_m"] is None
    assert result.detail["min_altitude_m"] == pytest.approx(2.0)
    assert result.detail["altitude_source"] == ""
    assert result.detail["reached_finish_altitude"] is False
    assert result.detail["command"]["active"] is False
    assert result.detail["command"]["vx_cmd"] == pytest.approx(0.0)
    assert result.detail["command"]["vy_cmd"] == pytest.approx(0.0)
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.0)


def test_local_z_altitude_source_prevents_descent_below_min_altitude() -> None:
    action = AlignDescendAction()
    action.start({"config": {"min_altitude_m": 2.5}})

    result = action.update(_active_context(ex_cam=0.0, ey_cam=0.0, local_z=-2.0))

    assert result.done is True
    assert result.reason == "min_altitude_reached"
    assert result.detail["altitude_source"] == "local_z"
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.0)


def test_vehicle_relative_altitude_source_is_supported() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 3.0, "config": {"min_altitude_m": 2.5}})

    result = action.update(
        _valid_inputs(ex_cam=0.0, ey_cam=0.0, vehicle={"relative_altitude": 4.0})
    )

    assert result.done is False
    assert result.detail["current_altitude_m"] == pytest.approx(4.0)
    assert result.detail["altitude_source"] == "vehicle.relative_altitude"
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.2)


def test_vehicle_local_z_source_stops_at_finish_altitude() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 3.0, "config": {"min_altitude_m": 2.5}})

    result = action.update(
        _valid_inputs(ex_cam=0.2, ey_cam=0.0, vehicle={"local_z": -3.0})
    )

    assert result.done is True
    assert result.reason == "finish_altitude_reached"
    assert result.detail["current_altitude_m"] == pytest.approx(3.0)
    assert result.detail["altitude_source"] == "vehicle.local_z"
    assert result.detail["reached_finish_altitude"] is True
    assert result.detail["command"]["vz_cmd"] == pytest.approx(0.0)


def test_invalid_finish_below_min_altitude_is_clamped() -> None:
    action = AlignDescendAction()
    action.start({"finish_altitude_m": 1.0, "config": {"min_altitude_m": 2.5}})

    assert action.finish_altitude_m == pytest.approx(2.5)


# ── payload offset compensation tests ─────────────────────────────────


def test_payload_offset_disabled_preserves_old_behavior() -> None:
    """With payload_offset_enabled=False, desired offsets are zero, corrected == raw."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        AlignDescendConfig(),
        altitude_m=1.0,
    )

    # same control as before
    assert command["vx_cmd"] == pytest.approx(-0.16)
    assert command["vy_cmd"] == pytest.approx(0.08)
    # desired is zero
    assert detail["desired_ex_cam"] == pytest.approx(0.0)
    assert detail["desired_ey_cam"] == pytest.approx(0.0)
    # corrected equals raw
    assert detail["corrected_ex_cam"] == pytest.approx(0.1)
    assert detail["corrected_ey_cam"] == pytest.approx(0.2)
    assert detail["raw_ex_cam"] == pytest.approx(0.1)
    assert detail["raw_ey_cam"] == pytest.approx(0.2)
    # ex_cam/ey_cam are corrected values
    assert detail["ex_cam"] == pytest.approx(0.1)
    assert detail["ey_cam"] == pytest.approx(0.2)
    assert detail["payload_offset_enabled"] is False


def test_payload_offset_forward_produces_nonzero_desired_ey() -> None:
    """Forward payload (positive payload_forward_m) → desired_ey_cam != 0."""
    config = AlignDescendConfig(
        payload_offset_enabled=True,
        payload_forward_m=0.2,
        payload_right_m=0.0,
        fov_y_deg=90.0,
        image_y_sign=-1.0,
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.0, ey_cam=0.0),
        config,
        altitude_m=1.0,
    )

    # desired_ey = atan(0.2 / (-1 * 1.0)) / radians(45) ≈ negative
    assert detail["desired_ey_cam"] < 0.0
    assert detail["desired_ex_cam"] == pytest.approx(0.0)
    assert detail["payload_offset_enabled"] is True
    assert detail["payload_offset_valid"] is True
    assert detail["payload_forward_m"] == pytest.approx(0.2)


def test_payload_offset_right_produces_nonzero_desired_ex() -> None:
    """Right payload (positive payload_right_m) → desired_ex_cam > 0."""
    config = AlignDescendConfig(
        payload_offset_enabled=True,
        payload_forward_m=0.0,
        payload_right_m=0.2,
        fov_x_deg=90.0,
        image_x_sign=1.0,
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.0, ey_cam=0.0),
        config,
        altitude_m=1.0,
    )

    assert detail["desired_ex_cam"] > 0.0
    assert detail["desired_ey_cam"] == pytest.approx(0.0)
    assert detail["payload_offset_valid"] is True


def test_corrected_error_controls_aligned_judgment() -> None:
    """When raw == desired, corrected is ~0 → aligned=True even if raw is nonzero."""
    config = AlignDescendConfig(
        payload_offset_enabled=True,
        payload_forward_m=0.2,
        fov_y_deg=90.0,
        image_y_sign=-1.0,
        max_ex_cam=0.06,
        max_ey_cam=0.06,
        descend_speed_mps=0.3,
    )

    # compute desired first so we can feed it back as raw
    _, pre = compute_align_descend_command(
        _valid_inputs(ex_cam=0.0, ey_cam=0.0),
        config,
        altitude_m=1.0,
    )
    desired_ex = pre["desired_ex_cam"]
    desired_ey = pre["desired_ey_cam"]

    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=desired_ex, ey_cam=desired_ey),
        config,
        altitude_m=1.0,
    )

    assert detail["aligned"] is True
    assert command["vz_cmd"] == pytest.approx(0.3)
    # corrected should be near zero, raw nonzero
    assert abs(detail["corrected_ex_cam"]) < 1e-6
    assert abs(detail["corrected_ey_cam"]) < 1e-6
    assert abs(detail["raw_ex_cam"]) > 0.0 or abs(detail["raw_ey_cam"]) > 0.0


def test_corrected_error_zeroes_control_when_raw_matches_desired() -> None:
    """vx/vy commands ~0 when raw == desired."""
    config = AlignDescendConfig(
        payload_offset_enabled=True,
        payload_forward_m=0.2,
        fov_y_deg=90.0,
        image_y_sign=-1.0,
    )

    _, pre = compute_align_descend_command(
        _valid_inputs(ex_cam=0.0, ey_cam=0.0),
        config,
        altitude_m=1.0,
    )
    command, _ = compute_align_descend_command(
        _valid_inputs(ex_cam=pre["desired_ex_cam"], ey_cam=pre["desired_ey_cam"]),
        config,
        altitude_m=1.0,
    )

    assert command["vx_cmd"] == pytest.approx(0.0)
    assert command["vy_cmd"] == pytest.approx(0.0)


def test_payload_offset_clamped_at_low_altitude() -> None:
    """At very low altitude, desired offset is clamped to max_payload_offset_ey_cam."""
    config = AlignDescendConfig(
        payload_offset_enabled=True,
        payload_forward_m=2.0,  # very large offset
        payload_right_m=0.0,
        fov_y_deg=90.0,
        image_y_sign=-1.0,
        max_payload_offset_ey_cam=0.3,
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.0, ey_cam=0.0),
        config,
        altitude_m=0.5,
    )

    assert detail["desired_ey_cam"] == pytest.approx(-0.3)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fov_x_deg": 0.0},
        {"fov_x_deg": 180.0},
        {"fov_x_deg": 190.0},
        {"fov_y_deg": 0.0},
        {"fov_y_deg": 180.0},
        {"image_x_sign": 0.0},
        {"image_x_sign": 2.0},
        {"image_y_sign": 0.0},
        {"image_y_sign": -2.0},
        {"max_payload_offset_ex_cam": 0.0},
        {"max_payload_offset_ex_cam": -0.1},
        {"max_payload_offset_ex_cam": 1.6},
        {"max_payload_offset_ey_cam": 0.0},
        {"max_payload_offset_ey_cam": -0.1},
        {"payload_forward_m": float("nan")},
        {"payload_right_m": float("inf")},
    ],
)
def test_payload_offset_config_rejects_invalid_values(kwargs) -> None:
    with pytest.raises(ValueError):
        AlignDescendConfig(**kwargs)


# ── multi-point height gain tests ──────────────────────────────────────


def test_height_gain_default_linear_mode_unchanged() -> None:
    """Default height_gain_mode='linear' preserves old behavior."""
    config = AlignDescendConfig(
        height_gain_enabled=True,
        gain_low_altitude_m=1.0,
        gain_high_altitude_m=3.0,
        gain_high_scale=0.25,
        height_gain_mode="linear",
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        config,
        altitude_m=3.0,
    )
    assert detail["height_gain_scale"] == pytest.approx(0.25)
    assert detail["height_gain_mode"] == "linear"
    assert detail["height_gain_points_active"] is False


def test_height_gain_points_below_min_returns_first_scale() -> None:
    """Height below lowest point returns first scale."""
    config = AlignDescendConfig(
        height_gain_enabled=True,
        height_gain_mode="points",
        height_scale_points=[
            {"altitude_m": 0.8, "scale": 0.40},
            {"altitude_m": 2.4, "scale": 0.80},
        ],
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        config,
        altitude_m=0.5,
    )
    assert detail["height_gain_scale"] == pytest.approx(0.40)
    assert detail["height_gain_points_active"] is True


def test_height_gain_points_above_max_returns_last_scale() -> None:
    """Height above highest point returns last scale."""
    config = AlignDescendConfig(
        height_gain_enabled=True,
        height_gain_mode="points",
        height_scale_points=[
            {"altitude_m": 3.5, "scale": 0.55},
            {"altitude_m": 5.0, "scale": 0.55},
        ],
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        config,
        altitude_m=6.0,
    )
    assert detail["height_gain_scale"] == pytest.approx(0.55)


def test_height_gain_points_interpolates_linearly() -> None:
    """Height between two points linearly interpolates scale."""
    config = AlignDescendConfig(
        height_gain_enabled=True,
        height_gain_mode="points",
        height_scale_points=[
            {"altitude_m": 1.3, "scale": 0.45},
            {"altitude_m": 2.4, "scale": 0.80},
        ],
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        config,
        altitude_m=1.85,
    )
    # t = (1.85-1.3)/(2.4-1.3) = 0.5 → 0.45 + 0.5*(0.80-0.45) = 0.625
    assert detail["height_gain_scale"] == pytest.approx(0.625)


def test_height_gain_points_affects_vx_vy() -> None:
    """Same raw error, higher altitude with higher scale produces larger vx/vy."""
    points = [
        {"altitude_m": 0.8, "scale": 0.40},
        {"altitude_m": 2.4, "scale": 0.80},
    ]
    config_low = AlignDescendConfig(
        height_gain_enabled=True, height_gain_mode="points", height_scale_points=points,
        kp_vx=0.8, kp_vy=0.8,
    )
    config_high = AlignDescendConfig(
        height_gain_enabled=True, height_gain_mode="points", height_scale_points=points,
        kp_vx=0.8, kp_vy=0.8,
    )

    cmd_low, _ = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2), config_low, altitude_m=0.8,
    )
    cmd_high, _ = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2), config_high, altitude_m=2.4,
    )

    # scale 0.80 > 0.40 → velocities at 2.4m should be larger magnitude
    assert abs(cmd_high["vx_cmd"]) > abs(cmd_low["vx_cmd"])
    assert abs(cmd_high["vy_cmd"]) > abs(cmd_low["vy_cmd"])


def test_height_gain_points_scales_max_velocity() -> None:
    """scale_max_velocity_with_height=true: max_vx_eff/max_vy_eff also scaled."""
    config = AlignDescendConfig(
        height_gain_enabled=True,
        height_gain_mode="points",
        height_scale_points=[
            {"altitude_m": 0.8, "scale": 0.40},
            {"altitude_m": 2.4, "scale": 0.80},
        ],
        max_vx_mps=0.4,
        max_vy_mps=0.4,
        scale_max_velocity_with_height=True,
    )
    _, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        config,
        altitude_m=2.4,
    )
    assert detail["max_vx_eff"] == pytest.approx(0.4 * 0.80)
    assert detail["max_vy_eff"] == pytest.approx(0.4 * 0.80)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"height_gain_mode": "invalid"},
        {"height_gain_mode": "points", "height_scale_points": None},
        {"height_gain_mode": "points", "height_scale_points": []},
        {"height_gain_mode": "points", "height_scale_points": [{"altitude_m": 1.0, "scale": 1.0}]},
        {"height_gain_mode": "points", "height_scale_points": [
            {"altitude_m": 0.0, "scale": 0.5},
            {"altitude_m": 1.0, "scale": 0.5},
        ]},
        {"height_gain_mode": "points", "height_scale_points": [
            {"altitude_m": -1.0, "scale": 0.5},
            {"altitude_m": 1.0, "scale": 0.5},
        ]},
        {"height_gain_mode": "points", "height_scale_points": [
            {"altitude_m": 1.0, "scale": 0.0},
            {"altitude_m": 2.0, "scale": 1.0},
        ]},
        {"height_gain_mode": "points", "height_scale_points": [
            {"altitude_m": 1.0, "scale": -0.1},
            {"altitude_m": 2.0, "scale": 1.0},
        ]},
        {"height_gain_mode": "points", "height_scale_points": [
            {"altitude_m": 1.0, "scale": 1.6},
            {"altitude_m": 2.0, "scale": 1.0},
        ]},
        {"height_gain_mode": "points", "height_scale_points": [
            {"altitude_m": 1.0, "scale": 0.5},
            {"altitude_m": 1.0, "scale": 0.8},
        ]},
    ],
)
def test_height_gain_points_rejects_invalid_config(kwargs) -> None:
    with pytest.raises(ValueError):
        AlignDescendConfig(**kwargs)


# ── descent gate policy tests ──────────────────────────────────────────


def test_default_policy_holds_when_not_aligned() -> None:
    """Default descent_gate_policy='aligned_or_slow': vz=0 when not aligned and not slow-descend."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.5, ey_cam=0.02),
        AlignDescendConfig(
            descent_gate_policy="aligned_or_slow",
            max_ex_cam=0.06,
            max_ey_cam=0.06,
            descend_speed_mps=0.3,
        ),
    )

    assert detail["aligned"] is False
    assert detail["slow_descending"] is False
    assert detail["hold_reason"] == "aligning"
    assert command["vz_cmd"] == pytest.approx(0.0)
    # vx/vy still active
    assert command["vx_cmd"] != pytest.approx(0.0)
    assert command["vy_cmd"] != pytest.approx(0.0)


def test_allow_unaligned_descends_when_not_aligned() -> None:
    """descent_gate_policy='allow_unaligned': vz=unaligned_descend_speed_mps even when not aligned."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.5, ey_cam=0.02),
        AlignDescendConfig(
            descent_gate_policy="allow_unaligned",
            unaligned_descend_speed_mps=0.06,
            max_ex_cam=0.06,
            max_ey_cam=0.06,
            slow_descend_speed_mps=0.0,
        ),
    )

    assert detail["aligned"] is False
    assert detail["hold_reason"] == "descending_unaligned"
    assert command["vz_cmd"] == pytest.approx(0.06)
    # vx/vy still apply horizontal correction
    assert command["vx_cmd"] != pytest.approx(0.0)
    assert command["vy_cmd"] != pytest.approx(0.0)


def test_allow_unaligned_zero_speed_is_noop() -> None:
    """When unaligned_descend_speed_mps=0, allow_unaligned falls back to aligning (safe no-op)."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.5, ey_cam=0.02),
        AlignDescendConfig(
            descent_gate_policy="allow_unaligned",
            unaligned_descend_speed_mps=0.0,
            max_ex_cam=0.06,
            max_ey_cam=0.06,
        ),
    )

    assert detail["aligned"] is False
    assert detail["hold_reason"] == "aligning"
    assert command["vz_cmd"] == pytest.approx(0.0)


def test_allow_unaligned_aligned_still_uses_full_descend() -> None:
    """When aligned, descent_gate_policy='allow_unaligned' still uses full descend_speed_mps."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        AlignDescendConfig(
            descent_gate_policy="allow_unaligned",
            unaligned_descend_speed_mps=0.06,
            max_ex_cam=0.06,
            max_ey_cam=0.06,
            descend_speed_mps=0.3,
        ),
    )

    assert detail["aligned"] is True
    assert detail["hold_reason"] == "descending"
    assert command["vz_cmd"] == pytest.approx(0.3)
