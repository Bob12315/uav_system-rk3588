# Archived behavior-lock source; not importable by production.
from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult
from .align_descend import AlignDescendAction


class VisualLandAction(ActionModule):
    """Composite action: search for YOLO class 'H', lock, then visually descend.

    Phase 1 – SEARCH: look for H detections in scene.detections, select the one
    closest to image centre.  If found with a valid track_id, dispatch
    yolo_lock_target.  If no H is found within search_max_updates, proceed to
    blind descent.

    Phase 2 – DESCENT: delegate to an internal AlignDescendAction configured
    with target_loss_policy='continue_descent'.  When the target is visible the
    internal action computes visual vx/vy/vz; when the target disappears it
    automatically switches to vx=0 vy=0 vz=blind_descend_speed_mps without
    triggering target_lost_timeout.

    The action finishes when the internal AlignDescendAction reaches
    finish_altitude_m (0.3 m default).  On finish (or failure/stop) it outputs
    a zero-velocity flight_command followed by clear_continuous_commands.
    """

    PHASE_SEARCH = "search"
    PHASE_DESCENT = "descent"

    def __init__(self) -> None:
        self.reset()

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        self.class_names: list[str] = list(data.get("class_names", ["H"]))
        self.min_confidence: float = float(data.get("min_confidence", 0.35))
        self.search_max_updates: int = int(data.get("search_max_updates", 8))
        self.finish_altitude_m: float = float(data.get("finish_altitude_m", 0.3))
        self.blind_descend_speed_mps: float = float(data.get("blind_descend_speed_mps", 0.3))
        self.priority: int = int(data.get("priority", 5))

        if self.search_max_updates < 1:
            raise ValueError("search_max_updates must be at least 1")
        if self.finish_altitude_m <= 0.0:
            raise ValueError("finish_altitude_m must be positive")
        if self.blind_descend_speed_mps < 0.0:
            raise ValueError("blind_descend_speed_mps must be non-negative")

        # ── build AlignDescendAction params ──────────────────────────
        align_params: dict[str, Any] = dict(data.get("align_descend") or {})
        if "config" not in align_params:
            align_params["config"] = {}
        # Force the safety-critical settings
        align_params["config"]["target_loss_policy"] = "continue_descent"
        align_params["config"]["target_loss_descend_speed_mps"] = self.blind_descend_speed_mps
        align_params["config"]["require_target_locked"] = bool(
            align_params["config"].get("require_target_locked", False)
        )
        align_params["config"]["altitude_source"] = align_params["config"].get(
            "altitude_source", "local_ned"
        )
        if "finish_altitude_m" not in align_params:
            align_params["finish_altitude_m"] = self.finish_altitude_m
        if "finish_policy" not in align_params:
            align_params["finish_policy"] = "legacy"

        self._align = AlignDescendAction()
        self._align.start(align_params)

        self.phase: str = self.PHASE_SEARCH
        self.search_updates: int = 0
        self._locked_track_id: int | None = None
        self._selected_h: dict[str, Any] | None = None
        self._last_align_result: ActionResult | None = None

        self.started = True
        self.done = False
        self.failed = False
        self.failure_reason: str = ""
        self.update_count: int = 0

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started", effects=ActionResult.typed([]))
        if self.done:
            return ActionResult(effects=ActionResult.typed([]), done=True, reason="visual_land_done",
                                detail=self._last_align_result.detail if self._last_align_result else {})
        if self.failed:
            return ActionResult(effects=ActionResult.typed([]), failed=True, reason=self.failure_reason)

        self.update_count += 1
        data = context or {}

        detections = self._scene_detections(data)

        # ── Phase SEARCH ─────────────────────────────────────────────
        if self.phase == self.PHASE_SEARCH:
            self.search_updates += 1
            best_h = self._select_best_h(detections, data)

            if best_h is not None:
                track_id = self._valid_track_id(best_h)
                if track_id is not None:
                    self._locked_track_id = track_id
                self._selected_h = best_h
                self.phase = self.PHASE_DESCENT

                actions: list[dict[str, Any]] = []
                if self._locked_track_id is not None:
                    actions.append({
                        "action_type": "yolo_lock_target",
                        "params": {"track_id": self._locked_track_id},
                        "key": f"visual_land_lock_{self._locked_track_id}",
                        "once": True,
                        "priority": self.priority,
                    })
                return ActionResult(
                    effects=ActionResult.typed(actions),
                    reason="target_locked_descending",
                    detail={"phase": self.phase, "track_id": self._locked_track_id},
                )

            if self.search_updates >= self.search_max_updates:
                # Search exhausted — proceed to blind descent
                self.phase = self.PHASE_DESCENT
                self._selected_h = None
                # fall through to descent
            else:
                # Still searching — produce zero velocity while hovering
                return ActionResult(
                    effects=ActionResult.typed([]),
                    reason="searching_for_h",
                    detail={
                        "phase": self.phase,
                        "search_update": self.search_updates,
                        "search_max_updates": self.search_max_updates,
                    },
                )

        # ── Phase DESCENT ────────────────────────────────────────────
        best_h = self._select_best_h(detections, data)
        align_ctx = self._build_align_context(data, best_h)
        result = self._align.update(align_ctx)
        self._last_align_result = result

        if result.failed:
            self.failed = True
            self.failure_reason = result.reason or "visual_land_align_failed"
            return ActionResult(
                effects=ActionResult.typed(self._stop_commands()),
                failed=True,
                reason=self.failure_reason,
                detail=result.detail,
            )

        if result.done:
            self.done = True
            return ActionResult(
                effects=ActionResult.typed(self._stop_commands()),
                done=True,
                reason="visual_land_complete",
                detail=result.detail,
            )

        # Still descending — pass through the align result (its detail.command
        # is picked up by the ActionDispatcher).
        return result

    # ------------------------------------------------------------------
    # stop / reset
    # ------------------------------------------------------------------

    def stop(self) -> None:
        if hasattr(self, '_align'):
            self._align.stop()
        self.done = False
        self.failed = False

    def reset(self) -> None:
        self._align = AlignDescendAction()
        self.phase = self.PHASE_SEARCH
        self.search_updates = 0
        self._locked_track_id = None
        self._selected_h = None
        self._last_align_result = None
        self.started = False
        self.done = False
        self.failed = False
        self.failure_reason = ""
        self.update_count = 0
        self.class_names = ["H"]
        self.min_confidence = 0.35
        self.search_max_updates = 8
        self.finish_altitude_m = 0.3
        self.blind_descend_speed_mps = 0.3
        self.priority = 5

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _scene_detections(context: dict[str, Any]) -> list[dict[str, Any]]:
        scene = context.get("scene")
        if not isinstance(scene, dict):
            return []
        dets = scene.get("detections")
        if not isinstance(dets, list):
            return []
        return dets

    def _select_best_h(
        self,
        detections: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return the H detection closest to image centre, or None."""
        scene = (context or {}).get("scene") or {}
        default_img_w = float(scene.get("image_width", 640))
        default_img_h = float(scene.get("image_height", 480))

        best: dict[str, Any] | None = None
        best_dist = float("inf")

        for det in detections:
            if not isinstance(det, dict):
                continue
            if det.get("class_name") not in self.class_names:
                continue
            try:
                conf = float(det.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            if conf < self.min_confidence:
                continue

            # Compute normalised camera error (ex, ey)
            ex: float | None = None
            ey: float | None = None

            if "ex" in det and "ey" in det:
                try:
                    ex = float(det["ex"])
                    ey = float(det["ey"])
                except (TypeError, ValueError):
                    pass

            if (ex is None or ey is None) and "cx" in det and "cy" in det:
                try:
                    cx = float(det["cx"])
                    cy = float(det["cy"])
                    img_w = float(det.get("image_width", default_img_w))
                    img_h = float(det.get("image_height", default_img_h))
                    ex = (cx - img_w / 2.0) / (img_w / 2.0)
                    ey = (cy - img_h / 2.0) / (img_h / 2.0)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

            if ex is None or ey is None:
                continue
            if not math.isfinite(ex) or not math.isfinite(ey):
                continue

            dist = math.sqrt(ex * ex + ey * ey)
            if dist < best_dist:
                best_dist = dist
                best = det

        return best

    @staticmethod
    def _valid_track_id(detection: dict[str, Any]) -> int | None:
        """Return an int track_id if present and >= 0, else None."""
        tid = detection.get("track_id")
        if tid is None:
            return None
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            return None
        if tid_int < 0:
            return None
        return tid_int

    def _build_align_context(
        self,
        context: dict[str, Any],
        best_h: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the context dict for the internal AlignDescendAction."""
        ctx = dict(context)

        if best_h is not None:
            ctx["target_valid"] = True
            ctx["vision_valid"] = True
            ctx["target_locked"] = True

            scene = context.get("scene") or {}
            default_img_w = float(scene.get("image_width", 640))
            default_img_h = float(scene.get("image_height", 480))

            if "ex" in best_h and "ey" in best_h:
                ctx["ex_cam"] = float(best_h["ex"])
                ctx["ey_cam"] = float(best_h["ey"])
            elif "cx" in best_h and "cy" in best_h:
                cx = float(best_h["cx"])
                cy = float(best_h["cy"])
                img_w = float(best_h.get("image_width", default_img_w))
                img_h = float(best_h.get("image_height", default_img_h))
                ctx["ex_cam"] = (cx - img_w / 2.0) / (img_w / 2.0)
                ctx["ey_cam"] = (cy - img_h / 2.0) / (img_h / 2.0)
            else:
                ctx["target_valid"] = False
                ctx["vision_valid"] = False
        else:
            ctx["target_valid"] = False
            ctx["vision_valid"] = False

        return ctx

    def _stop_commands(self) -> list[dict[str, Any]]:
        """Return the zero-velocity + clear actions for a safe exit."""
        return [
            {
                "action_type": "flight_command",
                "params": {
                    "type": "flight_command",
                    "vx_cmd": 0.0,
                    "vy_cmd": 0.0,
                    "vz_cmd": 0.0,
                    "yaw_rate_cmd": 0.0,
                    "enable_body": True,
                    "enable_approach": False,
                    "active": False,
                    "valid": True,
                },
                "key": "visual_land_stop",
                "priority": self.priority,
            },
            {
                "action_type": "clear_continuous_commands",
                "params": {"send_stop_first": True},
                "key": "visual_land_clear",
                "priority": self.priority,
            },
        ]
