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
