from __future__ import annotations

import math

import pytest

from missions.common.control.command_shaper import CommandShaper, CommandShaperConfig
from missions.common.control.types import FlightCommand


def test_limits_body_and_gimbal_channels() -> None:
    shaper = CommandShaper()
    raw = FlightCommand(
        vx_cmd=99.0,
        vy_cmd=-99.0,
        yaw_rate_cmd=99.0,
        gimbal_yaw_rate_cmd=-99.0,
        gimbal_pitch_rate_cmd=99.0,
        enable_body=True,
        enable_gimbal=True,
        enable_approach=True,
        valid=True,
    )

    shaped = shaper.update(raw, dt=0.0)

    assert shaped.vx_cmd == pytest.approx(shaper.config.max_vx)
    assert shaped.vy_cmd == pytest.approx(-shaper.config.max_vy)
    assert shaped.yaw_rate_cmd == pytest.approx(shaper.config.max_yaw_rate)
    assert shaped.gimbal_yaw_rate_cmd == pytest.approx(-shaper.config.max_gimbal_yaw_rate)
    assert shaped.gimbal_pitch_rate_cmd == pytest.approx(shaper.config.max_gimbal_pitch_rate)


def test_slew_rate_limits_by_dt() -> None:
    shaper = CommandShaper(config=CommandShaperConfig(max_vx_rate=1.0))

    shaped = shaper.update(
        FlightCommand(vx_cmd=1.0, enable_approach=True, valid=True),
        dt=0.02,
    )

    assert shaped.vx_cmd == pytest.approx(0.02)


def test_disabled_channel_smooths_toward_zero() -> None:
    shaper = CommandShaper(config=CommandShaperConfig(max_vx_rate=1.0))
    shaper.update(FlightCommand(vx_cmd=0.1, enable_approach=True, valid=True), dt=0.0)

    shaped = shaper.update(FlightCommand(valid=True), dt=0.02)

    assert shaped.vx_cmd == pytest.approx(0.08)
    assert shaped.enable_approach is False


def test_disabled_channel_can_snap_to_zero() -> None:
    shaper = CommandShaper(
        config=CommandShaperConfig(max_vx_rate=1.0, smooth_to_zero_when_disabled=False)
    )
    shaper.update(FlightCommand(vx_cmd=0.1, enable_approach=True, valid=True), dt=0.0)

    shaped = shaper.update(FlightCommand(valid=True), dt=0.02)

    assert shaped.vx_cmd == pytest.approx(0.0)


def test_non_finite_inputs_are_zeroed() -> None:
    shaper = CommandShaper()
    raw = FlightCommand(
        vx_cmd=math.nan,
        vy_cmd=math.inf,
        yaw_rate_cmd=-math.inf,
        gimbal_yaw_rate_cmd=math.nan,
        gimbal_pitch_rate_cmd=math.inf,
        enable_body=True,
        enable_gimbal=True,
        enable_approach=True,
        valid=True,
    )

    shaped = shaper.update(raw, dt=0.0)

    assert shaped.vx_cmd == pytest.approx(0.0)
    assert shaped.vy_cmd == pytest.approx(0.0)
    assert shaped.yaw_rate_cmd == pytest.approx(0.0)
    assert shaped.gimbal_yaw_rate_cmd == pytest.approx(0.0)
    assert shaped.gimbal_pitch_rate_cmd == pytest.approx(0.0)


def test_gimbal_angle_command_is_passed_through() -> None:
    shaper = CommandShaper()

    shaped = shaper.update(
        FlightCommand(
            gimbal_yaw_angle_cmd=0.1,
            gimbal_pitch_angle_cmd=-1.5707963267948966,
            enable_gimbal_angle=True,
            valid=True,
        ),
        dt=0.02,
    )

    assert shaped.enable_gimbal_angle is True
    assert shaped.gimbal_yaw_angle_cmd == pytest.approx(0.1)
    assert shaped.gimbal_pitch_angle_cmd == pytest.approx(-1.5707963267948966)
    assert shaped.active is True
