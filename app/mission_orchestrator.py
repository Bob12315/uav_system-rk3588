from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MissionActionStep:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MissionOrchestratorStatus:
    running: bool
    done: bool
    failed: bool
    current_index: int
    current_action: str | None
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


class MissionOrchestrator:
    """Minimal mission sequencer — drives ActionRuntimeService step by step.

    This orchestrator does NOT talk to LinkManager, pymavlink, or
    concrete Action classes directly.  All vehicle interaction flows
    through the ActionRuntimeService the caller injects.
    """

    def __init__(self, runtime: object, steps: list[MissionActionStep]) -> None:
        if not steps:
            raise ValueError("steps must be non-empty")
        self.runtime = runtime
        self.steps = list(steps)
        self.running = False
        self.done = False
        self.failed = False
        self.current_index = 0
        self.reason = "idle"
        self.detail: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.running = True
        self.done = False
        self.failed = False
        self.current_index = 0
        self.reason = "started"
        self.detail = {}
        self._start_current_step()

    def tick(
        self,
        context: dict[str, Any],
        *,
        link_manager: object | None = None,
        send_commands: bool = False,
    ) -> MissionOrchestratorStatus:
        if not self.running or self.done or self.failed:
            return self.status()

        # Drive the current action
        _status = self.runtime.tick(
            context,
            link_manager=link_manager,
            send_commands=send_commands,
        )

        # Read the ActionResult that ActionRuntimeService just processed
        result: dict[str, Any] = {}
        last_result_obj = getattr(self.runtime, "last_result", None)
        if last_result_obj is not None:
            if isinstance(last_result_obj, dict):
                result = last_result_obj
            else:
                result = last_result_obj.to_dict()

        if bool(result.get("failed")):
            self.failed = True
            self.running = False
            self.reason = str(result.get("reason") or "action_failed")
            self.detail = {"action_result": result}
            return self.status()

        if bool(result.get("done")):
            if self.current_index + 1 >= len(self.steps):
                self.done = True
                self.running = False
                self.reason = "mission_done"
                self.detail = {"action_result": result}
                return self.status()

            self.current_index += 1
            self.reason = "next_step"
            self.detail = {"previous_action_result": result}
            self._start_current_step()

        return self.status()

    def stop(self) -> None:
        self.runtime.stop()
        self.running = False
        self.reason = "stopped"

    def reset(self) -> None:
        self.runtime.reset()
        self.running = False
        self.done = False
        self.failed = False
        self.current_index = 0
        self.reason = "reset"
        self.detail = {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def status(self) -> MissionOrchestratorStatus:
        current = None
        if 0 <= self.current_index < len(self.steps):
            current = self.steps[self.current_index].name
        return MissionOrchestratorStatus(
            running=self.running,
            done=self.done,
            failed=self.failed,
            current_index=self.current_index,
            current_action=current,
            reason=self.reason,
            detail=dict(self.detail),
        )

    def _start_current_step(self) -> None:
        step = self.steps[self.current_index]
        self.runtime.start(step.name, dict(step.params), send_actions=True)
