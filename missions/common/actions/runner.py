from __future__ import annotations

from typing import Any

from .base import ActionModule
from .registry import ActionRegistry, default_registry
from .result import ActionResult


class ActionRunner:
    def __init__(self, registry: ActionRegistry | None = None):
        self.registry = registry or default_registry
        self.state = "idle"
        self.action_name: str | None = None
        self.current_action: ActionModule | None = None
        self.last_result = ActionResult()

    def start(
        self,
        action_name: str,
        params: dict[str, Any] | None = None,
    ) -> ActionResult:
        if self.state == "running" and self.current_action is not None:
            return self._set_result(
                ActionResult(failed=True, reason="action_already_running")
            )
        try:
            action = self.registry.create(action_name)
        except KeyError as exc:
            self.state = "idle"
            return self._set_result(
                ActionResult(
                    failed=True,
                    reason="unknown_action",
                    detail={"action_name": action_name, "error": str(exc)},
                )
            )
        try:
            action.start(params)
        except Exception as exc:
            self.current_action = None
            self.action_name = None
            self.state = "failed"
            return self._set_result(
                ActionResult(
                    failed=True,
                    reason="action_start_failed",
                    detail={"action_name": action_name, "error": str(exc)},
                )
            )
        self.current_action = action
        self.action_name = action_name
        self.state = "running"
        return self._set_result(ActionResult(reason="action_started"))

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if self.state != "running" or self.current_action is None:
            return self._set_result(ActionResult(reason="no_active_action"))
        try:
            result = self.current_action.update(context)
        except Exception as exc:
            self.state = "failed"
            return self._set_result(
                ActionResult(
                    failed=True,
                    reason="action_update_failed",
                    detail={"action_name": self.action_name, "error": str(exc)},
                )
            )
        if not isinstance(result, ActionResult):
            self.state = "failed"
            return self._set_result(
                ActionResult(failed=True, reason="invalid_action_result")
            )
        if result.failed:
            self.state = "failed"
        elif result.done:
            self.state = "done"
        return self._set_result(result)

    def stop(self) -> ActionResult:
        if self.current_action is None:
            return self._set_result(ActionResult(reason="no_active_action"))
        try:
            self.current_action.stop()
        except Exception as exc:
            self.state = "failed"
            return self._set_result(
                ActionResult(
                    failed=True,
                    reason="action_stop_failed",
                    detail={"action_name": self.action_name, "error": str(exc)},
                )
            )
        self.state = "stopped"
        return self._set_result(ActionResult(reason="action_stopped"))

    def reset(self) -> ActionResult:
        reset_error: Exception | None = None
        try:
            if self.current_action is not None:
                self.current_action.reset()
        except Exception as exc:
            reset_error = exc
        finally:
            self.current_action = None
            self.action_name = None
            self.state = "idle"
        if reset_error is not None:
            return self._set_result(
                ActionResult(
                    failed=True,
                    reason="action_reset_failed",
                    detail={"error": str(reset_error)},
                )
            )
        return self._set_result(ActionResult(reason="action_reset"))

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "action_name": self.action_name,
            "running": self.state == "running",
            "last_result": self.last_result.to_dict(),
        }

    def _set_result(self, result: ActionResult) -> ActionResult:
        self.last_result = result
        return result
