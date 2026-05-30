from __future__ import annotations

import pytest

from missions.common.control.executor import FlightCommandExecutor
from missions.common.control.types import FlightCommand


class _FakeTelemetryLink:
    def __init__(self) -> None:
        self.gimbal_angles: list[dict[str, float]] = []

    def send_gimbal_angle(self, pitch: float, yaw: float, roll: float = 0.0) -> None:
        self.gimbal_angles.append({"pitch": pitch, "yaw": yaw, "roll": roll})


def test_executor_sends_gimbal_angle_command_in_degrees() -> None:
    link = _FakeTelemetryLink()
    executor = FlightCommandExecutor(telemetry_link=link)

    executor.execute(
        FlightCommand(
            gimbal_yaw_angle_cmd=0.1,
            gimbal_pitch_angle_cmd=-1.5707963267948966,
            enable_gimbal_angle=True,
            valid=True,
        )
    )

    assert len(link.gimbal_angles) == 1
    assert link.gimbal_angles[0]["pitch"] == pytest.approx(-90.0)
    assert link.gimbal_angles[0]["yaw"] == pytest.approx(5.7295779513)
    assert link.gimbal_angles[0]["roll"] == pytest.approx(0.0)
