"""Atomic GPS projection of detections from the current view."""
from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from guidance.capture_projection import detection_pose, normalized_detection_error, scene_detections
from guidance.target_projection import GpsProjectionCamera, GpsProjectionError, GpsTargetProjector

from .base import ActionModule
from .result import ActionResult


class GpsCaptureViewAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.class_names = {str(value) for value in data.get("class_names", [])} or None
        self.min_confidence = float(data.get("min_confidence", 0.35))
        self.source_waypoint = str(data.get("source_waypoint", "view"))
        camera = dict(data.get("camera") or {})
        camera.setdefault("fov_x_deg", 51.3)
        camera.setdefault("fov_y_deg", 39.6)
        self.projector = GpsTargetProjector(GpsProjectionCamera(**camera))
        self.started, self.stopped, self.done = True, False, False
        self.last_detail: dict[str, Any] = {}

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", output=dict(self.last_detail), detail=self.last_detail)
        if self.done:
            return ActionResult(done=True, reason="gps_view_captured", output=dict(self.last_detail), detail=self.last_detail)
        data = context or {}
        detections, width, height = scene_detections(data)
        estimates, rejected = [], {}
        for detection in detections:
            class_name = str(detection.get("class_name") or "")
            if self.class_names is not None and class_name not in self.class_names:
                rejected["class_filtered"] = rejected.get("class_filtered", 0) + 1
                continue
            try:
                confidence = float(detection.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = math.nan
            error = normalized_detection_error(detection, width, height)
            pose = detection_pose(detection, data)
            if not math.isfinite(confidence) or confidence < self.min_confidence:
                reason = "confidence_filtered"
            elif error is None:
                reason = "missing_ex_ey"
            elif pose is None:
                reason = "invalid_capture_telemetry"
            else:
                try:
                    estimate = self.projector.project(
                        **pose, ex=error[0], ey=error[1], class_name=class_name,
                        confidence=confidence, track_id=_optional_int(detection.get("track_id")),
                        frame_id=_optional_int(detection.get("frame_id")),
                        timestamp=_optional_float(detection.get("timestamp")),
                        source_waypoint=self.source_waypoint,
                    )
                    estimates.append(asdict(estimate))
                    continue
                except (GpsProjectionError, TypeError, ValueError):
                    reason = "projection_failed"
            rejected[reason] = rejected.get(reason, 0) + 1
        self.last_detail = {"raw_estimates": estimates, "count": len(estimates),
                            "source_waypoint": self.source_waypoint,
                            "rejected_by_reason": rejected, "coordinate_frame": "GLOBAL"}
        self.done = True
        return ActionResult(done=True, reason="gps_view_captured", output=dict(self.last_detail), detail=self.last_detail)

    def stop(self) -> None: self.stopped = True

    def reset(self) -> None:
        self.started = self.stopped = self.done = False
        self.last_detail = {}


def _optional_int(value: Any) -> int | None:
    try: return None if value is None else int(value)
    except (TypeError, ValueError): return None


def _optional_float(value: Any) -> float | None:
    try: return None if value is None else float(value)
    except (TypeError, ValueError): return None
