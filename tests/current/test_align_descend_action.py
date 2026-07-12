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
    assert config.kp_vx == pytest.approx(0.4)
    assert config.descend_speed_mps == pytest.approx(0.2)
    assert config.yaw_control_mode == "hold"


def test_local_ned_source_prefers_explicit_local_altitude_and_reports_diagnostics() -> None:
    action = AlignDescendAction()
    action.start({"config": {"altitude_source": "local_ned"}})
    result = action.update(_active_context(
        local_altitude_m=1.30, local_altitude_valid=True, relative_altitude=1.85,
    ))
    assert result.detail["current_altitude_m"] == pytest.approx(1.30)
    assert result.detail["altitude_source"] == "local_position_ned_z"
    assert result.detail["local_altitude_m"] == pytest.approx(1.30)
    assert result.detail["relative_altitude_m"] == pytest.approx(1.85)
    assert result.detail["altitude_difference_m"] == pytest.approx(0.55)


def test_local_ned_source_never_falls_back_to_relative_altitude() -> None:
    action = AlignDescendAction()
    action.start({"config": {"altitude_source": "local_ned"}})
    result = action.update(_active_context(relative_altitude=1.2))
    assert result.failed and result.reason == "missing_local_ned_altitude"


def test_continue_descent_fails_when_control_is_not_allowed() -> None:
    action = AlignDescendAction()
    action.start({
        "config": {
            "target_loss_policy": "continue_descent",
            "target_loss_descend_speed_mps": 0.3,
        },
    })

    result = action.update(_active_context(control_allowed=False))

    assert result.failed
    assert result.reason == "control_not_allowed"


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
    assert command["vx_cmd"] == pytest.approx(-0.08)
    assert command["vy_cmd"] == pytest.approx(0.04)
    assert command["vz_cmd"] == pytest.approx(0.0)


def test_height_gain_disabled_by_default_keeps_existing_behavior() -> None:
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.1, ey_cam=0.2),
        AlignDescendConfig(),
        altitude_m=3.0,
    )

    assert command["vx_cmd"] == pytest.approx(-0.08)
    assert command["vy_cmd"] == pytest.approx(0.04)
    assert detail["height_gain_scale"] == pytest.approx(1.0)
    assert detail["kp_vx_eff"] == pytest.approx(0.4)
    assert detail["kp_vy_eff"] == pytest.approx(0.4)
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
    assert command["vx_cmd"] == pytest.approx(-0.08)
    assert command["vy_cmd"] == pytest.approx(0.04)


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


def test_hold_zero_rate_never_captures_or_emits_yaw() -> None:
    action = AlignDescendAction()
    action.start({"config": {"yaw_control_mode": "hold_zero_rate"}})
    result = action.update(
        _active_context(
            field_heading_yaw_rad=-1.0,
            arm_heading_yaw_rad=2.0,
            vehicle={"attitude_valid": True, "yaw": 3.13},
        )
    )
    assert result.detail["yaw_hold_rad"] is None
    assert "yaw_hold_rad" not in result.detail["command"]
    assert result.detail["command"]["yaw_rate_rad_s"] == pytest.approx(0.0)


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
    assert command["vx_cmd"] == pytest.approx(-0.08)
    assert command["vy_cmd"] == pytest.approx(0.04)
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


# ── staged descent speed tests ────────────────────────────────────────

def _staged_config(**stages):
    """Helper to create a config with descent_speed_stages."""
    params = {
        "descend_speed_mps": 0.20,
        "slow_descend_speed_mps": 0.10,
        "descent_speed_stages": [
            {"max_altitude_m": 1.80, "max_descend_speed_mps": 0.10},
            {"max_altitude_m": 1.50, "max_descend_speed_mps": 0.05},
            {"max_altitude_m": 1.35, "max_descend_speed_mps": 0.02},
        ],
        "max_ex_cam": 0.2,
        "max_ey_cam": 0.2,
    }
    for k, v in stages.items():
        if k == "stages":
            params["descent_speed_stages"] = v
        else:
            params[k] = v
    return AlignDescendConfig(**params)


