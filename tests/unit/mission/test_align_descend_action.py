from __future__ import annotations

import math

from contracts.effects import FlightCommand
from missions.common.actions.align_descend import AlignDescendAction


def _context(*, ex: float = 0.0, ey: float = 0.0, altitude_m: float = 2.0, locked: bool = True) -> dict:
    return {
        "field_heading_yaw_rad": 0.0,
        "drone": {"connected": True, "stale": False, "control_allowed": True, "relative_altitude": altitude_m},
        "perception": {
            "target_valid": True,
            "tracking_state": "locked" if locked else "tracking",
            "track_id": 42,
            "ex": ex,
            "ey": ey,
        },
    }


def _command(result) -> FlightCommand:
    assert len(result.effects) == 1
    command = result.effects[0]
    assert isinstance(command, FlightCommand)
    return command


def test_locked_target_uses_body_velocity_descent_and_fixed_yaw() -> None:
    action = AlignDescendAction()
    action.start({
        "track_id": 42,
        "target_altitude_m": 1.0,
        "field_yaw_deg": 90.0,
        "kp_forward": 1.0,
        "kp_right": 1.0,
        "max_vx_mps": 0.5,
        "max_vy_mps": 0.5,
        "descend_speed_mps": 0.2,
        "descent_deadband_ex": 0.3,
        "descent_deadband_ey": 0.3,
    })

    result = action.update(_context(ex=0.1, ey=-0.2))

    assert result.reason == "align_descending"
    command = _command(result)
    assert command.params["vx_cmd"] == 0.2
    assert command.params["vy_cmd"] == 0.1
    assert command.params["vz_cmd"] == 0.2
    assert math.isclose(command.params["yaw_hold_rad"], math.pi / 2)
    assert "yaw_rate" not in command.params


def test_completion_requires_height_and_release_deadband_then_stops() -> None:
    action = AlignDescendAction()
    action.start({"target_altitude_m": 1.0, "release_deadband_ex": 0.1, "release_deadband_ey": 0.1})

    result = action.update(_context(ex=0.05, ey=-0.05, altitude_m=1.0))

    assert result.done and not result.failed
    assert result.reason == "ready_to_release"
    command = _command(result)
    assert command.params["vx_cmd"] == command.params["vy_cmd"] == command.params["vz_cmd"] == 0.0


def test_unlocked_target_fails_safe_with_an_explicit_stop() -> None:
    action = AlignDescendAction()
    action.start({"target_altitude_m": 1.0})

    result = action.update(_context(locked=False))

    assert result.failed and result.reason == "target_not_locked"
    command = _command(result)
    assert command.params["vx_cmd"] == command.params["vy_cmd"] == command.params["vz_cmd"] == 0.0


def test_timeout_fails_safe_and_never_marks_release_ready() -> None:
    action = AlignDescendAction()
    action.start({"target_altitude_m": 1.0, "max_duration_s": 1.0})
    action.started_at -= 2.0

    result = action.update(_context(ex=0.0, ey=0.0, altitude_m=1.0))

    assert result.failed and not result.done
    assert result.reason == "align_descend_timeout"
    command = _command(result)
    assert command.params["vx_cmd"] == command.params["vy_cmd"] == command.params["vz_cmd"] == 0.0
