"""GPS-first reconnaissance area scan with per-frame danger-sign ranking."""
from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .result import ActionResult


DANGER_SIGN_CLASS_NAMES = [
    "baozha", "shenghua", "yiran", "fangshe", "buran",
    "fushi", "youdu", "yushi", "ziran", "ciji",
]


class GpsReconAreaScanAction(ActionModule):
    """Fly a fixed FIELD route and rank permitted signs from unique scene frames."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        raw_waypoints = data.get("waypoints")
        if not isinstance(raw_waypoints, list) or len(raw_waypoints) != 4:
            raise ValueError("waypoints must contain exactly four FIELD waypoints")
        self.waypoints = [self._waypoint(item, index) for index, item in enumerate(raw_waypoints)]
        self.waypoint_mode = str(data.get("waypoint_mode", "field")).strip().lower()
        self.target_frame = str(data.get("target_frame", "global")).strip().lower()
        self.yaw_mode = str(data.get("yaw_mode", "field_heading")).strip().lower()
        if self.waypoint_mode != "field":
            raise ValueError("gps_recon_area_scan requires waypoint_mode=field")
        if self.target_frame != "global":
            raise ValueError("gps_recon_area_scan requires target_frame=global")
        if self.yaw_mode != "field_heading":
            raise ValueError("gps_recon_area_scan requires yaw_mode=field_heading")
        raw_indices = data.get("scoring_target_indices", [1, 3])
        if not isinstance(raw_indices, list) or any(type(value) is not int for value in raw_indices):
            raise ValueError("scoring_target_indices must be a list of waypoint target indices")
        self.scoring_target_indices = list(raw_indices)
        if not self.scoring_target_indices or any(index < 0 or index >= len(self.waypoints) for index in self.scoring_target_indices):
            raise ValueError("scoring_target_indices contains an invalid waypoint target index")
        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source != "scene":
            raise ValueError("gps_recon_area_scan requires detection_source=scene")
        self.min_sign_confidence = self._finite_float(data.get("min_sign_confidence", 0.35), "min_sign_confidence")
        self.goto_max_updates = int(data.get("goto_max_updates", 200))
        if self.goto_max_updates < 1:
            raise ValueError("goto_max_updates must be >= 1")
        self.goto_cfg = dict(data.get("goto") or {})
        self.priority = int(data.get("priority", 5))
        self.waypoint_index = 0
        self.goto_updates = 0
        self.goto_action = self._new_goto_action()
        self.class_stats = {name: {"seen_frames": 0, "confidence_sum": 0.0, "confidence_max": 0.0} for name in DANGER_SIGN_CLASS_NAMES}
        self.seen_frame_identities: set[tuple[str, str]] = set()
        self.scored_unique_frame_count = 0
        self.duplicate_frame_count = 0
        self.missing_frame_identity_count = 0
        self.valid_sign_frame_count = 0
        self.started = True
        self.stopped = False
        self.state = "goto"

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail(done=True))
        if self.state == "done":
            return ActionResult(done=True, reason="gps_recon_area_scan_done", detail=self._detail(done=True))
        if self.state == "failed":
            return ActionResult(failed=True, reason="gps_recon_area_scan_failed", detail=self._detail())
        if self.goto_action is None:
            return ActionResult(failed=True, reason="goto_not_initialized", detail=self._detail())

        self.goto_updates += 1
        if self.goto_updates > self.goto_max_updates:
            self.goto_action.stop()
            self.state = "failed"
            return ActionResult(failed=True, reason="goto_timeout", detail=self._detail())

        result = self.goto_action.update(context or {})
        if result.failed:
            self.goto_action.stop()
            self.state = "failed"
            return ActionResult(failed=True, reason="goto_failed", detail=self._detail(extra={"goto": result.detail, "goto_reason": result.reason}))

        # target index describes the segment currently being flown: P0->P1 is 1,
        # P1->P2 is 2, and P2->P3 is 3.  It is intentionally not inferred.
        if self.waypoint_index in self.scoring_target_indices:
            self._sample_scene(context or {})

        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_recon_area_scan_goto", detail=self._detail(extra={"goto": result.detail, "goto_reason": result.reason}))

        if self.waypoint_index == len(self.waypoints) - 1:
            self.state = "done"
            self.goto_action = None
            return ActionResult(done=True, reason="gps_recon_area_scan_done", detail=self._detail(done=True, extra={"goto": result.detail}))

        self.waypoint_index += 1
        self.goto_updates = 0
        self.goto_action = self._new_goto_action()
        return ActionResult(reason="gps_recon_area_scan_next_waypoint", detail=self._detail(extra={"goto": result.detail}))

    def stop(self) -> None:
        self.stopped = True
        if self.goto_action is not None:
            self.goto_action.stop()

    def reset(self) -> None:
        self.waypoints: list[dict[str, float]] = []
        self.waypoint_mode = "field"
        self.target_frame = "global"
        self.yaw_mode = "field_heading"
        self.scoring_target_indices: list[int] = [1, 3]
        self.detection_source = "scene"
        self.min_sign_confidence = 0.35
        self.goto_max_updates = 200
        self.goto_cfg: dict[str, Any] = {}
        self.priority = 5
        self.waypoint_index = 0
        self.goto_updates = 0
        self.goto_action: GotoWaypointAction | None = None
        self.class_stats: dict[str, dict[str, float]] = {}
        self.seen_frame_identities: set[tuple[str, str]] = set()
        self.scored_unique_frame_count = 0
        self.duplicate_frame_count = 0
        self.missing_frame_identity_count = 0
        self.valid_sign_frame_count = 0
        self.started = False
        self.stopped = False
        self.state = "idle"

    def _new_goto_action(self) -> GotoWaypointAction:
        waypoint = self.waypoints[self.waypoint_index]
        params = {
            **self.goto_cfg,
            "x": waypoint["x"], "y": waypoint["y"], "altitude_m": waypoint["altitude_m"],
            "waypoint_mode": "field", "target_frame": "global", "yaw_mode": "field_heading",
            "priority": self.priority, "key": f"gps_recon_area_scan_p{self.waypoint_index}",
        }
        action = GotoWaypointAction()
        action.start(params)
        return action

    def _sample_scene(self, context: dict[str, Any]) -> None:
        scene = context.get("scene")
        if not isinstance(scene, dict):
            self.missing_frame_identity_count += 1
            return
        identity = self._frame_identity(scene)
        if identity is None:
            self.missing_frame_identity_count += 1
            return
        if identity in self.seen_frame_identities:
            self.duplicate_frame_count += 1
            return
        self.seen_frame_identities.add(identity)
        self.scored_unique_frame_count += 1
        best: dict[str, float] = {}
        detections = scene.get("detections")
        for detection in detections if isinstance(detections, list) else []:
            if not isinstance(detection, dict):
                continue
            class_name = str(detection.get("class_name") or detection.get("label") or "")
            if class_name not in self.class_stats:
                continue
            try:
                confidence = float(detection.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(confidence) or confidence < self.min_sign_confidence:
                continue
            best[class_name] = max(best.get(class_name, -math.inf), confidence)
        if best:
            self.valid_sign_frame_count += 1
        for class_name, confidence in best.items():
            stats = self.class_stats[class_name]
            stats["seen_frames"] += 1
            stats["confidence_sum"] += confidence
            stats["confidence_max"] = max(stats["confidence_max"], confidence)

    @staticmethod
    def _frame_identity(scene: dict[str, Any]) -> tuple[str, str] | None:
        for name in ("frame_id", "source_time_s", "timestamp"):
            value = scene.get(name)
            if value is not None and value != "":
                return name, str(value)
        return None

    def _ranking(self) -> list[dict[str, Any]]:
        order = {name: index for index, name in enumerate(DANGER_SIGN_CLASS_NAMES)}
        rows = []
        for class_name in DANGER_SIGN_CLASS_NAMES:
            stats = self.class_stats[class_name]
            seen_frames = int(stats["seen_frames"])
            confidence_sum = float(stats["confidence_sum"])
            rows.append({
                "class_name": class_name, "seen_frames": seen_frames,
                "confidence_sum": confidence_sum,
                "confidence_mean": confidence_sum / seen_frames if seen_frames else 0.0,
                "confidence_max": float(stats["confidence_max"]),
                "hit_ratio": seen_frames / self.scored_unique_frame_count if self.scored_unique_frame_count else 0.0,
            })
        rows.sort(key=lambda item: (-item["confidence_sum"], -item["seen_frames"], -item["confidence_max"], order[item["class_name"]]))
        for rank, item in enumerate(rows, start=1):
            item["rank"] = rank
        return rows

    def _detail(self, *, done: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        detail = {
            "ranking_mode": True, "ranking": self._ranking(), "waypoints": list(self.waypoints),
            "waypoint_index": self.waypoint_index, "current_scoring_segment": self.waypoint_index in self.scoring_target_indices,
            "scoring_target_indices": list(self.scoring_target_indices),
            "scan_summary": {
                "scored_unique_frame_count": self.scored_unique_frame_count,
                "duplicate_frame_count": self.duplicate_frame_count,
                "missing_frame_identity_count": self.missing_frame_identity_count,
                "valid_sign_frame_count": self.valid_sign_frame_count,
            },
        }
        if done:
            detail["done"] = True
        detail.update(extra or {})
        return detail

    @staticmethod
    def _waypoint(value: Any, index: int) -> dict[str, float]:
        if not isinstance(value, dict):
            raise ValueError(f"waypoints[{index}] must be an object")
        return {name: GpsReconAreaScanAction._finite_float(value.get(name), f"waypoints[{index}].{name}") for name in ("x", "y", "altitude_m")}

    @staticmethod
    def _finite_float(value: Any, name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be finite") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{name} must be finite")
        return parsed
