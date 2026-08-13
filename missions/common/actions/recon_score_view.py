"""Atomic, stationary danger-sign observation."""
from __future__ import annotations

import math
from typing import Any

from guidance.recon_ranking import DANGER_SIGN_CLASS_NAMES

from .base import ActionModule
from .result import ActionResult


class ReconScoreViewAction(ActionModule):
    def __init__(self) -> None: self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.capture_updates = max(1, int(data.get("capture_updates", 4)))
        self.max_updates = max(self.capture_updates, int(data.get("max_updates", 40)))
        self.update_count = 0
        self.min_confidence = float(data.get("min_sign_confidence", 0.35))
        self.frames, self.identities = [], set()
        self.started, self.stopped = True, False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started: return ActionResult(failed=True, reason="action_not_started")
        if self.stopped: return ActionResult(done=True, reason="stopped", detail=self._detail())
        self.update_count += 1
        scene = (context or {}).get("scene")
        if isinstance(scene, dict):
            identity = next(((name, str(scene[name])) for name in ("frame_id", "source_time_s", "timestamp")
                             if scene.get(name) not in (None, "")), None)
            if identity is not None and identity not in self.identities:
                self.identities.add(identity)
                best: dict[str, float] = {}
                for detection in scene.get("detections", []):
                    if not isinstance(detection, dict): continue
                    name = str(detection.get("class_name") or detection.get("label") or "")
                    try: confidence = float(detection.get("confidence", 0.0))
                    except (TypeError, ValueError): continue
                    if name in DANGER_SIGN_CLASS_NAMES and math.isfinite(confidence) and confidence >= self.min_confidence:
                        best[name] = max(best.get(name, 0.0), confidence)
                self.frames.append({"identity": list(identity), "best_by_class": best})
        done = len(self.frames) >= self.capture_updates or self.update_count >= self.max_updates
        return ActionResult(done=done, reason="recon_view_scored" if done else "recon_view_capturing",
                            detail=self._detail())

    def _detail(self): return {"frames": list(self.frames), "frame_count": len(self.frames)}
    def stop(self) -> None: self.stopped = True
    def reset(self) -> None:
        self.frames, self.identities = [], set()
        self.capture_updates, self.max_updates, self.update_count, self.min_confidence = 4, 40, 0, 0.35
        self.started = self.stopped = False
