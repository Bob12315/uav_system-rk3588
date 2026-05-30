from __future__ import annotations

import pytest

from missions.common.control.types import MissionStageInput
from missions.visual_tracking.stages.overhead_hold import (
    OverheadBodyConfig,
    OverheadHoldConfig,
    OverheadHoldMode,
)


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
        ex_cam=0.06,
        ey_cam=0.05,
        gimbal_yaw=0.1,
        gimbal_pitch=1.0,
        target_size=0.4,
        target_size_valid=True,
        vision_age_s=0.01,
        drone_age_s=0.01,
        gimbal_age_s=0.01,
    )
    data.update(overrides)
    return MissionStageInput(**data)


def test_overhead_hold_maps_overhead_errors_to_raw_command() -> None:
    command, status = OverheadHoldMode().update(_inputs())

    assert status.mode_name == "OVERHEAD_HOLD"
    assert command.enable_gimbal_angle is True
    assert command.gimbal_pitch_angle_cmd == pytest.approx(-1.5707963267948966)
    assert command.gimbal_yaw_angle_cmd == pytest.approx(0.1)
    assert command.gimbal_pitch_rate_cmd == pytest.approx(0.0)
    assert command.gimbal_yaw_rate_cmd == pytest.approx(0.0)
    assert command.yaw_rate_cmd == pytest.approx(0.0)
    assert command.vy_cmd == pytest.approx(0.06)
    assert command.vx_cmd == pytest.approx(0.05)


def test_overhead_hold_stops_gimbal_after_pitch_reaches_downward() -> None:
    mode = OverheadHoldMode()

    command, status = mode.update(_inputs(gimbal_pitch=-1.5707963267948966))

    assert status.detail["gimbal_pitch_aligned"] is True
    assert command.enable_gimbal is False
    assert command.enable_gimbal_angle is False
    assert command.gimbal_pitch_angle_cmd is None
    assert command.gimbal_pitch_rate_cmd == pytest.approx(0.0)
    assert command.gimbal_yaw_rate_cmd == pytest.approx(0.0)
    assert command.vy_cmd == pytest.approx(0.06)
    assert command.vx_cmd == pytest.approx(0.05)


def test_overhead_hold_never_commands_body_yaw() -> None:
    mode = OverheadHoldMode(
        config=OverheadHoldConfig(body=OverheadBodyConfig(kp_yaw=10.0))
    )

    command, _ = mode.update(_inputs(gimbal_yaw=0.5))

    assert command.yaw_rate_cmd == pytest.approx(0.0)


def test_overhead_hold_zeroes_when_target_invalid() -> None:
    command, status = OverheadHoldMode().update(_inputs(target_valid=False))

    assert command.valid is True
    assert command.active is False
    assert command.vx_cmd == pytest.approx(0.0)
    assert command.vy_cmd == pytest.approx(0.0)
    assert status.hold_reason == "no_target"
