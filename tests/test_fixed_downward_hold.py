from __future__ import annotations

import pytest

from missions.common.control.types import MissionStageInput
from missions.rescue_competition.stages.fixed_downward_hold import (
    FixedDownwardHoldMode,
)


def _inputs(**overrides) -> MissionStageInput:
    data = dict(
        timestamp=1.0,
        dt=0.02,
        target_valid=True,
        target_locked=True,
        vision_valid=True,
        drone_valid=True,
        control_allowed=True,
        ex_cam=0.06,
        ey_cam=0.05,
        vision_age_s=0.01,
        drone_age_s=0.01,
    )
    data.update(overrides)
    return MissionStageInput(**data)


def test_fixed_downward_hold_maps_camera_errors_without_gimbal_commands() -> None:
    command, status = FixedDownwardHoldMode().update(_inputs())

    assert status.mode_name == "FIXED_DOWNWARD_HOLD"
    assert status.detail["fixed_downward_camera"] is True
    assert status.detail["body_yaw_control"] is False
    assert command.vy_cmd == pytest.approx(0.06)
    assert command.vx_cmd == pytest.approx(-0.05)
    assert command.vz_cmd == pytest.approx(0.0)
    assert command.yaw_rate_cmd == pytest.approx(0.0)
    assert command.enable_body is True
    assert command.enable_approach is True
    assert command.enable_gimbal is False
    assert command.enable_gimbal_angle is False
    assert command.gimbal_yaw_rate_cmd == pytest.approx(0.0)
    assert command.gimbal_pitch_rate_cmd == pytest.approx(0.0)


def test_fixed_downward_hold_does_not_require_gimbal_feedback() -> None:
    command, status = FixedDownwardHoldMode().update(
        _inputs(gimbal_valid=False, gimbal_age_s=float("inf"))
    )

    assert status.hold_reason == ""
    assert command.active is True


def test_fixed_downward_hold_zeroes_when_target_is_invalid() -> None:
    command, status = FixedDownwardHoldMode().update(_inputs(target_valid=False))

    assert status.hold_reason == "no_target"
    assert command.active is False
    assert command.vx_cmd == pytest.approx(0.0)
    assert command.vy_cmd == pytest.approx(0.0)
