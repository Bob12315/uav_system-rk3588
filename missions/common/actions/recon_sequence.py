"""ReconSequenceAction — composite reconnaissance sequence for finish-first mission.

Orchestrates goto → lock → observe_descend → climb for each valid recon target.
Records danger sign detection results per target.

Key safety rules:
- goto failed → skip target, record blank, continue.
- lock failed → skip target, record blank, continue.
- observe timeout/failed → record blank or partial result, continue.
- No valid targets → done, results=[].
- climb timeout does NOT fail the sequence.
- observe→climb and climb→next goto always emit clear_continuous_commands.
"""

from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .recon_descend_observe import ReconDescendObserveAction
from .result import ActionResult
from .target_lock import TargetLockAction


class ReconSequenceAction(ActionModule):
    """Composite action: fly to recon targets, lock, observe, record results."""

    def __init__(self) -> None:
        self.reset()

    # ── ActionModule interface ─────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        # ── parse targets ──
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list):
            raise ValueError("targets must be a list")

        max_targets = int(data.get("max_targets", 5))
        self.valid_targets: list[dict[str, Any]] = []
        for t in raw_targets:
            if not isinstance(t, dict):
                continue
            if not t.get("valid", True):
                continue
            try:
                lx = float(t.get("local_x", t.get("x", float("nan"))))
                ly = float(t.get("local_y", t.get("y", float("nan"))))
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(lx) and math.isfinite(ly)):
                continue
            self.valid_targets.append(dict(t))
            if len(self.valid_targets) >= max_targets:
                break

        # ── altitude params ──
        self.approach_altitude_m = float(data.get("approach_altitude_m", 2.5))
        self.finish_altitude_m = float(data.get("finish_altitude_m", 1.5))
        self.climb_after_observe_m = float(data.get("climb_after_observe_m", 2.5))

        # ── timeout limits ──
        self.goto_max_updates = int(data.get("goto_max_updates", 120))
        self.target_lock_max_updates = int(data.get("target_lock_max_updates", 40))
        self.observe_max_updates = int(data.get("observe_max_updates", 200))
        self.climb_max_updates = int(data.get("climb_max_updates", 100))

        # ── behaviour ──
        self.continue_after_target_failure = bool(
            data.get("continue_after_target_failure", True)
        )

        # ── sub-action param templates ──
        self.goto_params = dict(data.get("goto") or {})
        self._target_lock_params = dict(data.get("target_lock") or {})
        self._observe_params = dict(data.get("observe") or {})

        # ── state ──
        self.phase = "init"
        self.target_index = 0
        self.phase_update_count = 0

        self.results: list[dict[str, Any]] = []
        self.recon_result_items: list[dict[str, Any]] = []
        self.observed_count = 0
        self.blank_count = 0
        self.skipped_count = 0

        self._current_action: ActionModule | None = None
        self._last_reason = ""
        self._last_detail: dict[str, Any] = {}

        self.started = True
        self.stopped = False
        self._done = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._make_detail())
        if self._done:
            return ActionResult(
                done=True,
                reason=self._last_reason or "recon_sequence_done",
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
        if self.phase == "observe_descend":
            return self._handle_observe_descend(data)
        if self.phase == "climb_after_observe":
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
        self.approach_altitude_m = 2.5
        self.finish_altitude_m = 1.5
        self.climb_after_observe_m = 2.5
        self.goto_max_updates = 120
        self.target_lock_max_updates = 40
        self.observe_max_updates = 200
        self.climb_max_updates = 100
        self.continue_after_target_failure = True
        self.goto_params = {}
        self._target_lock_params = {}
        self._observe_params = {}
        self.phase = "init"
        self.target_index = 0
        self.phase_update_count = 0
        self.results = []
        self.recon_result_items = []
        self.observed_count = 0
        self.blank_count = 0
        self.skipped_count = 0
        self._current_action = None
        self._last_reason = ""
        self._last_detail = {}
        self._done = False

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
            self._record_result("goto_failed", reason)
            self._advance_to_next_target()
            actions = [self._clear_continuous_action("goto_failed")]
            return ActionResult(
                actions=actions,
                reason=f"transition_to_{self.phase}",
                detail=self._make_detail(),
            )

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
            self._start_observe_descend()
            return self._phase_transition_result()
        if result.failed:
            self._record_result("target_lock_failed", result.reason)
            self._advance_to_next_target()
            return self._phase_transition_result()

        return ActionResult(
            actions=list(result.actions),
            reason="lock_target_active",
            detail=self._make_detail(),
        )

    # ── observe_descend ────────────────────────────────────────────────

    def _start_observe_descend(self) -> None:
        target = self.valid_targets[self.target_index]
        params: dict[str, Any] = {
            **self._observe_params,
            "target": {
                "id": str(target.get("id", target.get("target_id", f"recon_{self.target_index}"))),
                "local_x": target.get("local_x", target.get("x")),
                "local_y": target.get("local_y", target.get("y")),
            },
            "target_index": self.target_index,
            "finish_altitude_m": self.finish_altitude_m,
            "record_start_altitude_m": float(
                self._observe_params.get("record_start_altitude_m", 2.0)
            ),
        }
        # Build align_descend sub-params
        align_params = dict(self._observe_params.get("align_descend") or {})
        align_params["finish_altitude_m"] = self.finish_altitude_m
        align_params["max_updates"] = self.observe_max_updates
        params["align_descend"] = align_params

        action = ReconDescendObserveAction()
        action.start(params)
        self._current_action = action
        self.phase = "observe_descend"
        self.phase_update_count = 0

    def _handle_observe_descend(self, context: dict[str, Any]) -> ActionResult:
        self.phase_update_count += 1
        result = self._current_action.update(context)  # type: ignore[union-attr]

        is_timeout = self.phase_update_count > self.observe_max_updates

        if result.done or result.failed or is_timeout:
            # If timeout is triggered by outer limit (not sub-action itself),
            # stop the sub-action to release resources.
            if is_timeout and not (result.done or result.failed):
                if self._current_action is not None:
                    self._current_action.stop()

            # Record observation result from ReconDescendObserveAction detail
            detail = dict(result.detail)
            status = detail.get("status", "blank_or_uncertain")
            content = detail.get("content", "blank")
            confidence = float(detail.get("confidence", 0.0))

            if result.failed and status not in ("detected",):
                status = "blank_or_uncertain"
                content = "blank"
                confidence = 0.0

            self._record_observation(status, content, confidence, detail)

            # Start climb (or finish if last target)
            self._start_climb()

            # Pass through child zero flight_command, THEN clear continuous.
            actions = self._actions_with_child_then_clear(
                result.actions, "after_observe",
            )
            return ActionResult(
                actions=actions,
                reason=f"transition_to_{self.phase}",
                detail=self._make_detail(),
            )

        # Active: pass through flight_command actions
        return ActionResult(
            actions=list(result.actions),
            reason=result.reason or "observe_active",
            detail=self._make_detail(),
        )

    # ── climb_after_observe ────────────────────────────────────────────

    def _start_climb(self) -> None:
        target = self.valid_targets[self.target_index] if self.target_index < len(self.valid_targets) else {}
        params: dict[str, Any] = {
            "x": target.get("x", target.get("local_x", 0.0)),
            "y": target.get("y", target.get("local_y", 0.0)),
            "altitude_m": self.climb_after_observe_m,
            "waypoint_mode": self.goto_params.get("waypoint_mode", "absolute"),
            "yaw_mode": self.goto_params.get("yaw_mode", "field_heading"),
            "tolerance_xy_m": 0.7,
            "tolerance_z_m": 0.5,
            "min_hold_updates": 1,
            "priority": self.goto_params.get("priority", 5),
        }
        action = GotoWaypointAction()
        action.start(params)
        self._current_action = action
        self.phase = "climb_after_observe"
        self.phase_update_count = 0

    def _handle_climb(self, context: dict[str, Any]) -> ActionResult:
        self.phase_update_count += 1
        result = self._current_action.update(context)  # type: ignore[union-attr]

        if result.done or self.phase_update_count > self.climb_max_updates:
            self._advance_to_next_target()
            # Clear stale continuous commands before next navigation phase
            actions = [self._clear_continuous_action("before_goto")]
            return ActionResult(
                actions=actions,
                reason=f"transition_to_{self.phase}",
                detail=self._make_detail(),
            )

        return ActionResult(
            actions=list(result.actions),
            reason="climb_active",
            detail=self._make_detail(),
        )

    # ── advance logic ──────────────────────────────────────────────────

    def _advance_to_next_target(self) -> None:
        """Move to next target or finish the sequence."""
        self.target_index += 1
        if self.target_index < len(self.valid_targets):
            self._start_goto_target()
            return
        self._finish_done()

    def _finish_done(self) -> None:
        self._done = True
        self._last_reason = "recon_sequence_done"
        self._last_detail = self._make_detail(status="done")

    # ── result recording ───────────────────────────────────────────────

    def _record_result(self, status: str, reason: str) -> None:
        """Record a skipped/failed target result — also enters recon_result_items."""
        target = self.valid_targets[self.target_index] if self.target_index < len(self.valid_targets) else {}
        item = {
            "target_index": self.target_index,
            "target_id": str(target.get("id", target.get("target_id", f"recon_{self.target_index}"))),
            "status": "blank_or_uncertain",
            "content": "blank",
            "confidence": 0.0,
            "reason": status,
        }
        self.results.append(item)
        self.recon_result_items.append(dict(item))
        self.skipped_count += 1

    def _record_observation(
        self, status: str, content: str, confidence: float,
        observe_detail: dict[str, Any],
    ) -> None:
        """Record an observation result (detected or blank)."""
        target = self.valid_targets[self.target_index] if self.target_index < len(self.valid_targets) else {}
        target_id = str(target.get("id", target.get("target_id", f"recon_{self.target_index}")))

        result_item = {
            "target_index": self.target_index,
            "target_id": target_id,
            "status": status,
            "content": content,
            "confidence": confidence,
            "reason": observe_detail.get("align_reason", "observe_done"),
        }
        self.results.append(result_item)
        # All processed targets enter recon_result_items (detected + blank)
        self.recon_result_items.append(dict(result_item))

        if status == "detected":
            self.observed_count += 1
        else:
            self.blank_count += 1

    # ── helpers ────────────────────────────────────────────────────────

    def _phase_transition_result(self) -> ActionResult:
        """Return a neutral result during phase transitions."""
        return ActionResult(
            reason=f"transition_to_{self.phase}",
            detail=self._make_detail(),
        )

    def _actions_with_child_then_clear(
        self, child_actions: list[Any] | None, suffix: str,
    ) -> list[Any]:
        """Pass through child actions, then append clear_continuous_commands.

        Ensures sub-action zero flight_command is emitted before clear.
        """
        actions = list(child_actions or [])
        actions.append(self._clear_continuous_action(suffix))
        return actions

    def _clear_continuous_action(self, key_suffix: str) -> dict[str, Any]:
        """Build a clear_continuous_commands action for phase transitions.

        Key includes target_index and phase_update_count so every
        transition within the same run produces a unique key.
        """
        return {
            "action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": False},
            "key": (
                f"recon_sequence_clear_{key_suffix}"
                f"_t{self.target_index}_u{self.phase_update_count}"
            ),
            "once": True,
            "priority": 10,
        }

    def _make_detail(self, *, status: str = "") -> dict[str, Any]:
        detail: dict[str, Any] = {
            "status": status or self.phase,
            "observed_count": self.observed_count,
            "blank_count": self.blank_count,
            "skipped_count": self.skipped_count,
            "results": list(self.results),
            "recon_result_items": list(self.recon_result_items),
            "current": {
                "phase": self.phase,
                "target_index": self.target_index,
                "phase_update_count": self.phase_update_count,
            },
            "valid_target_count": len(self.valid_targets),
        }
        return detail
