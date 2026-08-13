# Archived behavior-lock source; not importable by production.
"""GPS-only recon: stable GLOBAL arrival followed by timed GLOBAL hover observation."""
from __future__ import annotations

import math
import time
from typing import Any

from .base import ActionModule
from .gps_target_sequence_core import GpsTargetSequenceCore
from .goto_waypoint import GotoWaypointAction
from .result import ActionResult
from .recon_observation_accumulator import ReconObservationAccumulator


class GpsReconSequenceAction(GpsTargetSequenceCore, ActionModule):
    """For each valid target, GLOBAL goto at 2.5m then observe while refreshing that setpoint."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self._goto_action_factory = GotoWaypointAction
        raw = data.get("targets", [])
        if not isinstance(raw, list):
            raise ValueError("targets must be a list")
        self.targets = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or item.get("valid", True) is False:
                continue
            try:
                lat, lon = float(item["lat"]), float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            target = dict(item)
            target.update({"lat": lat, "lon": lon, "target_id": str(item.get("target_id") or item.get("id") or f"recon_{index}")})
            self.targets.append(target)
        self.approach_altitude_m = self._positive_float(data, "approach_altitude_m", 2.5)
        self.observe_duration_s = self._positive_float(data, "observe_duration_s", 2.0)
        self.goto_max_updates = int(data.get("goto_max_updates", 200))
        if self.goto_max_updates < 1:
            raise ValueError("goto_max_updates must be >= 1")
        self.goto_cfg = dict(data.get("goto") or {})
        self.observation_cfg = dict(data.get("observation") or {})
        self.observations = []
        self.target_index = 0
        self.sub_action = None
        self.hover_action = None
        self.observer: ReconObservationAccumulator | None = None
        self.observe_started_monotonic_s: float | None = None
        self.update_count_at_phase = 0
        self._operation_started = False
        self._failed_reason = ""
        self.started = True
        self.stopped = False
        self.phase_history = ["done"] if not self.targets else ["goto"]
        self.phase = "done" if not self.targets else "goto"

    def _sequence_reason(self, event):
        return {"goto": "gps_recon_goto", "operation_start": "gps_recon_observe_start", "next": "gps_recon_next", "done": "gps_recon_sequence_done", "goto_timeout": "goto_timeout", "goto_failed": "goto_failed"}.get(event, event)

    def _sequence_namespace(self): return "gps_recon"

    def _sequence_detail(self, done=False, extra=None):
        detail = {"phase": self.phase, "target_index": self.target_index, "target_count": len(self.targets), "observations": list(self.observations)}
        if self.phase == "operation" and self.targets:
            target = self.targets[self.target_index]
            elapsed = 0.0 if self.observe_started_monotonic_s is None else time.monotonic() - self.observe_started_monotonic_s
            detail.update({"observe_duration_s": self.observe_duration_s, "observe_elapsed_s": elapsed, "hover_target_lat": target["lat"], "hover_target_lon": target["lon"], "hover_target_altitude_m": self.approach_altitude_m, "record_frame_count": self.observer.record_frame_count if self.observer else 0, "valid_sign_frame_count": self.observer.valid_sign_frame_count if self.observer else 0})
        detail.update(extra or {})
        if done: detail["done"] = True
        return detail

    def _action_key(self, phase): return f"gps_recon_{phase}_{self.target_index}"

    def _transition_after_goto(self, target, ctx, actions):
        self._operation_started = False
        return self._transition("operation", "operation_start", actions)

    def _transition_after_operation(self, target, ctx, actions):
        if self.target_index + 1 < len(self.targets):
            self.target_index += 1
            return self._transition("goto", "next", actions)
        self.phase = "done"
        self.sub_action = None
        return ActionResult(
            effects=ActionResult.typed(list(actions or []) + self._stop_actions("sequence_done")),
            done=True,
            reason=self._sequence_reason("done"),
            detail=self._sequence_detail(done=True),
        )

    def _start_operation(self, target):
        self.observer = ReconObservationAccumulator()
        self.observer.start_target(target, self.target_index, self.observation_cfg)
        self.observe_started_monotonic_s = time.monotonic()
        self.hover_action = GotoWaypointAction()
        hover_params = self._goto_params(target, self.approach_altitude_m, "goto")
        # Never completes during the timed observation, so every update refreshes GLOBAL position.
        hover_params.update({"min_hold_updates": 2_147_483_647, "key": self._action_key("hover")})
        self.hover_action.start(hover_params)

    def _update_operation_hook(self, ctx):
        assert self.observer is not None and self.hover_action is not None
        hover = self.hover_action.update(ctx)
        if hover.failed:
            return ActionResult(failed=True, reason="gps_recon_hover_failed", effects=ActionResult.typed(self._stop_actions("hover_failed")), detail=self._sequence_detail())
        altitude_m = self._current_altitude_m(ctx)
        self.observer.sample(altitude_m, ctx)
        elapsed_s = time.monotonic() - self.observe_started_monotonic_s
        if elapsed_s < self.observe_duration_s:
            return ActionResult(effects=ActionResult.typed(hover.actions), reason="gps_recon_observing", detail=self._sequence_detail())
        observation = self.observer.finalize("gps_hover_observation_complete", {"mode": "gps_hover_observe", "target_altitude_m": self.approach_altitude_m, "observe_duration_s": self.observe_duration_s, "observe_elapsed_s": elapsed_s})
        self.observations.append(observation)
        return ActionResult(done=True, reason="gps_recon_observing", effects=ActionResult.typed(hover.actions), detail=self._sequence_detail())

    def _operation_complete(self, target):
        self.hover_action = None
        self.observer = None
        self.observe_started_monotonic_s = None

    @staticmethod
    def _positive_float(data: dict[str, Any], name: str, default: float) -> float:
        try: value = float(data.get(name, default))
        except (TypeError, ValueError) as exc: raise ValueError(f"{name} must be finite and > 0") from exc
        if not math.isfinite(value) or value <= 0: raise ValueError(f"{name} must be finite and > 0")
        return value
