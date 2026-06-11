from __future__ import annotations

from telemetry_link.command_dispatcher import CommandResult
from uav_ui.control_switches import ControlRuntimeSwitches
from uav_ui.ui_commands import build_ui_command_handler


class _FakeManager:
    def __init__(self) -> None:
        self.clear_calls = 0
        self.velocity_commands: list[tuple[float, float, float, int]] = []
        self.modes: list[str] = []
        self.local_positions: list[dict[str, object]] = []

    def clear_continuous_commands(self) -> None:
        self.clear_calls += 1

    def send_velocity_command(self, vx: float, vy: float, vz: float, frame: int = 1) -> None:
        self.velocity_commands.append((vx, vy, vz, frame))

    def set_mode(self, mode: str) -> None:
        self.modes.append(mode)

    def local_position(self, x: float, y: float, z: float, frame: int, yaw: float | None = None, priority: int = 4) -> None:
        self.local_positions.append({"x": x, "y": y, "z": z, "frame": frame, "yaw": yaw})


class _FakeYoloClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, int | None]] = []

    def send(self, action: str, track_id: int | None = None) -> None:
        self.commands.append((action, track_id))


def _switches(*, send_commands: bool = True) -> ControlRuntimeSwitches:
    return ControlRuntimeSwitches(
        gimbal=True,
        body=True,
        approach=True,
        send_commands=send_commands,
    )


def test_manual_continuous_command_disables_automatic_sending_before_dispatch() -> None:
    manager = _FakeManager()
    switches = _switches()
    handler = build_ui_command_handler(manager, controller_switches=switches)

    result = handler("body_vel 1 2 3")

    assert result.ok is True
    assert switches.snapshot().send_commands is False
    assert manager.clear_calls == 1
    assert manager.velocity_commands == [(1.0, 2.0, 3.0, 8)]


def test_control_send_off_clears_continuous_commands() -> None:
    manager = _FakeManager()
    switches = _switches()
    handler = build_ui_command_handler(manager, controller_switches=switches)

    result = handler("control send off")

    assert result == CommandResult(True, "control send_commands=OFF")
    assert switches.snapshot().send_commands is False
    assert manager.clear_calls == 1


def test_mode_action_does_not_disable_automatic_sending() -> None:
    manager = _FakeManager()
    switches = _switches()
    handler = build_ui_command_handler(manager, controller_switches=switches)

    result = handler("mode GUIDED")

    assert result.ok is True
    assert switches.snapshot().send_commands is True
    assert manager.clear_calls == 0
    assert manager.modes == ["GUIDED"]


def test_target_lock_dispatches_yolo_udp_command() -> None:
    manager = _FakeManager()
    yolo_client = _FakeYoloClient()
    handler = build_ui_command_handler(manager, yolo_client=yolo_client)

    result = handler("target lock 7")

    assert result == CommandResult(True, "target lock_target sent track_id=7")
    assert yolo_client.commands == [("lock_target", 7)]


def test_mission_command_is_forwarded_to_app_handler() -> None:
    manager = _FakeManager()
    received: list[list[str]] = []

    def mission_handler(parts: list[str]) -> CommandResult:
        received.append(parts)
        return CommandResult(True, "mission switched")

    handler = build_ui_command_handler(manager, mission_command_handler=mission_handler)

    result = handler("mission switch rescue_competition")

    assert result == CommandResult(True, "mission switched")
    assert received == [["switch", "rescue_competition"]]


def test_stage_override_is_forwarded_to_app_handler() -> None:
    manager = _FakeManager()
    received: list[str | None] = []

    def stage_handler(stage: str | None) -> CommandResult:
        received.append(stage)
        return CommandResult(True, "stage updated")

    handler = build_ui_command_handler(manager, stage_override_handler=stage_handler)

    result = handler("stage mode OVERHEAD_HOLD")

    assert result == CommandResult(True, "stage updated")
    assert received == ["OVERHEAD_HOLD"]


def test_local_pos_clears_continuous_and_disables_sending() -> None:
    """local_pos is in _CONTINUOUS_MANUAL_COMMANDS — disables auto-send and clears continuous."""
    manager = _FakeManager()
    switches = _switches()
    handler = build_ui_command_handler(manager, controller_switches=switches)

    result = handler("local_pos 0 1 0 body_offset 1.23")

    assert result.ok is True
    assert switches.snapshot().send_commands is False
    assert manager.clear_calls == 1
    assert len(manager.local_positions) == 1
    assert manager.local_positions[0]["x"] == 0.0
    assert manager.local_positions[0]["y"] == 1.0
    assert manager.local_positions[0]["yaw"] == 1.23
