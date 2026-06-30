from __future__ import annotations

import logging
from typing import Any

from missions.common.actions.runner import ActionRunner
from app.action_dispatcher import ActionDispatcher


_log = logging.getLogger(__name__)


class ActionRuntimeService:
    """Thin orchestrator that owns ActionRunner + ActionDispatcher.

    SystemRunner delegates its public action_lab_* methods here so that
    the runner lifecycle and dispatch plumbing stay in one place.
    """

    def __init__(self, *, runner: ActionRunner, dispatcher: ActionDispatcher | None = None) -> None:
        self.runner = runner
        self.dispatcher = dispatcher or ActionDispatcher()
        self.last_result: dict[str, object] | None = None

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
        link_manager: object | None = None,
        clear_navigation: bool = True,
    ):
        if clear_navigation:
            self.clear_navigation_queue(link_manager)
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
        result_dict = result.to_dict()
        self.last_result = result_dict
        if self.runner.action_name == "align_descend" and (result.done or result.failed):
            _log.info(
                "align_descend ended reason=%s aligned=%s hold_updates=%s/%s "
                "current_altitude_m=%s finish_altitude_m=%s min_altitude_m=%s "
                "payload_release_allowed=%s",
                result.reason,
                result.detail.get("aligned"),
                result.detail.get("hold_updates"),
                result.detail.get("hold_updates_required"),
                result.detail.get("current_altitude_m"),
                result.detail.get("finish_altitude_m"),
                result.detail.get("min_altitude_m"),
                result.reason == "aligned_and_reached_finish_altitude",
            )
        self.dispatcher.last_dispatch = self.dispatcher.dispatch_result(
            result.to_dict(),
            action_name=self.runner.action_name,
            link_manager=link_manager,
            send_commands=send_commands,
        )
        return self.runner.status()

    def stop(self, link_manager: object | None = None, *, hold_current: bool = False):
        """Stop the running action and optionally hold current position."""
        self.clear_navigation_queue(link_manager, hold_current=hold_current)
        self.dispatcher.last_dispatch = self.dispatcher.empty_dispatch()
        return self.runner.stop()

    def reset(self, link_manager: object | None = None, *, hold_current: bool = False):
        """Reset the runtime and optionally hold current position."""
        self.clear_navigation_queue(link_manager, hold_current=hold_current)
        if self.runner.current_action is not None and self.runner.state == "running":
            self.runner.stop()
        self.dispatcher.reset_keys()
        self.dispatcher.last_dispatch = self.dispatcher.empty_dispatch()
        self.dispatcher.last_servo_command = None
        self.last_result = None
        return self.runner.reset()

    def status(self) -> dict[str, object]:
        return self.runner.status()

    @staticmethod
    def clear_navigation_queue(
        link_manager: object | None,
        *,
        hold_current: bool = False,
        leave_stop_queued: bool = False,
    ) -> None:
        """Clear continuous commands and pending LOCAL_POSITION; optionally send a hold.

        Order is important:
        By default the STOP sample is cleared too, so starting takeoff or a
        position action cannot inherit a persistent zero-velocity override.
        Only the align_descend -> payload_release transition opts into leaving
        STOP queued until payload_release starts refreshing its own zero command.
        """
        if link_manager is None:
            return

        stop_body = getattr(link_manager, "stop_body_velocity", None)
        clear_continuous = getattr(link_manager, "clear_continuous_commands", None)
        clear_nav = getattr(link_manager, "clear_pending_local_position_actions", None)
        if leave_stop_queued:
            if callable(clear_continuous):
                clear_continuous()
            if callable(clear_nav):
                clear_nav()
            if callable(stop_body):
                _log.info("queue persistent stop BODY_NED velocity for payload transition")
                stop_body()
        else:
            if callable(stop_body):
                _log.info("queue transient stop BODY_NED velocity before clearing")
                stop_body()
            if callable(clear_continuous):
                clear_continuous()
            if callable(clear_nav):
                clear_nav()

        if hold_current:
            hold = getattr(link_manager, "hold_current_local_position", None)
            if callable(hold):
                hold()

    def status_payload(self, *, send_commands: bool) -> dict[str, object]:
        return self.dispatcher.payload(
            status=self.runner.status(),
            action_name=self.runner.action_name,
            send_commands=send_commands,
        )
