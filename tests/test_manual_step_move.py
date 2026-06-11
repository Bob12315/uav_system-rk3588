from __future__ import annotations

import math
from collections import deque

import pytest

from telemetry_link.command_dispatcher import CommandResult


def _fake_runner(*, local_x=10.0, local_y=20.0, local_z=-3.0, yaw=0.0,
                 local_position_valid=True, action_running=False,
                 mission_running=False):
    """Minimal fake SystemRunner with a fake link_manager."""

    class FakeManager:
        def __init__(self):
            self.calls: list[str] = []
            self.last_local_pos: dict = {}

        def clear_continuous_commands(self):
            self.calls.append("clear_continuous")

        def clear_pending_local_position_actions(self):
            self.calls.append("clear_pending")

        def local_position(self, x, y, z, frame, yaw=None, priority=4):
            self.last_local_pos = {"x": x, "y": y, "z": z,
                                   "frame": frame, "yaw": yaw, "priority": priority}
            self.calls.append("local_position")

    class FakeActionRuntime:
        class Runner:
            state = "running" if action_running else "idle"

        runner = Runner()

        def stop(self, link_manager=None, hold_current=False):
            FakeActionRuntime.Runner.state = "stopped"

    class FakeOrchestrator:
        def __init__(self):
            self.running = mission_running

        def stop(self, link_manager=None, hold_current=False):
            self.running = False

    manager = FakeManager()
    runner = type("FakeRunner", (), {
        "services": type("FakeServices", (), {"link_manager": manager})(),
        "control_command_log_lock": type("FakeLock", (), {
            "__enter__": lambda s: None,
            "__exit__": lambda s, *a: None,
        })(),
        "latest_snapshot": {
            "drone": {
                "local_position_valid": local_position_valid,
                "local_x": local_x,
                "local_y": local_y,
                "local_z": local_z,
                "yaw": yaw,
            }
        },
        "action_runtime_lock": type("FakeLock2", (), {
            "__enter__": lambda s: None,
            "__exit__": lambda s, *a: None,
        })(),
        "action_runtime": FakeActionRuntime(),
        "action_mission_orchestrator": FakeOrchestrator(),
        "system_events": deque(maxlen=160),
        "manual_step_move": None,  # will be patched
    })()
    return manager, runner


def test_forward_move_yaw_zero() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=0, local_position_valid=True)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "forward", 1.0)
    assert manager.last_local_pos["x"] == pytest.approx(11.0)
    assert manager.last_local_pos["y"] == pytest.approx(20.0)
    assert manager.last_local_pos["z"] == pytest.approx(-3.0)
    assert manager.last_local_pos["yaw"] == pytest.approx(0.0)


def test_right_move_yaw_zero() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=0)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "right", 1.0)
    assert manager.last_local_pos["x"] == pytest.approx(10.0)
    assert manager.last_local_pos["y"] == pytest.approx(21.0)
    assert manager.last_local_pos["z"] == pytest.approx(-3.0)
    assert manager.last_local_pos["yaw"] == pytest.approx(0.0)


def test_left_move_yaw_zero() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=0)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "left", 1.0)
    assert manager.last_local_pos["x"] == pytest.approx(10.0)
    assert manager.last_local_pos["y"] == pytest.approx(19.0)
    assert manager.last_local_pos["z"] == pytest.approx(-3.0)
    assert manager.last_local_pos["yaw"] == pytest.approx(0.0)


def test_back_move_yaw_zero() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=0)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "back", 1.0)
    assert manager.last_local_pos["x"] == pytest.approx(9.0)
    assert manager.last_local_pos["y"] == pytest.approx(20.0)


def test_forward_move_yaw_pi_half() -> None:
    """forward with yaw=pi/2 means heading east, so forward goes +y."""
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=math.pi / 2)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "forward", 1.0)
    assert manager.last_local_pos["x"] == pytest.approx(10.0, abs=1e-6)
    assert manager.last_local_pos["y"] == pytest.approx(21.0, abs=1e-6)


def test_right_move_yaw_pi_half() -> None:
    """right with yaw=pi/2 means body-right is south, so local_x decreases."""
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=math.pi / 2)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "right", 1.0)
    assert manager.last_local_pos["x"] == pytest.approx(9.0, abs=1e-6)
    assert manager.last_local_pos["y"] == pytest.approx(20.0, abs=1e-6)


def test_up_move_only_changes_z() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=0)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "up", 1.0)
    assert manager.last_local_pos["x"] == pytest.approx(10.0)
    assert manager.last_local_pos["y"] == pytest.approx(20.0)
    assert manager.last_local_pos["z"] == pytest.approx(-4.0)
    assert manager.last_local_pos["yaw"] == pytest.approx(0.0)


def test_down_move_only_changes_z() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=0)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "down", 1.0)
    assert manager.last_local_pos["z"] == pytest.approx(-2.0)


def test_missing_local_position_valid() -> None:
    manager, fake = _fake_runner(local_position_valid=False)
    from app.system_runner import SystemRunner
    result = SystemRunner.manual_step_move(fake, "forward", 1.0)
    assert result.ok is False
    assert "no valid local position" in result.message


def test_missing_yaw() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3)
    # delete yaw
    fake.latest_snapshot["drone"].pop("yaw", None)
    from app.system_runner import SystemRunner
    result = SystemRunner.manual_step_move(fake, "forward", 1.0)
    assert result.ok is False


def test_clears_before_sending() -> None:
    manager, fake = _fake_runner(local_x=10, local_y=20, local_z=-3, yaw=0)
    from app.system_runner import SystemRunner
    SystemRunner.manual_step_move(fake, "forward", 1.0)
    # order must be clear_continuous -> clear_pending -> local_position
    assert manager.calls[:3] == ["clear_continuous", "clear_pending", "local_position"]


def test_invalid_direction() -> None:
    manager, fake = _fake_runner()
    from app.system_runner import SystemRunner
    result = SystemRunner.manual_step_move(fake, "diagonal", 1.0)
    assert result.ok is False
    assert "invalid direction" in result.message
