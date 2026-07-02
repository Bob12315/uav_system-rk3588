from __future__ import annotations

from app.action_runtime import ActionRuntimeService


def test_clear_navigation_queue_does_not_leave_zero_velocity_by_default() -> None:
    calls: list[str] = []

    class FakeLink:
        def stop_body_velocity(self) -> None:
            calls.append("stop_body_velocity")

        def clear_continuous_commands(self) -> None:
            calls.append("clear_continuous_commands")

        def clear_pending_local_position_actions(self) -> None:
            calls.append("clear_pending_local_position_actions")

    ActionRuntimeService.clear_navigation_queue(FakeLink())

    assert calls == [
        "stop_body_velocity",
        "clear_continuous_commands",
        "clear_pending_local_position_actions",
    ]


def test_clear_navigation_queue_can_leave_stop_for_payload_transition() -> None:
    calls: list[str] = []

    class FakeLink:
        def stop_body_velocity(self) -> None:
            calls.append("stop_body_velocity")

        def clear_continuous_commands(self) -> None:
            calls.append("clear_continuous_commands")

        def clear_pending_local_position_actions(self) -> None:
            calls.append("clear_pending_local_position_actions")

        def hold_current_local_position(self) -> None:
            calls.append("hold_current_local_position")

    ActionRuntimeService.clear_navigation_queue(
        FakeLink(),
        hold_current=True,
        leave_stop_queued=True,
    )

    assert calls == [
        "clear_continuous_commands",
        "clear_pending_local_position_actions",
        "stop_body_velocity",
        "hold_current_local_position",
    ]
