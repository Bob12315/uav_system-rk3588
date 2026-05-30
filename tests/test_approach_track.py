from __future__ import annotations

import pytest

from missions.visual_tracking.stages.approach_track import ApproachTrackMode
from missions.visual_tracking.stages.approach_track.body import ApproachBodyController
from missions.visual_tracking.stages.approach_track.gimbal import ApproachGimbalController
from missions.visual_tracking.stages.approach_track.config import (
    ApproachBodyConfig,
    ApproachForwardConfig,
    ApproachGimbalConfig,
    ApproachTrackConfig,
)
from missions.common.control.types import MissionStageInput


def _inputs(**overrides) -> MissionStageInput:
    data = dict(
        timestamp=1.0,
        dt=0.02,
        fused_valid=True,
        target_valid=True,
        target_locked=True,
        vision_valid=True,
        drone_valid=True,
        gimbal_valid=True,
        control_allowed=True,
        track_id=1,
        track_switched=False,
        target_stable=True,
        ex_cam=0.06,
        ey_cam=-0.05,
        ex_body=0.04,
        gimbal_yaw=0.1,
        gimbal_pitch=-1.0,
        target_size=0.2,
        target_size_valid=True,
        vision_age_s=0.01,
        drone_age_s=0.01,
        gimbal_age_s=0.01,
    )
    data.update(overrides)
    return MissionStageInput(**data)


def test_approach_track_maps_errors_to_raw_command() -> None:
    mode = ApproachTrackMode(config=ApproachTrackConfig(yaw_align_hold_s=0.0))

    command, status = mode.update(_inputs(target_size=0.1))

    assert status.mode_name == "APPROACHING"
    assert command.gimbal_yaw_rate_cmd == pytest.approx(0.300024)
    assert command.gimbal_pitch_rate_cmd == pytest.approx(0.09)
    assert command.vy_cmd == pytest.approx(0.0)
    assert command.yaw_rate_cmd == pytest.approx(0.02)
    assert command.vx_cmd == pytest.approx(0.13333333333333336)


def test_approach_track_holds_forward_until_yaw_alignment_is_stable() -> None:
    mode = ApproachTrackMode()

    first_command, first_status = mode.update(_inputs(timestamp=1.0, gimbal_yaw=0.1, target_size=0.1))
    second_command, second_status = mode.update(_inputs(timestamp=1.5, gimbal_yaw=0.1, target_size=0.1))

    assert first_status.mode_name == "YAW_ALIGNING"
    assert first_command.vx_cmd == pytest.approx(0.0)
    assert first_status.hold_reason == "yaw_aligning"
    assert second_status.mode_name == "APPROACHING"
    assert second_command.vx_cmd > 0.0


def test_body_yaw_uses_image_error_feedforward() -> None:
    mode = ApproachTrackMode(
        config=ApproachTrackConfig(
            body=ApproachBodyConfig(
                kp_yaw=0.0,
                kp_ex_cam_yaw=0.5,
                yaw_rate_damping=0.0,
                max_yaw_rate=1.0,
            )
        )
    )

    command, _ = mode.update(_inputs(ex_cam=0.2, gimbal_yaw=0.0))

    assert command.yaw_rate_cmd == pytest.approx(0.1)


def test_approach_stops_forward_when_image_error_is_too_large() -> None:
    mode = ApproachTrackMode(
        config=ApproachTrackConfig(
            yaw_align_hold_s=0.0,
            approach=ApproachForwardConfig(
                target_size_ref=0.2,
                kp_vx=4.0,
                ex_cam_slowdown_start=0.15,
                max_ex_cam_for_approach=0.35,
            ),
        )
    )

    command, status = mode.update(_inputs(ex_cam=0.4, gimbal_yaw=0.0, target_size=0.1))

    assert status.mode_name == "YAW_ALIGNING"
    assert status.hold_reason == "image_not_centered"
    assert command.vx_cmd == pytest.approx(0.0)


def test_approach_track_zeroes_when_target_invalid() -> None:
    command, status = ApproachTrackMode().update(_inputs(target_valid=False))

    assert command.valid is True
    assert command.active is False
    assert command.vx_cmd == pytest.approx(0.0)
    assert command.gimbal_yaw_rate_cmd == pytest.approx(0.0)
    assert status.hold_reason == "no_target"


def test_body_yaw_rate_damping_brakes_existing_yaw_motion() -> None:
    controller = ApproachBodyController(
        config=ApproachBodyConfig(
            kp_yaw=1.2,
            yaw_rate_damping=0.8,
            deadband_ex_body=0.0,
            deadband_gimbal_yaw=0.0,
        )
    )

    command = controller.update(_inputs(gimbal_yaw=0.1, yaw_rate=0.1))

    assert command.yaw_rate_cmd == pytest.approx(0.04)


def test_body_yaw_step_rate_quantizes_yaw_command() -> None:
    controller = ApproachBodyController(
        config=ApproachBodyConfig(
            kp_yaw=1.2,
            yaw_step_rate=0.05,
            deadband_ex_body=0.0,
            deadband_gimbal_yaw=0.0,
        )
    )

    command = controller.update(_inputs(gimbal_yaw=0.06))

    assert command.yaw_rate_cmd == pytest.approx(0.1)


def test_gimbal_derivative_switch_disables_pitch_derivative() -> None:
    controller = ApproachGimbalController(
        config=ApproachGimbalConfig(
            kp_yaw=0.0,
            kp_pitch=1.0,
            ki_pitch=0.0,
            kd_pitch=10.0,
            use_derivative=False,
            deadband_y=0.0,
            center_hold_pitch_threshold=0.0,
            max_pitch_rate=10.0,
            pitch_sign=-1.0,
        )
    )

    controller.update(_inputs(ey_cam=0.1))
    command = controller.update(_inputs(ey_cam=0.2))

    assert command.pitch_rate_cmd == pytest.approx(-0.2)
