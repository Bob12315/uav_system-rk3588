from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult
from .target_localization import CameraProjectionConfig, TargetLocalization


class TargetLockAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        target = data.get("target")
        if not isinstance(target, dict):
            raise ValueError("target must be a dict")
        self.target_x, self.target_y = self._target_xy(target)

        self.max_match_distance_m = float(data.get("max_match_distance_m", 1.0))
        if self.max_match_distance_m <= 0.0:
            raise ValueError("max_match_distance_m must be positive")
        self.min_confidence = float(data.get("min_confidence", 0.0))
        if self.min_confidence < 0.0:
            raise ValueError("min_confidence must be non-negative")

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("detection_source must be scene or perception")
        self.max_updates = int(data.get("max_updates", 30))
        if self.max_updates < 1:
            raise ValueError("max_updates must be at least 1")

        class_names = data.get("class_names")
        self.class_names = {str(name) for name in class_names} if class_names is not None else None
        camera_config = CameraProjectionConfig(**dict(data.get("camera") or {}))
        self.localizer = TargetLocalization(
            camera_config,
            min_confidence=self.min_confidence,
            class_names=self.class_names,
        )
        self.priority = int(data.get("priority", 5))
        self.key = str(data.get("key", "target_lock"))
        self.lock_once = bool(data.get("lock_once", True))

        self.started = True
        self.stopped = False
        self.done = False
        self.failed = False
        self.update_count = 0
        self.locked_track_id = None
        self.failure_reason = ""
        self.yaw_defaulted = False
        self.last_detail = {}

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")
        if self.done:
            return ActionResult(done=True, reason="target_locked", detail=self._detail())
        if self.failed:
            return ActionResult(
                failed=True,
                reason=self.failure_reason or "target_lock_failed",
                detail=self._detail(),
            )

        self.update_count += 1
        if self.update_count > self.max_updates:
            self.failed = True
            self.failure_reason = "target_lock_timeout"
            return ActionResult(
                failed=True,
                reason="target_lock_timeout",
                detail=self._detail(),
            )

        data = context or {}
        detections, image_width, image_height = self._detections(data)
        drone = self._drone_context(data)
        estimates: list[dict[str, Any]] = []
        localization_error = None
        if detections:
            localization_error = self._validate_localization_context(drone)
            if localization_error is None:
                try:
                    estimates = self.localizer.localize_detections(
                        detections,
                        drone,
                        image_width=image_width,
                        image_height=image_height,
                    )
                except Exception as exc:
                    localization_error = str(exc)

        best_estimate, best_distance_m = self._best_estimate(estimates)
        detail = self._detail(
            detections_count=len(detections),
            estimates_count=len(estimates),
            best_distance_m=best_distance_m,
            best_estimate=best_estimate,
            localization_error=localization_error,
        )
        if best_estimate is None:
            return ActionResult(reason="target_not_found", detail=detail)

        track_id = best_estimate.get("track_id")
        if track_id is None:
            return ActionResult(reason="target_without_track_id", detail=detail)
        try:
            lock_track_id = int(track_id)
        except (TypeError, ValueError):
            return ActionResult(reason="invalid_track_id", detail=detail)

        self.locked_track_id = lock_track_id
        self.done = True
        action = {
            "action_type": "yolo_lock_target",
            "params": {"track_id": lock_track_id},
            "key": self.key,
            "once": self.lock_once,
            "priority": self.priority,
        }
        return ActionResult(
            actions=[action],
            done=True,
            reason="target_locked",
            detail=self._detail(
                detections_count=len(detections),
                estimates_count=len(estimates),
                best_distance_m=best_distance_m,
                best_estimate=best_estimate,
            ),
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.target_x = 0.0
        self.target_y = 0.0
        self.max_match_distance_m = 1.0
        self.min_confidence = 0.0
        self.class_names: set[str] | None = None
        self.detection_source = "scene"
        self.priority = 5
        self.key = "target_lock"
        self.lock_once = True
        self.max_updates = 30
        self.localizer: TargetLocalization | None = None
        self.started = False
        self.stopped = False
        self.done = False
        self.failed = False
        self.update_count = 0
        self.locked_track_id: int | None = None
        self.failure_reason = ""
        self.yaw_defaulted = False
        self.last_detail: dict[str, Any] = {}

    def _target_xy(self, target: dict[str, Any]) -> tuple[float, float]:
        if "x" in target and "y" in target:
            return self._float_value(target["x"], "target.x"), self._float_value(
                target["y"], "target.y"
            )
        if "local_x" in target and "local_y" in target:
            return self._float_value(target["local_x"], "target.local_x"), self._float_value(
                target["local_y"], "target.local_y"
            )
        raise ValueError("target must include x/y or local_x/local_y")

    def _detections(
        self,
        context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int | float | None, int | float | None]:
        if self.detection_source == "scene":
            scene = context.get("scene")
            if not isinstance(scene, dict):
                return [], None, None
            detections = scene.get("detections")
            if not isinstance(detections, list):
                detections = []
            return (
                [item for item in detections if isinstance(item, dict)],
                scene.get("image_width"),
                scene.get("image_height"),
            )

        perception = context.get("perception")
        if not isinstance(perception, dict):
            return [], None, None
        has_error = ("ex" in perception and "ey" in perception) or (
            "cx" in perception and "cy" in perception
        )
        if not has_error:
            return [], None, None
        return [perception], perception.get("image_width"), perception.get("image_height")

    def _drone_context(self, context: dict[str, Any]) -> dict[str, Any]:
        self.yaw_defaulted = False
        drone = context.get("drone")
        if isinstance(drone, dict):
            if "local_x" in drone and "local_y" in drone and "local_z" in drone:
                data = dict(drone)
                if "yaw" not in data:
                    data["yaw"] = 0.0
                    self.yaw_defaulted = True
                return data

            local_position = drone.get("local_position")
            if isinstance(local_position, dict):
                return self._drone_from_local_position(local_position, drone.get("yaw"))

        local_position = context.get("local_position")
        if isinstance(local_position, dict):
            return self._drone_from_local_position(local_position, None)

        self.yaw_defaulted = True
        return {"yaw": 0.0}

    def _drone_from_local_position(
        self,
        local_position: dict[str, Any],
        yaw: Any,
    ) -> dict[str, Any]:
        data = {
            "local_x": local_position.get("x"),
            "local_y": local_position.get("y"),
            "local_z": local_position.get("z"),
        }
        try:
            z = float(local_position["z"])
        except (KeyError, TypeError, ValueError):
            z = None
        if z is not None and z < 0.0:
            data["relative_altitude"] = -z
        if yaw is None:
            data["yaw"] = 0.0
            self.yaw_defaulted = True
        else:
            data["yaw"] = yaw
        return data

    def _best_estimate(
        self,
        estimates: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, float | None]:
        best_estimate = None
        best_distance_m = None
        for estimate in estimates:
            try:
                x = self._float_value(estimate["x"], "estimate.x")
                y = self._float_value(estimate["y"], "estimate.y")
            except (KeyError, ValueError):
                continue
            distance_m = math.sqrt((x - self.target_x) ** 2 + (y - self.target_y) ** 2)
            if best_distance_m is None or distance_m < best_distance_m:
                best_estimate = estimate
                best_distance_m = distance_m
        if best_distance_m is None or best_distance_m > self.max_match_distance_m:
            return None, best_distance_m
        return best_estimate, best_distance_m

    def _validate_localization_context(self, drone: dict[str, Any]) -> str | None:
        if not self._has_float(drone, "local_x"):
            return "missing local_x"
        if not self._has_float(drone, "local_y"):
            return "missing local_y"
        if not self._has_float(drone, "yaw"):
            return "missing yaw"
        if self._has_float(drone, "relative_altitude"):
            return None
        if self._has_float(drone, "relative_altitude_m"):
            return None
        if self._has_float(drone, "local_z"):
            try:
                if float(drone["local_z"]) < 0.0:
                    return None
            except (TypeError, ValueError):
                pass
        if self._has_float(drone, "altitude"):
            return None
        if self._has_float(drone, "altitude_m"):
            return None
        return "missing usable altitude"

    def _detail(
        self,
        *,
        detections_count: int = 0,
        estimates_count: int = 0,
        best_distance_m: float | None = None,
        best_estimate: dict[str, Any] | None = None,
        localization_error: str | None = None,
    ) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "target": {"x": self.target_x, "y": self.target_y},
            "update_count": self.update_count,
            "detections_count": detections_count,
            "estimates_count": estimates_count,
            "best_distance_m": best_distance_m,
            "locked_track_id": self.locked_track_id,
        }
        if best_estimate is not None:
            detail["best_estimate"] = self._json_safe_dict(best_estimate)
        if localization_error is not None:
            detail["localization_error"] = localization_error
        if self.yaw_defaulted:
            detail["yaw_defaulted"] = True
        self.last_detail = detail
        return detail

    def _json_safe_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                safe[str(key)] = self._json_safe_dict(value)
            elif isinstance(value, list):
                safe[str(key)] = [self._json_safe_value(item) for item in value]
            else:
                safe[str(key)] = self._json_safe_value(value)
        return safe

    def _json_safe_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            return str(value)
        return str(value)

    def _float_value(self, value: Any, name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
        if not math.isfinite(result):
            raise ValueError(f"{name} must be finite")
        return result

    def _has_float(self, data: dict[str, Any], name: str) -> bool:
        if name not in data:
            return False
        try:
            self._float_value(data[name], name)
        except ValueError:
            return False
        return True
