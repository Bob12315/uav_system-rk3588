from __future__ import annotations

from app.action_runtime import ActionRuntimeService


def test_clear_navigation_queue_stops_body_velocity_before_clearing() -> None:
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
