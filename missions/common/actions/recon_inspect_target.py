from __future__ import annotations

import math
from typing import Any

from .align_descend import AlignDescendAction
from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .result import ActionResult
from .target_lock import TargetLockAction


BUCKET_CLASSES = ["bucket_1", "bucket_2", "bucket_3", "bucket", "recon_bucket", "white_bucket"]
SIGN_CLASSES = [
    "danger_1", "danger_2", "danger_3", "baozha", "shenghua", "yiran",
    "fangshe", "buran", "fushi", "youdu", "yushi", "ziran", "ciji",
]


class ReconInspectTargetAction(ActionModule):
    """Inspect one selected recon target; per-target failures are normal results."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        targets = data.get("targets", [])
        self.targets = targets if isinstance(targets, list) else []
        self.target_index = int(data.get("target_index", 0))
        self.inspect_altitude_m = float(data.get("inspect_altitude_m", 3.0))
        self.align_finish_altitude_m = float(data.get("align_finish_altitude_m", 1.5))
        self.waypoint_mode = str(data.get("waypoint_mode", "absolute"))
        self.yaw_mode = str(data.get("yaw_mode", "field_heading"))
        self.goto_tolerance_xy_m = float(data.get("goto_tolerance_xy_m", 0.35))
        self.goto_tolerance_z_m = float(data.get("goto_tolerance_z_m", 0.35))
        self.goto_min_hold_updates = int(data.get("goto_min_hold_updates", 1))
        self.target_lock_params = self._target_lock_defaults() | dict(data.get("target_lock") or {})
        self.align_params = self._merge_align_params(dict(data.get("align_descend") or {}))
        self.observe_params = self._observe_defaults() | dict(data.get("observe") or {})
        self.continue_on_lock_failed = self._bool(data.get("continue_on_lock_failed", False), "continue_on_lock_failed")
        self.continue_on_align_failed = self._bool(data.get("continue_on_align_failed", False), "continue_on_align_failed")
        self.priority = int(data.get("priority", 5))
        expected_dt = float(self.observe_params["expected_dt_s"])
        observe_time = float(self.observe_params["observe_time_s"])
        if expected_dt <= 0.0 or observe_time <= 0.0:
            raise ValueError("observe timing must be positive")
        self.observe_updates = max(1, int(round(observe_time / expected_dt)))
        self.sign_class_names = {str(item) for item in self.observe_params["sign_class_names"]}
        self.min_sign_confidence = float(self.observe_params["min_sign_confidence"])
        self.detection_source = str(self.observe_params["detection_source"])
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("observe.detection_source must be scene or perception")
        self.started, self.stopped = True, False
        self.state, self.child, self.last_result = "init", None, None
        self.target = self._target()
        self.report = self._report_base(self.target or {})
        self.observe_count = 0
        self.best_sign = None

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self.report)
        if self.last_result is not None:
            return self.last_result
        data = context or {}
        if self.state == "init":
            if self.target is None or self._xy(self.target) is None:
                return self._finish("skipped_missing_target", "skipped_missing_target")
            self._start_goto()

        if self.state in {"goto_target", "target_lock", "align_descend"}:
            assert self.child is not None
            result = self.child.update(data)
            if result.failed:
                return self._child_failed(result)
            if result.done:
                self._record_child_done(result)
                if self.state == "align_descend":
                    self.state, self.child = "observe", None
                    return self._observe(data)  # first observe frame actively clears descent
                self._advance_child()
                return ActionResult(reason=self.state, detail=self._detail())
            return ActionResult(actions=list(result.actions), reason=result.reason, detail=self._detail(result.detail))
        if self.state == "observe":
            return self._observe(data)
        return self.last_result or ActionResult(done=True, reason=self.state, detail=self._detail())

    def stop(self) -> None:
        self.stopped = True
        if self.child is not None:
            self.child.stop()

    def reset(self) -> None:
        self.targets: list[Any] = []
        self.target_index = 0
        self.target: dict[str, Any] | None = None
        self.inspect_altitude_m = 3.0
        self.align_finish_altitude_m = 1.5
        self.waypoint_mode, self.yaw_mode = "absolute", "field_heading"
        self.goto_tolerance_xy_m = self.goto_tolerance_z_m = 0.35
        self.goto_min_hold_updates = 1
        self.target_lock_params: dict[str, Any] = {}
        self.align_params: dict[str, Any] = {}
        self.observe_params: dict[str, Any] = {}
        self.continue_on_lock_failed = self.continue_on_align_failed = False
        self.priority = 5
        self.observe_updates, self.observe_count = 20, 0
        self.sign_class_names: set[str] = set()
        self.min_sign_confidence, self.detection_source = 0.35, "scene"
        self.started = self.stopped = False
        self.state = "init"
        self.child: ActionModule | None = None
        self.best_sign: dict[str, Any] | None = None
        self.report: dict[str, Any] = {}
        self.last_result: ActionResult | None = None

    def _start_goto(self) -> None:
        assert self.target is not None
        x, y = self._xy(self.target) or (0.0, 0.0)
        child = GotoWaypointAction()
        child.start({"x": x, "y": y, "altitude_m": self.inspect_altitude_m,
                     "waypoint_mode": self.waypoint_mode, "yaw_mode": self.yaw_mode,
                     "tolerance_xy_m": self.goto_tolerance_xy_m, "tolerance_z_m": self.goto_tolerance_z_m,
                     "min_hold_updates": self.goto_min_hold_updates, "priority": self.priority,
                     "key": f"recon_inspect_goto_{self.target_index}"})
        self.child, self.state = child, "goto_target"

    def _advance_child(self) -> None:
        assert self.target is not None
        if self.state == "goto_target":
            params = dict(self.target_lock_params)
            params.update({"target": self.target, "priority": self.priority,
                           "key": f"recon_inspect_lock_{self.target_index}"})
            child: ActionModule = TargetLockAction()
            child.start(params)
            self.child, self.state = child, "target_lock"
        elif self.state == "target_lock":
            child = AlignDescendAction()
            child.start(self.align_params)
            self.child, self.state = child, "align_descend"

    def _child_failed(self, result: ActionResult) -> ActionResult:
        if self.state == "goto_target":
            self.report["goto_reason"] = result.reason
            return self._finish("goto_failed", "goto_failed")
        if self.state == "target_lock":
            self.report["lock_reason"] = result.reason
            if self.continue_on_lock_failed:
                self._advance_child()
                return ActionResult(reason=self.state, detail=self._detail(result.detail))
            return self._finish("lock_failed", "lock_failed")
        self.report["align_reason"] = result.reason
        self.report["height_m"] = result.detail.get("height_m")
        if self.continue_on_align_failed:
            self.state, self.child = "observe", None
            return self._observe({})
        return self._finish("align_failed", "align_failed")

    def _record_child_done(self, result: ActionResult) -> None:
        key = {"goto_target": "goto_reason", "target_lock": "lock_reason", "align_descend": "align_reason"}[self.state]
        self.report[key] = result.reason
        if self.state == "align_descend":
            self.report["height_m"] = result.detail.get("height_m")

    def _observe(self, context: dict[str, Any]) -> ActionResult:
        self._capture(context)
        self.observe_count += 1
        zero = self._zero_velocity_action()
        if self.observe_count < self.observe_updates:
            return ActionResult(actions=[zero], reason="observe", detail=self._detail())
        if self.best_sign is None:
            self.report.update({"sign_class": "", "confidence": 0.0, "observe_reason": "observe_done"})
            return self._finish("no_sign", "observe_done", actions=[zero])
        sign = self.best_sign
        bbox = sign.get("bbox")
        if bbox is None and all(k in sign for k in ("x1", "y1", "x2", "y2")):
            bbox = [sign["x1"], sign["y1"], sign["x2"], sign["y2"]]
        self.report.update({"sign_class": sign["class_name"], "confidence": sign["confidence"],
                            "bbox": bbox, "track_id": sign.get("track_id"), "observe_reason": "observe_done"})
        return self._finish("detected", "observe_done", actions=[zero])

    def _capture(self, context: dict[str, Any]) -> None:
        source = context.get("scene") if self.detection_source == "scene" else context.get("perception")
        detections = source.get("detections", []) if isinstance(source, dict) and self.detection_source == "scene" else [source]
        for item in detections if isinstance(detections, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("class_name") or item.get("label") or "")
            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            if name in self.sign_class_names and confidence >= self.min_sign_confidence and (
                self.best_sign is None or confidence > float(self.best_sign["confidence"])
            ):
                self.best_sign = dict(item) | {"class_name": name, "confidence": confidence}

    def _finish(self, status: str, reason: str, actions: list[Any] | None = None) -> ActionResult:
        self.state = "done"
        self.report["status"] = status
        self.last_result = ActionResult(actions=actions or [], done=True, reason=reason, detail=self._detail())
        return self.last_result

    def _detail(self, child_detail: dict[str, Any] | None = None) -> dict[str, Any]:
        detail = dict(self.report)
        detail.update({"target_index": self.target_index, "state": self.state, "done": self.state == "done"})
        if child_detail is not None:
            detail["child_detail"] = child_detail
        return detail

    def _target(self) -> dict[str, Any] | None:
        if self.target_index < 0 or self.target_index >= len(self.targets):
            return None
        target = self.targets[self.target_index]
        return target if isinstance(target, dict) else None

    def _report_base(self, target: dict[str, Any]) -> dict[str, Any]:
        xy = self._xy(target)
        x, y = xy if xy is not None else (None, None)
        return {"target_index": self.target_index,
                "target_id": str(target.get("id") or target.get("target_id") or f"target_{self.target_index}"),
                "rank": target.get("rank", self.target_index + 1), "class_name": str(target.get("class_name") or "bucket"),
                "local_x": x, "local_y": y, "field_x": x, "field_y": y, "status": "",
                "sign_class": "", "confidence": 0.0, "bbox": None, "track_id": None,
                "goto_reason": "", "lock_reason": "", "align_reason": "", "observe_reason": "",
                "observe_time_s": float(self.observe_params.get("observe_time_s", 2.0)), "height_m": None}

    @staticmethod
    def _xy(target: dict[str, Any]) -> tuple[float, float] | None:
        try:
            x = float(target["local_x"] if "local_x" in target else target["x"])
            y = float(target["local_y"] if "local_y" in target else target["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return (x, y) if math.isfinite(x) and math.isfinite(y) else None

    def _zero_velocity_action(self) -> dict[str, Any]:
        return {
            "action_type": "flight_command",
            "params": {
                "type": "flight_command",
                "frame": "BODY_NED",
                "vx_mps": 0.0,
                "vy_mps": 0.0,
                "vz_mps": 0.0,
                "vx_cmd": 0.0,
                "vy_cmd": 0.0,
                "vz_cmd": 0.0,
                "yaw_rate_cmd": 0.0,
                "gimbal_yaw_rate_cmd": 0.0,
                "gimbal_pitch_rate_cmd": 0.0,
                "gimbal_yaw_angle_cmd": None,
                "gimbal_pitch_angle_cmd": None,
                "enable_body": True,
                "enable_gimbal": False,
                "enable_gimbal_angle": False,
                "enable_approach": False,
                "active": True,
                "valid": True,
                "priority": self.priority,
            },
            "key": f"recon_inspect_observe_zero_{self.target_index}",
            "once": False,
            "priority": self.priority,
        }

    @staticmethod
    def _target_lock_defaults() -> dict[str, Any]:
        return {"max_match_distance_m": 1.2, "detection_source": "scene", "class_names": BUCKET_CLASSES,
                "min_confidence": 0.25, "max_updates": 25}

    def _merge_align_params(self, override: dict[str, Any]) -> dict[str, Any]:
        defaults = {"expected_dt_s": 0.1, "lost_timeout_updates": 8, "hold_updates_required": 1,
                    "max_retries": 1, "max_updates": 160, "finish_altitude_m": self.align_finish_altitude_m,
                    "config": {"kp_vx": 0.45, "kp_vy": 0.45, "max_vx_mps": 0.16, "max_vy_mps": 0.16,
                    "height_gain_enabled": True, "height_gain_mode": "points",
                    "height_scale_points": [{"altitude_m": 1.2, "scale": 0.20}, {"altitude_m": 1.3, "scale": 0.25},
                    {"altitude_m": 2.4, "scale": 0.55}, {"altitude_m": 3.5, "scale": 0.55}, {"altitude_m": 4.5, "scale": 0.55}],
                    "scale_max_velocity_with_height": True, "descend_speed_mps": 0.18, "slow_descend_speed_mps": 0.10,
                    "max_ex_cam": 0.16, "max_ey_cam": 0.16, "slow_descend_max_ex_cam": 0.24,
                    "slow_descend_max_ey_cam": 0.24, "deadband_ex_cam": 0.04, "deadband_ey_cam": 0.04,
                    "min_altitude_m": 1.3, "require_target_locked": False, "payload_offset_enabled": False,
                    "fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0}}
        config = dict(defaults["config"]) | dict(override.get("config") or {})
        config["payload_offset_enabled"] = False
        merged = defaults | override
        merged["config"] = config
        merged["finish_altitude_m"] = self.align_finish_altitude_m
        return merged

    @staticmethod
    def _observe_defaults() -> dict[str, Any]:
        return {"observe_time_s": 2.0, "expected_dt_s": 0.1, "min_sign_confidence": 0.35,
                "detection_source": "scene", "sign_class_names": SIGN_CLASSES}

    @staticmethod
    def _bool(value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"{name} must be a bool")
