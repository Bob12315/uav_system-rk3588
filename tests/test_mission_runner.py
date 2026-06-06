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

    def send_gimbal_angle(
        self,
        pitch: float,
        yaw: float,
        roll: float = 0.0,
        priority: int = 5,
    ) -> None:
        if self.fail:
            raise RuntimeError("gimbal angle failed")
        self.calls.append(("gimbal_angle", (pitch, yaw, roll), priority))

    def condition_yaw(
        self,
        yaw_deg: float,
        yaw_speed_deg_s: float = 20.0,
        direction: int = 0,
        relative: bool = False,
        priority: int = 4,
    ) -> None:
        if self.fail:
            raise RuntimeError("condition yaw failed")
        self.calls.append(
            (
                "condition_yaw",
                (yaw_deg, yaw_speed_deg_s, direction, relative),
                priority,
            )
        )

    def local_position(
        self,
        x: float,
        y: float,
        z: float,
        frame: int,
        yaw: float | None = None,
        priority: int = 4,
    ) -> None:
        if self.fail:
            raise RuntimeError("local position failed")
        self.calls.append(("local_position", (x, y, z, frame, yaw), priority))


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


def test_gimbal_angle_action_dispatches_through_link_manager() -> None:
    link = FakeLink()
    runner = MissionRunner(
        FakeMission(
            [
                MissionAction(
                    "gimbal_angle",
                    params={"pitch": -90.0, "yaw": 0.0, "roll": 0.0},
                    key="gimbal-downward",
                    priority=2,
                )
            ]
        ),
        link_manager=link,
        send_actions=True,
    )

    runner.update(_context())
    runner.update(_context())

    assert link.calls == [("gimbal_angle", (-90.0, 0.0, 0.0), 2)]


def test_local_position_action_dispatches_optional_yaw() -> None:
    link = FakeLink()
    runner = MissionRunner(
        FakeMission(
            [
                MissionAction(
                    "local_position",
                    params={"x": 1.0, "y": 2.0, "z": -3.0, "frame": 1, "yaw": 0.75},
                    priority=4,
                )
            ]
        ),
        link_manager=link,
        send_actions=True,
    )

    runner.update(_context())

    assert link.calls == [("local_position", (1.0, 2.0, -3.0, 1, 0.75), 4)]


def test_condition_yaw_action_dispatches_through_link_manager() -> None:
    link = FakeLink()
    runner = MissionRunner(
        FakeMission(
            [
                MissionAction(
                    "condition_yaw",
                    params={
                        "yaw_deg": 45.0,
                        "yaw_speed_deg_s": 30.0,
                        "direction": 0,
                        "relative": False,
                    },
                    priority=4,
                )
            ]
        ),
        link_manager=link,
        send_actions=True,
    )

    runner.update(_context())

    assert link.calls == [("condition_yaw", (45.0, 30.0, 0, False), 4)]


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
