from __future__ import annotations

from typing import Any

from missions.common.actions.action_lab import create_action_lab_registry
from missions.common.actions.runner import ActionRunner
from app.action_dispatcher import ActionDispatcher


class ActionRuntimeService:
    """Thin orchestrator that owns ActionRunner + ActionDispatcher.

    SystemRunner delegates its public action_lab_* methods here so that
    the runner lifecycle and dispatch plumbing stay in one place.
    """

    def __init__(self, *, dispatcher: ActionDispatcher | None = None) -> None:
        self.runner = ActionRunner(create_action_lab_registry())
        self.dispatcher = dispatcher or ActionDispatcher()

    # ------------------------------------------------------------------
    # convenience properties
    # ------------------------------------------------------------------

    @property
    def action_name(self) -> str | None:
        return self.runner.action_name

    @property
    def send_actions_requested(self) -> bool:
        return self.dispatcher.send_actions

    @send_actions_requested.setter
    def send_actions_requested(self, value: bool) -> None:
        self.dispatcher.send_actions = bool(value)

    # ------------------------------------------------------------------
    # public API — mirrors SystemRunner.action_lab_*
    # ------------------------------------------------------------------

    def start(
        self,
        action_name: str,
        params: dict[str, object] | None = None,
        *,
        send_actions: bool | None = None,
    ):
        if send_actions is not None:
            self.dispatcher.send_actions = bool(send_actions)
        # Switch-running action: stop the current one first.
        if (
            self.runner.state == "running"
            and self.runner.action_name
            and self.runner.action_name != action_name
        ):
            self.runner.stop()
        self.dispatcher.reset_keys()
        self.dispatcher.last_dispatch = self.dispatcher.empty_dispatch()
        self.dispatcher.last_servo_command = None
        return self.runner.start(action_name, dict(params or {}))

    def tick(
        self,
        context: dict[str, object],
        *,
        link_manager: object | None,
        send_commands: bool,
    ) -> dict[str, object]:
        if self.runner.state != "running":
            return self.runner.status()
        result = self.runner.update(context)
        self.dispatcher.last_dispatch = self.dispatcher.dispatch_result(
            result.to_dict(),
            action_name=self.runner.action_name,
            link_manager=link_manager,
            send_commands=send_commands,
        )
        return self.runner.status()

    def stop(self):
        self.dispatcher.last_dispatch = self.dispatcher.empty_dispatch()
        return self.runner.stop()

    def reset(self):
        if self.runner.current_action is not None and self.runner.state == "running":
            self.runner.stop()
        self.dispatcher.reset_keys()
        self.dispatcher.last_dispatch = self.dispatcher.empty_dispatch()
        self.dispatcher.last_servo_command = None
        return self.runner.reset()

    def status(self) -> dict[str, object]:
        return self.runner.status()

    def status_payload(self, *, send_commands: bool) -> dict[str, object]:
        return self.dispatcher.payload(
            status=self.runner.status(),
            action_name=self.runner.action_name,
            send_commands=send_commands,
        )
