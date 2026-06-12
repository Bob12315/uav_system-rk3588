from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MissionActionStep:
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    save_as: str | None = None
    label: str | None = None
    on_failed: dict[str, Any] | None = None


@dataclass(slots=True)
class MissionOrchestratorStatus:
    running: bool
    done: bool
    failed: bool
    current_index: int
    current_action: str | None
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


class MissionBlackboard:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def clear(self) -> None:
        self.data.clear()

    def set(self, name: str, value: Any) -> None:
        normalized = self._normalize_name(name)
        self.data[normalized] = value

    def get_path(self, path: str) -> Any:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("blackboard path must be a non-empty string")
        current: Any = self.data
        for part in path.strip().split("."):
            if not part:
                raise ValueError("blackboard path contains an empty segment")
            if isinstance(current, dict):
                if part not in current:
                    raise KeyError(part)
                current = current[part]
                continue
            if isinstance(current, list):
                try:
                    index = int(part)
                except ValueError as exc:
                    raise ValueError(f"list index must be an integer: {part}") from exc
                try:
                    current = current[index]
                except IndexError as exc:
                    raise KeyError(part) from exc
                continue
            raise KeyError(part)
        return current

    def resolve(self, value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith("$"):
                return self.get_path(value[1:])
            return value
        if isinstance(value, dict):
            return {key: self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        return value

    def _normalize_name(self, name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("blackboard name must be a non-empty string")
        normalized = name.strip()
        if not normalized:
            raise ValueError("blackboard name must be a non-empty string")
        return normalized


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
        self.blackboard = MissionBlackboard()
        self.step_attempts: dict[int, int] = {}
        self.failure_policy_counts: dict[str, int] = {}
        self.labels = self._build_labels()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self, *, link_manager: object | None = None) -> None:
        self.running = True
        self.done = False
        self.failed = False
        self.current_index = 0
        self.reason = "started"
        self.detail = {}
        self.blackboard.clear()
        self.step_attempts.clear()
        self.failure_policy_counts.clear()
        self._start_current_step(link_manager=link_manager)

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
            self._handle_step_failed(result, link_manager=link_manager)
            return self.status()

        if bool(result.get("done")):
            step = self.steps[self.current_index]
            if step.save_as:
                try:
                    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
                    self.blackboard.set(step.save_as, detail)
                except Exception as exc:
                    self.failed = True
                    self.running = False
                    self.reason = "blackboard_save_failed"
                    self.detail = {
                        "step_index": self.current_index,
                        "step_name": step.name,
                        "save_as": step.save_as,
                        "error": str(exc),
                        "blackboard_keys": sorted(self.blackboard.data.keys()),
                    }
                    return self.status()

            if self.current_index + 1 >= len(self.steps):
                self.done = True
                self.running = False
                self.reason = "mission_done"
                self.detail = {"action_result": result}
                return self.status()

            self.current_index += 1
            self.reason = "next_step"
            self.detail = {"previous_action_result": result}
            # Clear any stale LOCAL_POSITION before starting the next step
            clear_nav = getattr(self.runtime, "clear_navigation_queue", None)
            if callable(clear_nav):
                clear_nav(link_manager)
            self._start_current_step(link_manager=link_manager)

        return self.status()

    def stop(self, *, link_manager: object | None = None, hold_current: bool = False) -> None:
        stop = getattr(self.runtime, "stop", None)
        if callable(stop):
            stop(link_manager, hold_current=hold_current)
        self.running = False
        self.reason = "stopped"

    def reset(self, *, link_manager: object | None = None, hold_current: bool = False) -> None:
        reset = getattr(self.runtime, "reset", None)
        if callable(reset):
            reset(link_manager, hold_current=hold_current)
        self.running = False
        self.done = False
        self.failed = False
        self.current_index = 0
        self.reason = "reset"
        self.detail = {}
        self.blackboard.clear()
        self.step_attempts.clear()
        self.failure_policy_counts.clear()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def status(self) -> MissionOrchestratorStatus:
        current = None
        if 0 <= self.current_index < len(self.steps):
            current = self.steps[self.current_index].name
        detail = dict(self.detail)
        detail["blackboard_keys"] = sorted(self.blackboard.data.keys())
        detail["step_attempts"] = dict(self.step_attempts)
        detail["failure_policy_counts"] = dict(self.failure_policy_counts)
        return MissionOrchestratorStatus(
            running=self.running,
            done=self.done,
            failed=self.failed,
            current_index=self.current_index,
            current_action=current,
            reason=self.reason,
            detail=detail,
        )

    def _start_current_step(self, *, link_manager: object | None = None) -> None:
        step = self.steps[self.current_index]
        start = getattr(self.runtime, "start", None)
        if callable(start):
            try:
                resolved_params = self.blackboard.resolve(dict(step.params))
            except Exception as exc:
                self.failed = True
                self.running = False
                self.reason = "param_resolution_failed"
                self.detail = {
                    "step_index": self.current_index,
                    "step_name": step.name,
                    "error": str(exc),
                    "blackboard_keys": sorted(self.blackboard.data.keys()),
                }
                return
            self.step_attempts[self.current_index] = self.step_attempts.get(self.current_index, 0) + 1
            start(step.name, resolved_params, send_actions=True, link_manager=link_manager)

    def _handle_step_failed(
        self,
        result: dict[str, Any],
        *,
        link_manager: object | None = None,
    ) -> None:
        step = self.steps[self.current_index]
        policy = step.on_failed or {}
        action = str(policy.get("action", "fail")).strip().lower()
        if action == "retry_current":
            self._handle_retry_current(result, policy, link_manager=link_manager)
            return
        if action == "jump_to":
            self._handle_jump_to(result, policy, link_manager=link_manager)
            return
        if action == "continue":
            self._handle_continue(result, link_manager=link_manager)
            return
        self._fail_mission(result, reason=str(result.get("reason") or "action_failed"))

    def _handle_retry_current(
        self,
        result: dict[str, Any],
        policy: dict[str, Any],
        *,
        link_manager: object | None,
    ) -> None:
        max_attempts = int(policy.get("max_attempts", 1))
        attempts = self.step_attempts.get(self.current_index, 1)
        if attempts < max_attempts:
            self.reason = "retry_current"
            self.detail = {
                "failed_action_result": result,
                "retry_step_index": self.current_index,
                "attempt": attempts + 1,
                "max_attempts": max_attempts,
            }
            self._clear_runtime_before_retry(link_manager)
            self._start_current_step(link_manager=link_manager)
            return
        self._fail_mission(result, reason="retry_attempts_exhausted")

    def _handle_jump_to(
        self,
        result: dict[str, Any],
        policy: dict[str, Any],
        *,
        link_manager: object | None,
    ) -> None:
        target = str(policy.get("target") or "").strip()
        if target not in self.labels:
            self._fail_mission(result, reason="jump_target_not_found")
            return
        max_attempts = int(policy.get("max_attempts", 1))
        key = f"{self.current_index}:jump_to:{target}"
        count = self.failure_policy_counts.get(key, 0)
        if count < max_attempts:
            self.failure_policy_counts[key] = count + 1
            self.current_index = self.labels[target]
            self.reason = "jump_to"
            self.detail = {
                "failed_action_result": result,
                "target": target,
                "target_index": self.current_index,
                "policy_count": count + 1,
                "max_attempts": max_attempts,
            }
            self._clear_runtime_before_retry(link_manager)
            self._start_current_step(link_manager=link_manager)
            return
        self._fail_mission(result, reason="jump_attempts_exhausted")

    def _handle_continue(self, result: dict[str, Any], *, link_manager: object | None) -> None:
        if self.current_index + 1 >= len(self.steps):
            self.done = True
            self.running = False
            self.reason = "mission_done_after_failed_continue"
            self.detail = {"failed_action_result": result}
            return
        self.current_index += 1
        self.reason = "continue_after_failed_step"
        self.detail = {"failed_action_result": result}
        self._clear_runtime_before_retry(link_manager)
        self._start_current_step(link_manager=link_manager)

    def _fail_mission(self, result: dict[str, Any], *, reason: str) -> None:
        self.failed = True
        self.running = False
        self.reason = reason
        self.detail = {"action_result": result}

    def _clear_runtime_before_retry(self, link_manager: object | None = None) -> None:
        clear_nav = getattr(self.runtime, "clear_navigation_queue", None)
        if callable(clear_nav):
            clear_nav(link_manager, hold_current=True)
        reset = getattr(self.runtime, "reset", None)
        if callable(reset):
            reset(link_manager, hold_current=True)

    def _build_labels(self) -> dict[str, int]:
        labels: dict[str, int] = {}
        for index, step in enumerate(self.steps):
            if step.label is None:
                continue
            label = step.label.strip()
            if not label:
                continue
            if label in labels:
                raise ValueError(f"duplicate mission step label: {label}")
            labels[label] = index
        return labels
