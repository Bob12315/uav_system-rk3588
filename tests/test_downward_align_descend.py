from __future__ import annotations

import pytest

from missions.common.control.types import MissionStageInput
from missions.rescue_competition.stages.downward_align_descend import (
    DownwardAlignDescendMode,
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
        control_allowed=True,
        ex_cam=0.04,
        ey_cam=0.05,
        vision_age_s=0.01,
        drone_age_s=0.01,
    )
    data.update(overrides)
    return MissionStageInput(**data)


def test_downward_align_descend_maps_camera_errors_without_yaw_or_gimbal() -> None:
    command, status = DownwardAlignDescendMode().update(_inputs())

    assert status.mode_name == "DOWNWARD_ALIGN_DESCEND"
    assert status.detail["aligned"] is True
    assert command.vx_cmd == pytest.approx(-0.04)
    assert command.vy_cmd == pytest.approx(0.032)
    assert command.vz_cmd == pytest.approx(0.2)
    assert command.yaw_rate_cmd == pytest.approx(0.0)
    assert command.enable_body is True
    assert command.enable_approach is True
    assert command.enable_gimbal is False


def test_downward_align_descend_holds_altitude_until_aligned() -> None:
    command, status = DownwardAlignDescendMode().update(_inputs(ex_cam=0.2))

    assert status.hold_reason == "aligning"
    assert command.active is True
    assert command.vz_cmd == pytest.approx(0.0)
    assert command.vy_cmd != pytest.approx(0.0)


def test_downward_align_descend_zeroes_when_target_invalid() -> None:
    command, status = DownwardAlignDescendMode().update(_inputs(target_valid=False))

    assert status.hold_reason == "target_not_valid"
    assert command.active is False
    assert command.vx_cmd == pytest.approx(0.0)
    assert command.vy_cmd == pytest.approx(0.0)
    assert command.vz_cmd == pytest.approx(0.0)
