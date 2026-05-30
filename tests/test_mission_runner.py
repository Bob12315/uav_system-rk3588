from __future__ import annotations

from dataclasses import dataclass, field

from app.health_monitor import HealthStatus
from app.mission_runner import MissionRunner
from missions.common.control.types import MissionStageInput
from fusion.models import PerceptionTarget
from missions.base import MissionAction, MissionContext, MissionOutput
from telemetry_link.models import DroneState, GimbalState, LinkStatus


@dataclass(slots=True)
class FakeMission:
    actions: list[MissionAction]
    name: str = "fake"
    calls: int = 0

    def reset(self) -> None:
        self.calls = 0

    def update(self, context: MissionContext) -> MissionOutput:
        self.calls += 1
        return MissionOutput(active_mode="IDLE", actions=list(self.actions))


@dataclass(slots=True)
class FakeLink:
    calls: list[tuple[str, tuple[object, ...], int]] = field(default_factory=list)
    fail: bool = False

    def arm(self, priority: int = 1) -> None:
        if self.fail:
            raise RuntimeError("arm failed")
        self.calls.append(("arm", (), priority))

    def set_servo(self, channel: int, pwm: int, priority: int = 3) -> None:
        if self.fail:
            raise RuntimeError("servo failed")
        self.calls.append(("set_servo", (channel, pwm), priority))


@dataclass(slots=True)
class FakeYoloClient:
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def lock_target(self, track_id: int) -> None:
        self.calls.append(("lock_target", (track_id,)))

    def unlock_target(self) -> None:
        self.calls.append(("unlock_target", ()))


def _context() -> MissionContext:
    health = HealthStatus(
        vision_fresh=False,
        drone_fresh=False,
        gimbal_fresh=False,
        fusion_ready=False,
        control_ready=False,
        target_ready=False,
        hold_reason="fusion_invalid",
    )
    return MissionContext(
        timestamp=1.0,
        inputs=MissionStageInput(),
        health=health,
        perception=PerceptionTarget(),
        drone=DroneState(),
        gimbal=GimbalState(),
        link=LinkStatus(),
    )


def test_once_action_only_dispatches_once() -> None:
    link = FakeLink()
    runner = MissionRunner(
        FakeMission([MissionAction("arm", key="arm-once", priority=2)]),
        link_manager=link,
        send_actions=True,
    )

    runner.update(_context())
    runner.update(_context())

    assert link.calls == [("arm", (), 2)]
    assert runner.executed_action_keys == {"arm-once"}


def test_non_once_action_can_dispatch_repeatedly() -> None:
    link = FakeLink()
    runner = MissionRunner(
        FakeMission(
            [
                MissionAction(
                    "set_servo",
                    params={"channel": 9, "pwm": 1900},
                    once=False,
                    priority=4,
                )
            ]
        ),
        link_manager=link,
        send_actions=True,
    )

    runner.update(_context())
    runner.update(_context())

    assert link.calls == [
        ("set_servo", (9, 1900), 4),
        ("set_servo", (9, 1900), 4),
    ]


def test_send_actions_false_does_not_dispatch_or_mark_once() -> None:
    link = FakeLink()
    runner = MissionRunner(
        FakeMission([MissionAction("arm", key="arm-once")]),
        link_manager=link,
        send_actions=False,
    )

    output = runner.update(_context())

    assert output.active_mode == "IDLE"
    assert link.calls == []
    assert runner.executed_action_keys == set()
    assert runner.get_action_log_lines()[0].startswith("DRY action skipped action=arm")


def test_missing_link_manager_is_safe_and_does_not_mark_once() -> None:
    runner = MissionRunner(FakeMission([MissionAction("arm", key="arm-once")]))
    runner.send_actions = True

    output = runner.update(_context())

    assert output.active_mode == "IDLE"
    assert runner.executed_action_keys == set()
    assert runner.get_action_log_lines()[0].startswith("DROP action missing_link action=arm")


def test_unknown_action_does_not_mark_once() -> None:
    link = FakeLink()
    runner = MissionRunner(
        FakeMission([MissionAction("unknown", key="unknown-once")]),
        link_manager=link,
        send_actions=True,
    )

    runner.update(_context())

    assert link.calls == []
    assert runner.executed_action_keys == set()
    assert runner.get_action_log_lines()[0].startswith("DROP action unknown action=unknown")


def test_dispatch_exception_does_not_mark_once() -> None:
    link = FakeLink(fail=True)
    runner = MissionRunner(
        FakeMission([MissionAction("arm", key="arm-once")]),
        link_manager=link,
        send_actions=True,
    )

    runner.update(_context())

    assert runner.executed_action_keys == set()
    assert runner.get_action_log_lines()[0].startswith("FAIL action dispatch_failed action=arm")


def test_yolo_lock_target_respects_dry_run_and_once_guard() -> None:
    yolo = FakeYoloClient()
    runner = MissionRunner(
        FakeMission(
            [
                MissionAction(
                    "yolo_lock_target",
                    params={"track_id": 7},
                    key="lock-7",
                )
            ]
        ),
        yolo_client=yolo,
        send_actions=False,
    )

    runner.update(_context())

    assert yolo.calls == []
    assert runner.executed_action_keys == set()
    assert runner.get_action_log_lines()[0].startswith("DRY action skipped action=yolo_lock_target")


def test_yolo_lock_target_dispatches_and_marks_once_when_enabled() -> None:
    yolo = FakeYoloClient()
    runner = MissionRunner(
        FakeMission(
            [
                MissionAction(
                    "yolo_lock_target",
                    params={"track_id": 7},
                    key="lock-7",
                )
            ]
        ),
        yolo_client=yolo,
        send_actions=True,
    )

    runner.update(_context())
    runner.update(_context())

    assert yolo.calls == [("lock_target", (7,))]
    assert runner.executed_action_keys == {"lock-7"}


def test_yolo_unlock_target_dispatches_when_enabled() -> None:
    yolo = FakeYoloClient()
    runner = MissionRunner(
        FakeMission([MissionAction("yolo_unlock_target", key="unlock")]),
        yolo_client=yolo,
        send_actions=True,
    )

    runner.update(_context())

    assert yolo.calls == [("unlock_target", ())]
    assert runner.executed_action_keys == {"unlock"}
