from __future__ import annotations

import math
from typing import Any

from .align_descend import AlignDescendAction
from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .result import ActionResult
from .target_lock import TargetLockAction


class ReconInspectTargetsAction(ActionModule):
    """Inspect localized buckets sequentially while isolating per-target failures."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        targets = data.get("targets", [])
        if not isinstance(targets, list):
            raise ValueError("targets must be a list")
        self.max_targets = int(data.get("max_targets", 5))
        if self.max_targets < 1:
            raise ValueError("max_targets must be at least 1")
        self.targets = list(targets[: self.max_targets])
        self.inspect_altitude_m = float(data.get("inspect_altitude_m", 3.0))
        self.align_finish_altitude_m = float(data.get("align_finish_altitude_m", 2.0))
        self.waypoint_mode = str(data.get("waypoint_mode", "absolute"))
        self.yaw_mode = str(data.get("yaw_mode", "field_heading"))
        self.goto_tolerance_xy_m = float(data.get("goto_tolerance_xy_m", 0.35))
        self.goto_tolerance_z_m = float(data.get("goto_tolerance_z_m", 0.35))
        self.goto_min_hold_updates = int(data.get("goto_min_hold_updates", 1))
        self.target_lock_params = dict(data.get("target_lock") or {})
        self.align_params = dict(data.get("align_descend") or {})
        self.capture_params = dict(data.get("capture_sign") or {})
        self.continue_on_target_failed = self._bool(data.get("continue_on_target_failed", True), "continue_on_target_failed")
        self.continue_when_no_sign = self._bool(data.get("continue_when_no_sign", True), "continue_when_no_sign")
        self.priority = int(data.get("priority", 5))
        capture_updates = int(self.capture_params.get("capture_updates", 8))
        if capture_updates < 1:
            raise ValueError("capture_sign.capture_updates must be at least 1")
        self.capture_updates = capture_updates
        self.min_sign_confidence = float(self.capture_params.get("min_sign_confidence", 0.35))
        self.sign_class_names = {str(value) for value in self.capture_params.get("sign_class_names", [])}
        self.detection_source = str(self.capture_params.get("detection_source", "scene"))
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("capture_sign.detection_source must be scene or perception")
        self.started = True
        self.stopped = False
        self.state = "init"
        self.current_target_index = 0
        self.recon_report = []
        self.child = None
        self.current_report = None
        self.capture_count = 0
        self.best_sign = None
        self.last_result = None

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail())
        if self.last_result is not None:
            return self.last_result
        if not self.targets:
            self.last_result = ActionResult(failed=True, reason="no_recon_targets", detail=self._detail())
            return self.last_result

        data = context or {}
        # Transitions are handled in one update until a child needs another tick.
        for _ in range(8):
            if self.state == "init":
                if not self._start_target():
                    continue
            if self.state in {"goto_target", "target_lock", "align_descend"}:
                assert self.child is not None
                result = self.child.update(data)
                if result.failed:
                    status = {"goto_target": "goto_failed", "target_lock": "lock_failed", "align_descend": "align_failed"}[self.state]
                    self._finish_failed_target(status, result.reason, result.detail)
                    if not self.continue_on_target_failed:
                        return self._fail(result.reason)
                    return ActionResult(actions=[], reason="next_target", detail=self._detail())
                if result.done:
                    if self.current_report is not None:
                        key = {"goto_target": "goto_reason", "target_lock": "lock_reason", "align_descend": "align_reason"}[self.state]
                        self.current_report[key] = result.reason
                        if self.state == "align_descend":
                            self.current_report["height_m"] = result.detail.get("height_m")
                    self._advance_child_stage()
                    # Every child transition yields an empty command tick so no
                    # position/velocity command leaks into the following stage.
                    return ActionResult(actions=[], reason=self.state, detail=self._detail())
                return ActionResult(actions=list(result.actions), reason=result.reason, detail=self._detail(result.detail))
            if self.state == "capture_sign":
                self._capture(data)
                self.capture_count += 1
                if self.capture_count < self.capture_updates:
                    return ActionResult(actions=[], reason="capture_sign", detail=self._detail())
                self._finish_capture()
                if self.state == "done":
                    return self._done()
                return ActionResult(actions=[], reason="next_target", detail=self._detail())
            if self.state == "next_target":
                self.current_target_index += 1
                self.child = None
                self.current_report = None
                self.state = "init"
                if self.current_target_index >= len(self.targets):
                    return self._done()
                continue
            if self.state == "done":
                return self._done()
        return ActionResult(actions=[], reason=self.state, detail=self._detail())

    def stop(self) -> None:
        self.stopped = True
        if self.child is not None:
            self.child.stop()

    def reset(self) -> None:
        self.targets: list[Any] = []
        self.max_targets = 5
        self.inspect_altitude_m = 3.0
        self.align_finish_altitude_m = 2.0
        self.waypoint_mode = "absolute"
        self.yaw_mode = "field_heading"
        self.goto_tolerance_xy_m = 0.35
        self.goto_tolerance_z_m = 0.35
        self.goto_min_hold_updates = 1
        self.target_lock_params: dict[str, Any] = {}
        self.align_params: dict[str, Any] = {}
        self.capture_params: dict[str, Any] = {}
        self.capture_updates = 8
        self.min_sign_confidence = 0.35
        self.sign_class_names: set[str] = set()
        self.detection_source = "scene"
        self.continue_on_target_failed = True
        self.continue_when_no_sign = True
        self.priority = 5
        self.started = False
        self.stopped = False
        self.state = "init"
        self.current_target_index = 0
        self.recon_report: list[dict[str, Any]] = []
        self.child: ActionModule | None = None
        self.current_report: dict[str, Any] | None = None
        self.capture_count = 0
        self.best_sign: dict[str, Any] | None = None
        self.last_result: ActionResult | None = None

    def _start_target(self) -> bool:
        if self.current_target_index >= len(self.targets):
            self.state = "done"
            return False
        target = self.targets[self.current_target_index]
        if not isinstance(target, dict) or self._xy(target) is None:
            report = self._report_base(target if isinstance(target, dict) else {})
            report["status"] = "skipped_invalid_target"
            self.recon_report.append(report)
            self.state = "next_target"
            return False
        x, y = self._xy(target) or (0.0, 0.0)
        self.current_report = self._report_base(target)
        child = GotoWaypointAction()
        child.start({"x": x, "y": y, "altitude_m": self.inspect_altitude_m,
                     "waypoint_mode": self.waypoint_mode, "yaw_mode": self.yaw_mode,
                     "tolerance_xy_m": self.goto_tolerance_xy_m, "tolerance_z_m": self.goto_tolerance_z_m,
                     "min_hold_updates": self.goto_min_hold_updates, "priority": self.priority,
                     "key": f"recon_inspect_goto_{self.current_target_index}"})
        self.child = child
        self.state = "goto_target"
        return True

    def _advance_child_stage(self) -> None:
        assert self.current_report is not None
        target = self.targets[self.current_target_index]
        if self.state == "goto_target":
            params = dict(self.target_lock_params)
            params["target"] = target
            params.setdefault("priority", self.priority)
            params["key"] = f"recon_inspect_lock_{self.current_target_index}"
            child = TargetLockAction()
            child.start(params)
            self.child = child
            self.state = "target_lock"
        elif self.state == "target_lock":
            params = dict(self.align_params)
            config = dict(params.get("config") or {})
            config["payload_offset_enabled"] = False
            params["config"] = config
            params["finish_altitude_m"] = self.align_finish_altitude_m
            child = AlignDescendAction()
            child.start(params)
            self.child = child
            self.state = "align_descend"
        else:
            self.child = None
            self.capture_count = 0
            self.best_sign = None
            self.state = "capture_sign"

    def _capture(self, context: dict[str, Any]) -> None:
        detections: list[Any] = []
        if self.detection_source == "scene":
            scene = context.get("scene")
            if isinstance(scene, dict) and isinstance(scene.get("detections"), list):
                detections = scene["detections"]
        else:
            perception = context.get("perception")
            if isinstance(perception, dict):
                detections = [perception]
        for detection in detections:
            if not isinstance(detection, dict):
                continue
            class_name = str(detection.get("class_name") or detection.get("label") or "")
            try:
                confidence = float(detection.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            if class_name not in self.sign_class_names or confidence < self.min_sign_confidence:
                continue
            if self.best_sign is None or confidence > float(self.best_sign.get("confidence", 0.0)):
                self.best_sign = dict(detection)
                self.best_sign["class_name"] = class_name
                self.best_sign["confidence"] = confidence

    def _finish_capture(self) -> None:
        assert self.current_report is not None
        if self.best_sign is None:
            self.current_report.update({"status": "no_sign", "sign_class": "", "confidence": 0.0})
            self.recon_report.append(self.current_report)
            if not self.continue_when_no_sign:
                self.state = "done"
                return
        else:
            sign = self.best_sign
            bbox = sign.get("bbox")
            if bbox is None and all(key in sign for key in ("x1", "y1", "x2", "y2")):
                bbox = [sign["x1"], sign["y1"], sign["x2"], sign["y2"]]
            self.current_report.update({"status": "detected", "sign_class": sign["class_name"],
                                        "confidence": sign["confidence"], "bbox": bbox,
                                        "track_id": sign.get("track_id"), "raw_detection": sign})
            self.recon_report.append(self.current_report)
        self.state = "next_target"

    def _finish_failed_target(self, status: str, reason: str, detail: dict[str, Any]) -> None:
        if self.current_report is None:
            self.current_report = self._report_base({})
        key = {"goto_failed": "goto_reason", "lock_failed": "lock_reason", "align_failed": "align_reason"}[status]
        self.current_report.update({"status": status, key: reason})
        if status == "align_failed":
            self.current_report["height_m"] = detail.get("height_m")
        self.recon_report.append(self.current_report)
        self.state = "next_target"
        self.child = None

    def _report_base(self, target: dict[str, Any]) -> dict[str, Any]:
        xy = self._xy(target)
        x, y = xy if xy is not None else (None, None)
        return {"target_id": str(target.get("id") or target.get("target_id") or f"target_{self.current_target_index}"),
                "rank": target.get("rank", self.current_target_index + 1),
                "class_name": str(target.get("class_name") or "bucket"),
                "local_x": x, "local_y": y, "field_x": x, "field_y": y,
                "status": "capture_failed", "sign_class": "", "confidence": 0.0,
                "bbox": None, "track_id": None, "goto_reason": "", "lock_reason": "",
                "align_reason": "", "height_m": None}

    def _detail(self, child_detail: dict[str, Any] | None = None) -> dict[str, Any]:
        detected = sum(item.get("status") == "detected" for item in self.recon_report)
        no_sign = sum(item.get("status") == "no_sign" for item in self.recon_report)
        failed = len(self.recon_report) - detected - no_sign
        detail: dict[str, Any] = {"recon_report": list(self.recon_report), "inspected_targets": list(self.recon_report),
            "target_count": self.max_targets, "input_target_count": len(self.targets),
            "inspected_count": len(self.recon_report), "detected_sign_count": detected,
            "no_sign_count": no_sign, "failed_count": failed,
            "current_target_index": self.current_target_index, "state": self.state, "done": self.state == "done"}
        if child_detail is not None:
            detail["child_detail"] = child_detail
        return detail

    def _done(self) -> ActionResult:
        self.state = "done"
        self.last_result = ActionResult(done=True, reason="recon_inspection_complete", detail=self._detail())
        return self.last_result

    def _fail(self, reason: str) -> ActionResult:
        self.last_result = ActionResult(failed=True, reason=reason, detail=self._detail())
        return self.last_result

    @staticmethod
    def _xy(target: dict[str, Any]) -> tuple[float, float] | None:
        try:
            x = float(target["local_x"] if "local_x" in target else target["x"])
            y = float(target["local_y"] if "local_y" in target else target["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return (x, y) if math.isfinite(x) and math.isfinite(y) else None

    @staticmethod
    def _bool(value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"{name} must be a bool")