def test_staged_descent_high_altitude_no_cap() -> None:
    """At 2.0m, fully aligned → vz=0.20, stage_active=false."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        _staged_config(),
        altitude_m=2.0,
    )
    assert detail["aligned"] is True
    assert command["vz_cmd"] == pytest.approx(0.20)
    assert detail["descent_speed_stage_active"] is False
    assert detail["descent_speed_before_stage_mps"] == pytest.approx(0.20)
    assert detail["descent_speed_after_stage_mps"] == pytest.approx(0.20)


def test_staged_descent_first_stage_cap() -> None:
    """At 1.70m, fully aligned → vz=0.10, active stage=1.80."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        _staged_config(),
        altitude_m=1.70,
    )
    assert detail["aligned"] is True
    assert command["vz_cmd"] == pytest.approx(0.10)
    assert detail["descent_speed_stage_active"] is True
    assert detail["descent_speed_stage_max_altitude_m"] == pytest.approx(1.80)
    assert detail["descent_speed_cap_mps"] == pytest.approx(0.10)


def test_staged_descent_second_stage_cap() -> None:
    """At 1.45m, fully aligned → vz=0.05, active stage=1.50."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        _staged_config(),
        altitude_m=1.45,
    )
    assert detail["aligned"] is True
    assert command["vz_cmd"] == pytest.approx(0.05)
    assert detail["descent_speed_stage_active"] is True
    assert detail["descent_speed_stage_max_altitude_m"] == pytest.approx(1.50)
    assert detail["descent_speed_cap_mps"] == pytest.approx(0.05)


def test_staged_descent_final_stage_cap() -> None:
    """At 1.33m, fully aligned, above finish → vz=0.02, active stage=1.35."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        _staged_config(),
        altitude_m=1.33,
    )
    assert detail["aligned"] is True
    assert command["vz_cmd"] == pytest.approx(0.02)
    assert detail["descent_speed_stage_active"] is True
    assert detail["descent_speed_stage_max_altitude_m"] == pytest.approx(1.35)
    assert detail["descent_speed_cap_mps"] == pytest.approx(0.02)


def test_staged_descent_not_aligned_no_cap_when_vz_zero() -> None:
    """When not aligned (vz=0), stages must not force descent."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.5, ey_cam=0.5),
        _staged_config(),
        altitude_m=1.45,
    )
    assert detail["aligned"] is False
    assert command["vz_cmd"] == pytest.approx(0.0)
    assert detail["descent_speed_stage_active"] is False


def test_staged_descent_slow_descend_branch() -> None:
    """Slow-descend vz=0.10 at 1.45m → capped to 0.05."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.30, ey_cam=0.30),
        _staged_config(
            descend_speed_mps=0.20,
            slow_descend_speed_mps=0.10,
            slow_descend_max_ex_cam=0.45,
            slow_descend_max_ey_cam=0.45,
        ),
        altitude_m=1.45,
    )
    assert detail["aligned"] is False
    assert detail["slow_descending"] is True
    assert command["vz_cmd"] == pytest.approx(0.05)
    assert detail["descent_speed_stage_active"] is True


