"""DropSequenceAction — composite drop sequence for finish-first mission.

Orchestrates goto → lock → align_descend → payload_release → climb
for up to max_payloads payloads across up to max_target_candidates targets.

Key safety rules:
- lock_target failure does NOT consume a payload.
- align_descend timeout/failure → release current payload.
- Last candidate failure → fallback release (if enabled).
- Single valid target + release_all_payloads_if_only_one_target → release all
  payloads at the same spot without re-goto/re-lock.
- climb timeout does NOT fail the sequence.
- No valid targets → done with released_count=0 (not failed).
"""

from __future__ import annotations

import math
from typing import Any

from .align_descend import AlignDescendAction
from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .payload_release import PayloadReleaseAction
from .result import ActionResult
from .target_lock import TargetLockAction


class DropSequenceAction(ActionModule):
    """Composite action: fly to targets, lock, align-descend, release payloads."""

    def __init__(self) -> None:
        self.reset()

    # ── ActionModule interface ─────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        # ── parse targets (target_slots) ──
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list):
            raise ValueError("targets must be a list")

        max_candidates = int(data.get("max_target_candidates", 3))
        self.valid_targets: list[dict[str, Any]] = []
        for t in raw_targets:
            if not isinstance(t, dict):
                continue
            if not t.get("valid", False):
                continue
            try:
                lx = float(t.get("local_x", t.get("x", float("nan"))))
                ly = float(t.get("local_y", t.get("y", float("nan"))))
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(lx) and math.isfinite(ly)):
                continue
            self.valid_targets.append(dict(t))
            if len(self.valid_targets) >= max_candidates:
                break

        # ── parse payloads ──
        raw_payloads = data.get("payloads", [])
        if not isinstance(raw_payloads, list):
            raise ValueError("payloads must be a list")
        max_payloads = int(data.get("max_payloads", 2))
        self.payloads: list[dict[str, Any]] = []
        for p in raw_payloads[:max_payloads]:
            if not isinstance(p, dict):
                continue
            self.payloads.append(dict(p))
        if not self.payloads:
            raise ValueError("at least one payload required")

        # ── altitude params ──
        self.approach_altitude_m = float(data.get("approach_altitude_m", 2.5))
        self.finish_altitude_m = float(data.get("finish_altitude_m", 1.5))
        self.climb_after_drop_m = float(data.get("climb_after_drop_m", 3.5))

        # ── timeout limits ──
        self.goto_max_updates = int(data.get("goto_max_updates", 120))
        self.target_lock_max_updates = int(data.get("target_lock_max_updates", 50))
        self.align_descend_max_updates = int(data.get("align_descend_max_updates", 250))
        self.climb_max_updates = int(data.get("climb_max_updates", 100))

        # ── behaviour flags ──
        self.fallback_release_when_last_target_failed = bool(
            data.get("fallback_release_when_last_target_failed", True)
        )
        self.release_all_payloads_if_only_one_target = bool(
            data.get("release_all_payloads_if_only_one_target", True)
        )
        self.continue_after_any_failure = bool(
            data.get("continue_after_any_failure", True)
        )

        # ── sub-action param templates ──
        self.goto_params = dict(data.get("goto") or {})
        self._target_lock_params = dict(data.get("target_lock") or {})
        self._align_descend_params = dict(data.get("align_descend") or {})

        self.release_wait_updates = int(data.get("release_wait_updates", 5))

        # ── state ──
        self.phase = "init"
        self.target_index = 0
        self.payload_index = 0
        self.phase_update_count = 0

        self.attempted_targets: list[dict[str, Any]] = []
        self.payload_results: list[dict[str, Any]] = []
        self.released_count = 0
        self.fallback_release_count = 0
        self.skipped_target_count = 0

        self._current_action: ActionModule | None = None
        self._last_actions: list[dict[str, Any]] = []
        self._last_reason = ""
        self._last_detail: dict[str, Any] = {}

        self.started = True
        self.stopped = False
        self._done = False

        self._only_one_target = len(self.valid_targets) == 1

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._make_detail())
        if self._done:
            return ActionResult(
                done=True,
                reason=self._last_reason or "drop_sequence_done",
                detail=self._last_detail,
            )

        data = context or {}

        # ── first call: check for no valid targets ──
        if self.phase == "init":
            if not self.valid_targets:
                self._done = True
                self._last_reason = "no_valid_targets"
                self._last_detail = self._make_detail(status="done")
                return ActionResult(
                    done=True, reason="no_valid_targets", detail=self._last_detail,
                )
            self._start_goto_target()

        # ── phase dispatch ──
        if self.phase == "goto_target":
            return self._handle_goto_target(data)
        if self.phase == "lock_target":
            return self._handle_lock_target(data)
        if self.phase == "align_descend":
            return self._handle_align_descend(data)
        if self.phase == "release_payload":
            return self._handle_release_payload(data)
        if self.phase == "climb_after_release":
            return self._handle_climb(data)

        # unreachable
        self._done = True
        self._last_reason = "invalid_phase"
        self._last_detail = self._make_detail(status="failed")
        return ActionResult(failed=True, reason="invalid_phase", detail=self._last_detail)

    def stop(self) -> None:
        self.stopped = True
        if self._current_action is not None:
            self._current_action.stop()

    def reset(self) -> None:
        self.started = False
        self.stopped = False
        self.valid_targets = []
        self.payloads = []
        self.approach_altitude_m = 2.5
        self.finish_altitude_m = 1.5
        self.climb_after_drop_m = 3.5
        self.goto_max_updates = 120
        self.target_lock_max_updates = 50
        self.align_descend_max_updates = 250
        self.climb_max_updates = 100
        self.fallback_release_when_last_target_failed = True
        self.release_all_payloads_if_only_one_target = True
        self.continue_after_any_failure = True
        self.goto_params = {}
        self._target_lock_params = {}
        self._align_descend_params = {}
        self.release_wait_updates = 5
        self.phase = "init"
        self.target_index = 0
        self.payload_index = 0
        self.phase_update_count = 0
        self.attempted_targets = []
        self.payload_results = []
        self.released_count = 0
        self.fallback_release_count = 0
        self.skipped_target_count = 0
        self._current_action = None
        self._last_actions = []
        self._last_reason = ""
        self._last_detail = {}
        self._done = False
        self._only_one_target = False

    # ── goto_target ────────────────────────────────────────────────────

    def _start_goto_target(self) -> None:
        target = self.valid_targets[self.target_index]
        params: dict[str, Any] = {
            **self.goto_params,
            "x": target.get("x", target.get("local_x")),
            "y": target.get("y", target.get("local_y")),
            "altitude_m": self.approach_altitude_m,
            "skip_if_invalid_target": True,
            "priority": self.goto_params.get("priority", 5),
        }
        action = GotoWaypointAction()
        action.start(params)
        self._current_action = action
        self.phase = "goto_target"
        self.phase_update_count = 0

    def _handle_goto_target(self, context: dict[str, Any]) -> ActionResult:
        self.phase_update_count += 1
        result = self._current_action.update(context)  # type: ignore[union-attr]

        if result.done:
            self._start_lock_target()
            return self._phase_transition_result()
        if result.failed or self.phase_update_count > self.goto_max_updates:
            reason = result.reason if result.failed else "goto_timeout"
            self._record_attempt("goto_target", "failed", reason)
            self.skipped_target_count += 1
            self._advance_target_after_failure()
            return self._phase_transition_result()

        return ActionResult(
            actions=list(result.actions),
            reason="goto_active",
            detail=self._make_detail(),
        )

    # ── lock_target ────────────────────────────────────────────────────

    def _start_lock_target(self) -> None:
        target = self.valid_targets[self.target_index]
        params: dict[str, Any] = {
            **self._target_lock_params,
            "target": {
                "local_x": target.get("local_x", target.get("x")),
                "local_y": target.get("local_y", target.get("y")),
            },
            "skip_if_invalid_target": True,
            "max_updates": self.target_lock_max_updates,
        }
        action = TargetLockAction()
        action.start(params)
        self._current_action = action
        self.phase = "lock_target"
        self.phase_update_count = 0

    def _handle_lock_target(self, context: dict[str, Any]) -> ActionResult:
        self.phase_update_count += 1
        result = self._current_action.update(context)  # type: ignore[union-attr]

        if result.done:
            self._record_attempt("lock_target", "success", result.reason)
            self._start_align_descend()
            return self._phase_transition_result()
        if result.failed:
            self._record_attempt("lock_target", "failed", result.reason)
            self.skipped_target_count += 1
            self._advance_target_after_failure()
            return self._phase_transition_result()

        return ActionResult(
            actions=list(result.actions),
            reason="lock_target_active",
            detail=self._make_detail(),
        )

    # ── align_descend ──────────────────────────────────────────────────

    def _start_align_descend(self) -> None:
        payload = self.payloads[self.payload_index]
        params: dict[str, Any] = dict(self._align_descend_params)
        params["finish_altitude_m"] = self.finish_altitude_m
        params["max_updates"] = self.align_descend_max_updates
        config = dict(params.get("config") or {})
        config["payload_forward_m"] = float(payload.get("payload_forward_m", 0.0))
        config["payload_right_m"] = float(payload.get("payload_right_m", 0.0))
        params["config"] = config
        action = AlignDescendAction()
        action.start(params)
        self._current_action = action
        self.phase = "align_descend"
        self.phase_update_count = 0

    def _handle_align_descend(self, context: dict[str, Any]) -> ActionResult:
        self.phase_update_count += 1
        result = self._current_action.update(context)  # type: ignore[union-attr]
        detail = dict(result.detail)
        command = detail.get("command")

        if result.done:
            self._start_release_payload("aligned_release")
            return self._phase_transition_result()
        if result.failed:
            self._start_release_payload("align_failed_release")
            return self._phase_transition_result()

        actions: list[Any] = []
        if isinstance(command, dict) and command.get("active"):
            actions = [self._flight_command_action(command)]
        return ActionResult(
            actions=actions,
            reason=result.reason,
            detail=self._make_detail(),
        )

    # ── release_payload ────────────────────────────────────────────────

    def _start_release_payload(self, reason: str) -> None:
        payload = self.payloads[self.payload_index]
        target = self.valid_targets[self.target_index] if self.target_index < len(self.valid_targets) else {}
        params: dict[str, Any] = {
            "servo_outputs": list(payload.get("servo_outputs", [])),
            "payload_id": str(payload.get("payload_id", f"payload_{self.payload_index}")),
            "target_id": str(target.get("id", target.get("target_id", f"target_{self.target_index}"))),
            "release_wait_updates": self.release_wait_updates,
            "priority": 3,
        }
        self._current_release_reason = reason
        action = PayloadReleaseAction()
        action.start(params)
        self._current_action = action
        self.phase = "release_payload"
        self.phase_update_count = 0

    def _handle_release_payload(self, context: dict[str, Any]) -> ActionResult:
        self.phase_update_count += 1
        result = self._current_action.update(context)  # type: ignore[union-attr]

        if result.done:
            target = self.valid_targets[self.target_index] if self.target_index < len(self.valid_targets) else {}
            reason = getattr(self, "_current_release_reason", "aligned_release")
            is_fallback = reason in ("lock_failed_fallback_release",)
            self.payload_results.append({
                "payload_index": self.payload_index,
                "payload_id": self.payloads[self.payload_index].get("payload_id"),
                "released": True,
                "target_id": target.get("id", target.get("target_id")),
                "target_index": self.target_index,
                "fallback_release": is_fallback,
                "release_reason": reason,
            })
            self.released_count += 1
            if is_fallback:
                self.fallback_release_count += 1
            self._advance_after_payload()
            # Pass through sub-action result (includes set_servo hold action)
            return ActionResult(
                actions=list(result.actions),
                done=result.done,
                failed=result.failed,
                reason=result.reason,
                detail=self._make_detail(),
            )

        return ActionResult(
            actions=list(result.actions),
            reason=result.reason or "release_active",
            detail=self._make_detail(),
        )

    # ── climb_after_release ────────────────────────────────────────────

    def _start_climb(self) -> None:
        target = self.valid_targets[self.target_index] if self.target_index < len(self.valid_targets) else {}
        params: dict[str, Any] = {
            "x": target.get("x", target.get("local_x", 0.0)),
            "y": target.get("y", target.get("local_y", 0.0)),
            "altitude_m": self.climb_after_drop_m,
            "waypoint_mode": self.goto_params.get("waypoint_mode", "field"),
            "yaw_mode": self.goto_params.get("yaw_mode", "field_heading"),
            "tolerance_xy_m": 0.7,
            "tolerance_z_m": 0.5,
            "min_hold_updates": 1,
            "priority": self.goto_params.get("priority", 5),
        }
        action = GotoWaypointAction()
        action.start(params)
        self._current_action = action
        self.phase = "climb_after_release"
        self.phase_update_count = 0

    def _handle_climb(self, context: dict[str, Any]) -> ActionResult:
        self.phase_update_count += 1
        result = self._current_action.update(context)  # type: ignore[union-attr]

        if result.done or self.phase_update_count > self.climb_max_updates:
            self._advance_to_next_cycle()
            return self._phase_transition_result()

        return ActionResult(
            actions=list(result.actions),
            reason="climb_active",
            detail=self._make_detail(),
        )

    # ── advance logic ──────────────────────────────────────────────────

    def _advance_target_after_failure(self) -> None:
        """Called after goto or lock failure — payload NOT consumed."""
        next_target = self.target_index + 1

        if next_target < len(self.valid_targets):
            # more targets: try next with same payload
            self.target_index = next_target
            self._start_goto_target()
            return

        # last target failed
        if self.fallback_release_when_last_target_failed:
            self._start_release_payload("lock_failed_fallback_release")
            return

        # no fallback: consume this payload slot without release
        self._advance_to_next_cycle()

    def _advance_after_payload(self) -> None:
        """Called after a successful payload release.

        Increments payload_index (the payload has been consumed).
        Always starts climb; _advance_to_next_cycle handles target advance.
        """
        self.payload_index += 1

        if self.payload_index >= len(self.payloads):
            # no more payloads: advance target and finish
            self.target_index += 1
            self._finish_done()
            return

        # more payloads remain — climb before next action
        self._start_climb()

    def _advance_to_next_cycle(self) -> None:
        """Called after climb (or fallback no-release).

        payload_index was already incremented by _advance_after_payload.
        Advance target_index (unless single-target release_all) and decide next step.
        """
        if self.release_all_payloads_if_only_one_target and self._only_one_target:
            # single target: release remaining payloads at same spot
            if self.payload_index < len(self.payloads):
                self._start_release_payload("single_target_release_all")
                return
            self._finish_done()
            return

        # normal: advance both indices
        self.target_index += 1

        if (self.payload_index < len(self.payloads)
                and self.target_index < len(self.valid_targets)):
            self._start_goto_target()
            return

        self._finish_done()

    def _finish_done(self) -> None:
        self._done = True
        self._last_reason = "drop_sequence_done"
        self._last_detail = self._make_detail(status="done")

    # ── helpers ────────────────────────────────────────────────────────

    def _record_attempt(
        self, phase: str, status: str, reason: str,
    ) -> None:
        target = self.valid_targets[self.target_index] if self.target_index < len(self.valid_targets) else {}
        self.attempted_targets.append({
            "target_index": self.target_index,
            "target_id": str(target.get("id", target.get("target_id", f"target_{self.target_index}"))),
            "payload_id": str(self.payloads[self.payload_index].get("payload_id", "")),
            "phase": phase,
            "status": status,
            "reason": reason,
            "consumed_payload": status == "success" or phase in (
                "align_descend", "release_payload",
            ),
        })

    def _phase_transition_result(self) -> ActionResult:
        """Return a neutral result during phase transitions."""
        return ActionResult(
            reason=f"transition_to_{self.phase}",
            detail=self._make_detail(),
        )

    def _flight_command_action(self, command: dict[str, Any]) -> dict[str, Any]:
        """Wrap AlignDescend flight command in Dispatcher envelope."""
        return {
            "action_type": "flight_command",
            "params": command,
            "key": f"drop_sequence_align_payload_{self.payload_index}",
            "once": False,
            "priority": self.goto_params.get("priority", 5),
        }

    def _make_detail(self, *, status: str = "") -> dict[str, Any]:
        detail: dict[str, Any] = {
            "status": status or self.phase,
            "released_count": self.released_count,
            "fallback_release_count": self.fallback_release_count,
            "skipped_target_count": self.skipped_target_count,
            "attempted_targets": list(self.attempted_targets),
            "payload_results": list(self.payload_results),
            "current": {
                "phase": self.phase,
                "target_index": self.target_index,
                "payload_index": self.payload_index,
                "phase_update_count": self.phase_update_count,
            },
            "valid_target_count": len(self.valid_targets),
            "total_payload_count": len(self.payloads),
        }
        return detail
