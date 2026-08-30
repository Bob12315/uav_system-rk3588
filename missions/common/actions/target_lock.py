from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult
from guidance.target_localization import CameraProjectionConfig, TargetLocalization


class TargetLockAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.acquire_mode = str(data.get("acquire_mode", "known_target")).strip().lower()
        if self.acquire_mode not in {"known_target", "class_single"}:
            raise ValueError("acquire_mode must be known_target or class_single")
        self.skip_if_invalid_target = bool(data.get("skip_if_invalid_target", False))
        target = data.get("target")
        if self.acquire_mode == "known_target" and self.skip_if_invalid_target:
            # skip on None, non-dict, explicit valid=false, or invalid coords
            if not isinstance(target, dict):
                self._skipped = True
                self.started = True
                self.stopped = False
                return
            if target.get("valid") is False:
                self._skipped = True
                self.started = True
                self.stopped = False
                return
            try:
                self.target_x, self.target_y = self._target_xy(target)
            except ValueError:
                self._skipped = True
                self.started = True
                self.stopped = False
                return
        elif self.acquire_mode == "known_target":
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
        self.require_unique_track = bool(data.get("require_unique_track", True))
        self.max_target_age_s = self._positive(
            data.get("max_target_age_s", 0.5), "max_target_age_s"
        )
        if self.acquire_mode == "class_single":
            if self.detection_source != "scene":
                raise ValueError("class_single requires detection_source=scene")
            if not self.class_names:
                raise ValueError("class_single requires class_names")
            if not self.require_unique_track:
                raise ValueError("class_single requires require_unique_track=true")
            self.localizer = None
        else:
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
        self.lock_requested_track_id = None
        self.failure_reason = ""
        self.yaw_defaulted = False
        self.last_detail = {}

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")
        if getattr(self, "_skipped", False):
            return ActionResult(done=True, reason="skipped_missing_target",
                                detail={"status": "skipped_missing_target"})
        if self.done:
            return ActionResult(
                done=True,
                reason="target_locked",
                output=self._locked_output(),
                detail=self._detail(),
            )
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
        if self.acquire_mode == "class_single":
            return self._update_class_single(data)

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
            effects=ActionResult.typed([action]),
            done=True,
            reason="target_locked",
            output=self._locked_output(),
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
        self.skip_if_invalid_target = False
        self._skipped = False
        self.acquire_mode = "known_target"
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
        self.require_unique_track = True
        self.max_target_age_s = 0.5
        self.localizer: TargetLocalization | None = None
        self.started = False
        self.stopped = False
        self.done = False
        self.failed = False
        self.update_count = 0
        self.locked_track_id: int | None = None
        self.lock_requested_track_id: int | None = None
        self.failure_reason = ""
        self.yaw_defaulted = False
        self.last_detail: dict[str, Any] = {}

    def _update_class_single(self, data: dict[str, Any]) -> ActionResult:
        """Acquire one live class match, then wait for the lock acknowledgement.

        There is intentionally no metric target in this mode.  It is for the
        final home-marker correction after FIELD/GLOBAL navigation reaches
        home, never for converting FIELD coordinates into LOCAL_NED.
        """
        source_error = self._class_single_source_error(data)
        if source_error is not None:
            return ActionResult(
                reason=source_error,
                detail=self._detail(localization_error=source_error),
            )

        if self.lock_requested_track_id is None:
            detections, _width, _height = self._detections(data)
            candidates, rejected = self._class_single_candidates(detections)
            detail = self._detail(
                detections_count=len(detections),
                candidate_count=len(candidates),
                candidate_track_ids=[candidate["track_id"] for candidate in candidates],
                rejected_candidates=rejected,
            )
            if not candidates:
                return ActionResult(reason="target_not_found", detail=detail)
            if len(candidates) != 1:
                return ActionResult(reason="target_acquisition_ambiguous", detail=detail)

            candidate = candidates[0]
            track_id = int(candidate["track_id"])
            self.locked_track_id = track_id
            self.lock_requested_track_id = track_id
            action = {
                "action_type": "yolo_lock_target",
                "params": {"track_id": track_id},
                "key": self.key,
                "once": self.lock_once,
                "priority": self.priority,
            }
            return ActionResult(
                effects=ActionResult.typed([action]),
                reason="target_lock_requested",
                detail=self._detail(
                    detections_count=len(detections),
                    candidate_count=1,
                    candidate_track_ids=[track_id],
                    selected_candidate=candidate,
                ),
            )

        lock_error = self._class_single_lock_error(data)
        if lock_error is not None:
            return ActionResult(
                reason="target_lock_waiting",
                detail=self._detail(lock_error=lock_error),
            )

        self.done = True
        return ActionResult(
            done=True,
            reason="target_locked",
            output=self._locked_output(),
            detail=self._detail(),
        )

    def _class_single_source_error(self, data: dict[str, Any]) -> str | None:
        status = data.get("perception_status")
        if isinstance(status, dict):
            if bool(status.get("stale", False)):
                return "perception_stale"
            age_s = self._optional_finite(status.get("age_sec"))
            if age_s is not None and age_s > self.max_target_age_s:
                return "perception_stale"
        scene = data.get("scene")
        if not isinstance(scene, dict) or scene.get("valid") is not True:
            return "scene_invalid"
        return None

    def _class_single_candidates(
        self,
        detections: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        candidates_by_track: dict[int, dict[str, Any]] = {}
        rejected: list[dict[str, Any]] = []
        for detection in detections:
            class_name = str(detection.get("class_name", ""))
            if class_name not in (self.class_names or set()):
                continue
            track_id = self._optional_int(detection.get("track_id"))
            confidence = self._optional_finite(detection.get("confidence"))
            ex = self._optional_finite(detection.get("ex"))
            ey = self._optional_finite(detection.get("ey"))
            if track_id is None:
                rejected.append({"reason": "track_id_missing", "class_name": class_name})
                continue
            if confidence is None or confidence < self.min_confidence:
                rejected.append({"reason": "confidence_below_min", "track_id": track_id})
                continue
            if ex is None or ey is None:
                rejected.append({"reason": "image_error_unavailable", "track_id": track_id})
                continue
            candidates_by_track[track_id] = {
                "track_id": track_id,
                "class_name": class_name,
                "confidence": confidence,
                "ex": ex,
                "ey": ey,
            }
        return list(candidates_by_track.values()), rejected

    def _class_single_lock_error(self, data: dict[str, Any]) -> str | None:
        perception = data.get("perception")
        if not isinstance(perception, dict):
            return "perception_unavailable"
        if not bool(perception.get("target_valid", False)):
            return "target_not_valid"
        if str(perception.get("tracking_state", "")).lower() != "locked":
            return "target_not_locked"
        if self._optional_int(perception.get("track_id")) != self.lock_requested_track_id:
            return "target_track_id_mismatch"
        if str(perception.get("class_name", "")) not in (self.class_names or set()):
            return "target_class_mismatch"
        confidence = self._optional_finite(perception.get("confidence"))
        if confidence is None or confidence < self.min_confidence:
            return "target_confidence_below_min"
        if (
            self._optional_finite(perception.get("ex")) is None
            or self._optional_finite(perception.get("ey")) is None
        ):
            return "target_error_unavailable"
        return None

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

    def _locked_output(self) -> dict[str, int]:
        return {} if self.locked_track_id is None else {"locked_track_id": self.locked_track_id}

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
        candidate_count: int | None = None,
        candidate_track_ids: list[int] | None = None,
        rejected_candidates: list[dict[str, Any]] | None = None,
        selected_candidate: dict[str, Any] | None = None,
        lock_error: str | None = None,
    ) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "acquire_mode": self.acquire_mode,
            "update_count": self.update_count,
            "detections_count": detections_count,
            "estimates_count": estimates_count,
            "best_distance_m": best_distance_m,
            "locked_track_id": self.locked_track_id,
        }
        if self.acquire_mode == "known_target":
            detail["target"] = {"x": self.target_x, "y": self.target_y}
        if best_estimate is not None:
            detail["best_estimate"] = self._json_safe_dict(best_estimate)
        if localization_error is not None:
            detail["localization_error"] = localization_error
        if candidate_count is not None:
            detail["candidate_count"] = candidate_count
        if candidate_track_ids is not None:
            detail["candidate_track_ids"] = candidate_track_ids
        if rejected_candidates:
            detail["rejected_candidates"] = [
                self._json_safe_dict(candidate) for candidate in rejected_candidates
            ]
        if selected_candidate is not None:
            detail["selected_candidate"] = self._json_safe_dict(selected_candidate)
        if lock_error is not None:
            detail["lock_error"] = lock_error
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

    def _positive(self, value: Any, name: str) -> float:
        result = self._float_value(value, name)
        if result <= 0.0:
            raise ValueError(f"{name} must be positive")
        return result

    def _optional_finite(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _optional_int(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            return None
        try:
            if float(value) != float(candidate):
                return None
        except (TypeError, ValueError):
            return None
        return candidate

    def _has_float(self, data: dict[str, Any], name: str) -> bool:
        if name not in data:
            return False
        try:
            self._float_value(data[name], name)
        except ValueError:
            return False
        return True