def test_staged_descent_default_no_stages_unchanged() -> None:
    """Without descent_speed_stages, existing behavior is unchanged."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        AlignDescendConfig(descend_speed_mps=0.20, max_ex_cam=0.2, max_ey_cam=0.2),
        altitude_m=1.45,
    )
    assert detail["aligned"] is True
    assert command["vz_cmd"] == pytest.approx(0.20)
    assert detail["descent_speed_stage_active"] is False


def test_staged_descent_two_stages_min_speed_wins() -> None:
    """When two stages apply at same height, the smaller cap wins."""
    command, detail = compute_align_descend_command(
        _valid_inputs(ex_cam=0.02, ey_cam=0.02),
        _staged_config(stages=[
            {"max_altitude_m": 1.80, "max_descend_speed_mps": 0.10},
            {"max_altitude_m": 1.60, "max_descend_speed_mps": 0.03},
        ]),
        altitude_m=1.50,
    )
    assert command["vz_cmd"] == pytest.approx(0.03)
    assert detail["descent_speed_cap_mps"] == pytest.approx(0.03)


@pytest.mark.parametrize("kwargs,error_match", [
    ({"descent_speed_stages": "not_a_list"}, "must be a list"),
    ({"descent_speed_stages": [{"max_altitude_m": -1.0, "max_descend_speed_mps": 0.1}]}, "must be finite and > 0"),
    ({"descent_speed_stages": [{"max_altitude_m": 1.5, "max_descend_speed_mps": -0.1}]}, "must be finite and >= 0"),
    ({"descent_speed_stages": [{"max_altitude_m": float("nan"), "max_descend_speed_mps": 0.1}]}, "must be finite"),
    ({"descent_speed_stages": [{"max_altitude_m": 1.5, "max_descend_speed_mps": float("inf")}]}, "must be finite"),
    ({"descent_speed_stages": [{"max_altitude_m": True, "max_descend_speed_mps": 0.1}]}, "must not be boolean"),
    ({"descent_speed_stages": [{"max_altitude_m": 1.5, "max_descend_speed_mps": False}]}, "must not be boolean"),
    ({"descent_speed_stages": [{}]}, "must be finite"),  # missing keys → nan
    ({"descent_speed_stages": [1, 2, 3]}, "must be a dict"),
])
def test_staged_descent_rejects_invalid_config(kwargs, error_match) -> None:
    with pytest.raises(ValueError, match=error_match):
        AlignDescendConfig(**kwargs)


# ══════════════════════════════════════════════════════════════════════
# latched_center_alignment tests
# ══════════════════════════════════════════════════════════════════════

import math as _math
from missions.common.actions import align_descend as _ad


def _mk_cd(**overrides):
    """Build a mock command_detail dict for compute_align_descend_command."""
    d = {
        "enabled": True,
        "aligned": True,
        "slow_descending": False,
        "hold_reason": "",
        "ex_cam": 0.0,
        "ey_cam": 0.0,
        "raw_ex_cam": 0.0,
        "raw_ey_cam": 0.0,
        "desired_ex_cam": 0.0,
        "desired_ey_cam": 0.0,
        "corrected_ex_cam": 0.0,
        "corrected_ey_cam": 0.0,
        "payload_offset_enabled": False,
        "payload_offset_valid": False,
        "height_gain_scale": 1.0,
        "kp_vx_eff": 0.4,
        "kp_vy_eff": 0.4,
        "max_vx_eff": 0.4,
        "max_vy_eff": 0.4,
    }
    d.update(overrides)
    return d


def _mk_lc_ctx(altitude=1.15, target_valid=True):
    """Minimal context for latched_center_alignment tests."""
    return {
        "drone": {"relative_altitude": altitude},
        "target_valid": target_valid,
        "target_locked": True,
        "control_allowed": True,
    }


def _start_lc_action(monkeypatch, command_detail_overrides=None, **start_overrides):
    """Start AlignDescendAction with latched_center_alignment and patched compute."""
    overrides = command_detail_overrides or {}
    def _mock_compute(inputs, config, altitude_m=None):
        cd = _mk_cd(**overrides)
        # Derive 'enabled' from inputs to match real behaviour (target_ok gate)
        cd["enabled"] = bool(inputs.get("target_valid") or inputs.get("vision_valid"))
        return {}, cd
    monkeypatch.setattr(_ad, "compute_align_descend_command", _mock_compute)
    params = {
        "config": {"require_target_locked": False},
        "finish_policy": "latched_center_alignment",
        "finish_altitude_m": 1.2,
        "finish_alignment_max_ex_cam": 0.20,
        "finish_alignment_max_ey_cam": 0.20,
        "finish_alignment_hold_updates": 2,
        "max_updates": 30,
    }
    params.update(start_overrides)
    action = AlignDescendAction()
    action.start(params)
    return action


def test_lc_target_invalid_clears_hold_count_and_no_done(monkeypatch) -> None:
    """final_align with target_valid=False → hold_count=0, never done on centre."""
    action = _start_lc_action(monkeypatch)
    ctx = _mk_lc_ctx(altitude=1.15, target_valid=False)
    r = action.update(ctx)
    # After first update, final_align should be latched, hold_count stays 0
    assert not r.done
    assert action.finish_alignment_hold_count == 0
    assert action.final_align_started is True
    # A few more updates: still not done
    for _ in range(3):
        r = action.update(ctx)
    assert not r.done
    assert action.finish_alignment_hold_count == 0


def test_lc_target_lost_timeout(monkeypatch) -> None:
    """final_align with sustained target loss → target_lost_timeout failure."""
    action = _start_lc_action(monkeypatch,
                                  start_overrides={"lost_timeout_updates": 3, "max_retries": 0})
    ctx = _mk_lc_ctx(altitude=1.15, target_valid=False)
    for _ in range(20):
        r = action.update(ctx)
        if r.failed:
            break
    assert r.failed
    assert r.reason == "target_lost_timeout"


def test_lc_target_lost_once_resets_hold_count(monkeypatch) -> None:
    """One frame of target loss resets hold_count to 0."""
    action = _start_lc_action(monkeypatch,
                                  start_overrides={"lost_timeout_updates": 99})
    ctx_ok = _mk_lc_ctx(altitude=1.15, target_valid=True)
    # One good update → hold_count=1 (not yet done, need 2)
    action.update(ctx_ok)
    assert action.final_align_started is True
    assert action.finish_alignment_hold_count == 1
    # One bad update → hold_count reset
    ctx_bad = _mk_lc_ctx(altitude=1.15, target_valid=False)
    action.update(ctx_bad)
    assert action.finish_alignment_hold_count == 0


def test_lc_target_recovered_needs_two_consecutive_again(monkeypatch) -> None:
    """After target recovery, must accumulate 2 consecutive again to done."""
    action = _start_lc_action(monkeypatch,
                                  start_overrides={"lost_timeout_updates": 99})
    ctx_ok = _mk_lc_ctx(altitude=1.15, target_valid=True)
    ctx_bad = _mk_lc_ctx(altitude=1.15, target_valid=False)
    action.update(ctx_ok)
    assert action.finish_alignment_hold_count == 1
    action.update(ctx_bad)
    assert action.finish_alignment_hold_count == 0
    for _ in range(4):
        r = action.update(ctx_ok)
        if r.done:
            break
    assert r.done
    assert r.reason == "latched_center_aligned"


def test_lc_corrected_nan_not_done(monkeypatch) -> None:
    """corrected_ex_cam = NaN → in_center is False, never done."""
    cd = _mk_cd(corrected_ex_cam=float("nan"), corrected_ey_cam=0.0)
    action = _start_lc_action(monkeypatch, command_detail_overrides={
        "corrected_ex_cam": float("nan"), "corrected_ey_cam": 0.0,
    }, start_overrides={"max_updates": 10, "lost_timeout_updates": 99})
    ctx = _mk_lc_ctx(altitude=1.15, target_valid=True)
    for _ in range(10):
        r = action.update(ctx)
    assert not r.done
    assert action.finish_alignment_hold_count == 0


def test_lc_raw_irrelevant_only_corrected_matters(monkeypatch) -> None:
    """raw ex/ey in centre but corrected ex/ey out → no done (no raw fallback)."""
    action = _start_lc_action(monkeypatch, command_detail_overrides={
        "ex_cam": 0.0, "ey_cam": 0.0,
        "raw_ex_cam": 0.0, "raw_ey_cam": 0.0,
        "corrected_ex_cam": 0.30, "corrected_ey_cam": 0.30,
    }, start_overrides={"max_updates": 10, "lost_timeout_updates": 99})
    ctx = _mk_lc_ctx(altitude=1.15, target_valid=True)
    for _ in range(10):
        r = action.update(ctx)
    assert not r.done
    assert action.finish_alignment_hold_count == 0


def test_lc_corrected_in_center_two_consecutive_done(monkeypatch) -> None:
    """corrected in centre + target_ok=True → 2 consecutive → done."""
    action = _start_lc_action(monkeypatch, command_detail_overrides={
        "corrected_ex_cam": 0.05, "corrected_ey_cam": -0.03,
    })
    ctx = _mk_lc_ctx(altitude=1.15, target_valid=True)
    for _ in range(5):
        r = action.update(ctx)
        if r.done:
            break
    assert r.done
    assert r.reason == "latched_center_aligned"


# ══════════════════════════════════════════════════════════════════════
# latched_center_alignment parameter validation
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad_value,error_match", [
    (float("nan"), "finish_alignment_max_ex_cam must be finite"),
    (float("inf"), "finish_alignment_max_ex_cam must be finite"),
    (-1.0, "finish_alignment_max_ex_cam must be finite"),
    (0.0, "finish_alignment_max_ex_cam must be finite"),
])
def test_lc_rejects_invalid_max_ex_cam(bad_value, error_match) -> None:
    with pytest.raises(ValueError, match=error_match):
        AlignDescendAction().start({
            "config": {"require_target_locked": False},
            "finish_policy": "latched_center_alignment",
            "finish_altitude_m": 1.2,
            "finish_alignment_max_ex_cam": bad_value,
            "finish_alignment_max_ey_cam": 0.20,
            "finish_alignment_hold_updates": 2,
        })


@pytest.mark.parametrize("bad_value,error_match", [
    (float("nan"), "finish_alignment_max_ey_cam must be finite"),
    (float("inf"), "finish_alignment_max_ey_cam must be finite"),
    (-1.0, "finish_alignment_max_ey_cam must be finite"),
    (0.0, "finish_alignment_max_ey_cam must be finite"),
])
def test_lc_rejects_invalid_max_ey_cam(bad_value, error_match) -> None:
    with pytest.raises(ValueError, match=error_match):
        AlignDescendAction().start({
            "config": {"require_target_locked": False},
            "finish_policy": "latched_center_alignment",
            "finish_altitude_m": 1.2,
            "finish_alignment_max_ex_cam": 0.20,
            "finish_alignment_max_ey_cam": bad_value,
            "finish_alignment_hold_updates": 2,
        })


@pytest.mark.parametrize("bad_value,error_match", [
    (0, "finish_alignment_hold_updates must be an integer >= 1"),
    (-1, "finish_alignment_hold_updates must be an integer >= 1"),
    (1.5, "finish_alignment_hold_updates must be an integer >= 1"),
    (2.0, "finish_alignment_hold_updates must be an integer >= 1"),
    (True, "finish_alignment_hold_updates must be an integer >= 1"),
    (False, "finish_alignment_hold_updates must be an integer >= 1"),
    ("2", "finish_alignment_hold_updates must be an integer >= 1"),
])
def test_lc_rejects_invalid_hold_updates(bad_value, error_match) -> None:
    with pytest.raises(ValueError, match=error_match):
        AlignDescendAction().start({
            "config": {"require_target_locked": False},
            "finish_policy": "latched_center_alignment",
            "finish_altitude_m": 1.2,
            "finish_alignment_max_ex_cam": 0.20,
            "finish_alignment_max_ey_cam": 0.20,
            "finish_alignment_hold_updates": bad_value,
        })


@pytest.mark.parametrize("good_value", [1, 2])
def test_lc_accepts_valid_hold_updates(good_value) -> None:
    """Valid int >= 1 is accepted without error."""
    action = AlignDescendAction()
    action.start({
        "config": {"require_target_locked": False},
        "finish_policy": "latched_center_alignment",
        "finish_altitude_m": 1.2,
        "finish_alignment_max_ex_cam": 0.20,
        "finish_alignment_max_ey_cam": 0.20,
        "finish_alignment_hold_updates": good_value,
    })
    assert action.finish_alignment_hold_updates == good_value


# ══════════════════════════════════════════════════════════════════════
# NaN / inf visual error rejection (real compute_align_descend_command)
# ══════════════════════════════════════════════════════════════════════

import math as _math2
from missions.common.actions.align_descend import (
    compute_align_descend_command,
    AlignDescendConfig,
)

@pytest.mark.parametrize("bad_value,label", [
    (float("nan"), "NaN"),
    (float("inf"), "+inf"),
    (float("-inf"), "-inf"),
])
def test_nan_inf_ex_cam_disabled(bad_value, label) -> None:
    """ex_cam=NaN/inf → enabled=False, vx/vy/vz=0."""
    config = AlignDescendConfig()
    inputs = {"target_valid": True, "target_locked": True,
              "control_allowed": True, "ex_cam": bad_value, "ey_cam": 0.02}
    command, detail = compute_align_descend_command(inputs, config)
    assert detail["enabled"] is False, f"ex_cam={label}: expected enabled=False"
    assert detail["hold_reason"] == "invalid_error"
    assert command["vx_cmd"] == 0.0
    assert command["vy_cmd"] == 0.0
    assert command["vz_cmd"] == 0.0
    assert _math2.isfinite(command["vx_cmd"])
    assert _math2.isfinite(command["vy_cmd"])
    assert _math2.isfinite(command["vz_cmd"])


@pytest.mark.parametrize("bad_value,label", [
    (float("nan"), "NaN"),
    (float("inf"), "+inf"),
    (float("-inf"), "-inf"),
])
def test_nan_inf_ey_cam_disabled(bad_value, label) -> None:
    """ey_cam=NaN/inf → enabled=False, vx/vy/vz=0."""
    config = AlignDescendConfig()
    inputs = {"target_valid": True, "target_locked": True,
              "control_allowed": True, "ex_cam": 0.02, "ey_cam": bad_value}
    command, detail = compute_align_descend_command(inputs, config)
    assert detail["enabled"] is False
    assert detail["hold_reason"] == "invalid_error"
    assert command["vx_cmd"] == 0.0
    assert command["vy_cmd"] == 0.0
    assert command["vz_cmd"] == 0.0


def test_real_action_nan_error_clears_hold_count_and_no_done(monkeypatch) -> None:
    """Real AlignDescendAction with NaN ex_cam → target_ok=False, hold_count=0, never done."""
    action = AlignDescendAction()
    action.start({
        "config": {"require_target_locked": False},
        "finish_policy": "latched_center_alignment",
        "finish_altitude_m": 1.2,
        "finish_alignment_max_ex_cam": 0.20,
        "finish_alignment_max_ey_cam": 0.20,
        "finish_alignment_hold_updates": 2,
        "max_updates": 10,
        "lost_timeout_updates": 99,
    })
    ctx = {
        "drone": {"relative_altitude": 1.15},
        "target_valid": True,
        "target_locked": True,
        "control_allowed": True,
        "ex_cam": float("nan"),
        "ey_cam": 0.02,
    }
    for _ in range(10):
        r = action.update(ctx)
    assert not r.done
    assert action.finish_alignment_hold_count == 0


def test_real_action_nan_error_continuous_triggers_target_lost_timeout() -> None:
    """Continuous NaN ex_cam → lost_updates accumulate → target_lost_timeout."""
    action = AlignDescendAction()
    action.start({
        "config": {"require_target_locked": False},
        "finish_policy": "latched_center_alignment",
        "finish_altitude_m": 1.2,
        "lost_timeout_updates": 3,
        "max_retries": 0,
        "max_updates": 20,
        "finish_alignment_max_ex_cam": 0.20,
        "finish_alignment_max_ey_cam": 0.20,
        "finish_alignment_hold_updates": 2,
    })
    ctx = {
        "drone": {"relative_altitude": 1.15},
        "target_valid": True,
        "target_locked": True,
        "control_allowed": True,
        "ex_cam": float("nan"),
        "ey_cam": 0.02,
    }
    for _ in range(20):
        r = action.update(ctx)
        if r.failed:
            break
    assert r.failed
    assert r.reason == "target_lost_timeout"


def _low_altitude_integral_config(**overrides):
    config = {
        "require_target_locked": False,
        "min_altitude_m": 0.3,
        "integral_enabled": True,
        "integral_active_below_altitude_m": 1.6,
        "ki_vx": 0.04,
        "ki_vy": 0.04,
        "integral_vx_limit_mps": 0.03,
        "integral_vy_limit_mps": 0.03,
    }
    config.update(overrides)
    return config


def test_low_altitude_integral_uses_monotonic_time_and_resets_on_deadband(monkeypatch) -> None:
    clock = iter((100.0, 100.5, 101.0))
    monkeypatch.setattr("missions.common.actions.align_descend.time.monotonic", lambda: next(clock))
    action = AlignDescendAction()
    action.start({"config": _low_altitude_integral_config()})
    context = _active_context(ex_cam=0.2, ey_cam=0.2)
    context["drone"] = {"relative_altitude": 1.5}
    first = action.update(context)
    second = action.update(context)
    assert first.detail["integral_active"] is True
    assert second.detail["integral_dt_s"] == pytest.approx(0.5)
    assert abs(second.detail["integral_vx_mps"]) > abs(first.detail["integral_vx_mps"])
    assert abs(second.detail["integral_vx_mps"]) <= 0.03
    context["ey_cam"] = 0.01
    reset = action.update(context)
    assert reset.detail["integral_vx_mps"] == pytest.approx(0.0)
    assert reset.detail["integral_reset_reason"] == "ey_deadband"


def test_integral_is_inactive_above_configured_altitude() -> None:
    action = AlignDescendAction()
    action.start({"config": _low_altitude_integral_config()})
    context = _active_context(ex_cam=0.2, ey_cam=0.2)
    context["drone"] = {"relative_altitude": 2.0}
    result = action.update(context)
    assert result.detail["integral_active"] is False
    assert result.detail["integral_vx_mps"] == pytest.approx(0.0)


def test_min_effective_speed_is_low_altitude_direction_preserving_and_limited() -> None:
    config = AlignDescendConfig(
        kp_vx=0.1, kp_vy=0.1, max_vx_mps=0.04, max_vy_mps=0.04,
        min_effective_speed_enabled=True,
        min_effective_speed_active_below_altitude_m=1.6,
        min_effective_speed_mps=0.035,
        min_effective_speed_ex_threshold=0.12,
        min_effective_speed_ey_threshold=0.16,
    )
    command, detail = compute_align_descend_command(_valid_inputs(ex_cam=0.2, ey_cam=-0.2), config, altitude_m=1.5)
    assert command["vx_cmd"] == pytest.approx(0.035)
    assert command["vy_cmd"] == pytest.approx(0.035)
    assert detail["min_effective_speed_applied_vx"] is True
    high_command, high_detail = compute_align_descend_command(_valid_inputs(ex_cam=0.2, ey_cam=-0.2), config, altitude_m=2.0)
    assert high_command["vx_cmd"] == pytest.approx(0.02)
    assert high_detail["min_effective_speed_active"] is False


def test_one_target_loss_update_keeps_scaled_horizontal_command_then_stops(monkeypatch) -> None:
    clock = iter((10.0, 10.1, 10.2))
    monkeypatch.setattr("missions.common.actions.align_descend.time.monotonic", lambda: next(clock))
    action = AlignDescendAction()
    action.start({"config": {
        **_low_altitude_integral_config(),
        "target_loss_grace_updates": 1,
        "target_loss_grace_horizontal_scale": 0.5,
    }, "lost_timeout_updates": 1, "max_retries": 0})
    good = _active_context(ex_cam=0.2, ey_cam=0.2)
    good["drone"] = {"relative_altitude": 1.5}
    active = action.update(good)
    lost = action.update({"drone": {"relative_altitude": 1.5}, "target_valid": False, "control_allowed": True})
    assert lost.reason == "target_loss_grace"
    assert lost.detail["command"]["valid"] is True
    assert lost.detail["command"]["active"] is True
    assert lost.detail["command"]["vz_cmd"] == pytest.approx(0.0)
    assert lost.detail["command"]["vx_cmd"] == pytest.approx(active.detail["command"]["vx_cmd"] * 0.5)
    stopped = action.update({"drone": {"relative_altitude": 1.5}, "target_valid": False, "control_allowed": True})
    assert stopped.failed
    assert stopped.reason == "target_lost_timeout"
