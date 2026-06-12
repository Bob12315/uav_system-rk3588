from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .result import ActionResult


DEFAULT_WAYPOINTS = [
    {"x": -2.5, "y": 48.0, "altitude_m": 2.2},
    {"x": 2.5, "y": 48.0, "altitude_m": 2.2},
    {"x": 2.5, "y": 52.0, "altitude_m": 2.2},
    {"x": -2.5, "y": 52.0, "altitude_m": 2.2},
    {"x": 0.0, "y": 50.0, "altitude_m": 2.0},
]
DEFAULT_BUCKET_CLASSES = ["recon_bucket", "white_bucket"]
DEFAULT_SIGN_CLASSES = ["danger_1", "danger_2", "danger_3"]


class ReconScanAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        waypoints = data.get("waypoints", DEFAULT_WAYPOINTS)
        if not isinstance(waypoints, list) or not waypoints:
            raise ValueError("waypoints must be a non-empty list")
        self.waypoints = [self._validated_waypoint(item) for item in waypoints]

        self.yaw_mode = str(data.get("yaw_mode", "arm_heading")).strip().lower()
        if self.yaw_mode not in {"hold", "fixed", "arm_heading"}:
            raise ValueError("yaw_mode must be hold, fixed, or arm_heading")
        self.yaw_rad = None
        if self.yaw_mode == "fixed":
            self.yaw_rad = float(data["yaw_rad"])
        self.frame = int(data.get("frame", 1))
        self.goto_tolerance_xy_m = float(data.get("goto_tolerance_xy_m", 0.3))
        self.goto_tolerance_z_m = float(data.get("goto_tolerance_z_m", 0.3))
        self.goto_min_hold_updates = int(data.get("goto_min_hold_updates", 1))
        self.capture_updates_per_waypoint = int(data.get("capture_updates_per_waypoint", 4))
        self.settle_updates_per_waypoint = int(data.get("settle_updates_per_waypoint", 2))
        self.max_updates_per_waypoint = int(data.get("max_updates_per_waypoint", 150))
        if self.capture_updates_per_waypoint < 1:
            raise ValueError("capture_updates_per_waypoint must be at least 1")
        if self.settle_updates_per_waypoint < 0:
            raise ValueError("settle_updates_per_waypoint must be non-negative")
        if self.max_updates_per_waypoint < self.capture_updates_per_waypoint + self.settle_updates_per_waypoint:
            raise ValueError("max_updates_per_waypoint is too small")

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("detection_source must be scene or perception")
        self.bucket_class_names = {str(name) for name in data.get("bucket_class_names", DEFAULT_BUCKET_CLASSES)}
        self.sign_class_names = {str(name) for name in data.get("sign_class_names", DEFAULT_SIGN_CLASSES)}
        self.min_bucket_confidence = self._confidence(data.get("min_bucket_confidence", 0.25), "min_bucket_confidence")
        self.min_sign_confidence = self._confidence(data.get("min_sign_confidence", 0.35), "min_sign_confidence")
        self.min_report_confidence = self._confidence(data.get("min_report_confidence", 0.65), "min_report_confidence")
        self.associate_max_distance_norm = float(data.get("associate_max_distance_norm", 0.35))
        self.cluster_radius_m = float(data.get("cluster_radius_m", 0.6))
        if self.associate_max_distance_norm <= 0.0:
            raise ValueError("associate_max_distance_norm must be positive")
        if self.cluster_radius_m <= 0.0:
            raise ValueError("cluster_radius_m must be positive")
        self.blank_when_uncertain = self._bool_param(data.get("blank_when_uncertain", True), "blank_when_uncertain")
        self.priority = int(data.get("priority", 5))
        self.camera = dict(data.get("camera") or {})

        self.phase = "goto"
        self.waypoint_index = 0
        self.goto_action = self._new_goto_action()
        self.waypoint_update_count = 0
        self.settle_count = 0
        self.capture_count = 0
        self.captures = []
        self.bucket_observations = []
        self.sign_observations = []
        self.associations = []
        self.recon_report = {"barrels": []}
        self.localization_error_count = 0
        self.skipped_detection_count = 0
        self.started = True
        self.stopped = False
        self.done = False
        self.failed = False
        self.failure_reason = ""
        self.last_result = None
        self.last_detail = self._detail()

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail())
        if self.done or self.failed:
            return self._clone_result(self.last_result)

        self.waypoint_update_count += 1
        if self.waypoint_update_count > self.max_updates_per_waypoint:
            return self._fail("waypoint_timeout")

        data = context or {}
        if self.phase == "goto":
            result = self._update_goto(data)
        elif self.phase == "settle":
            result = self._update_settle()
        elif self.phase == "capture":
            result = self._update_capture(data)
        else:
            result = self._fail("invalid_recon_phase")
        self.last_result = result
        self.last_detail = dict(result.detail)
        return result

    def stop(self) -> None:
        self.stopped = True
        if self.goto_action is not None:
            self.goto_action.stop()

    def reset(self) -> None:
        self.waypoints: list[dict[str, float]] = []
        self.yaw_mode = "arm_heading"
        self.yaw_rad: float | None = None
        self.frame = 1
        self.goto_tolerance_xy_m = 0.3
        self.goto_tolerance_z_m = 0.3
        self.goto_min_hold_updates = 1
        self.capture_updates_per_waypoint = 4
        self.settle_updates_per_waypoint = 2
        self.max_updates_per_waypoint = 150
        self.detection_source = "scene"
        self.bucket_class_names = set(DEFAULT_BUCKET_CLASSES)
        self.sign_class_names = set(DEFAULT_SIGN_CLASSES)
        self.min_bucket_confidence = 0.25
        self.min_sign_confidence = 0.35
        self.min_report_confidence = 0.65
        self.associate_max_distance_norm = 0.35
        self.cluster_radius_m = 0.6
        self.blank_when_uncertain = True
        self.priority = 5
        self.camera: dict[str, Any] = {}
        self.phase = "idle"
        self.waypoint_index = 0
        self.goto_action: GotoWaypointAction | None = None
        self.waypoint_update_count = 0
        self.settle_count = 0
        self.capture_count = 0
        self.captures: list[dict[str, Any]] = []
        self.bucket_observations: list[dict[str, Any]] = []
        self.sign_observations: list[dict[str, Any]] = []
        self.associations: list[dict[str, Any]] = []
        self.recon_report: dict[str, Any] = {"barrels": []}
        self.localization_error_count = 0
        self.skipped_detection_count = 0
        self.started = False
        self.stopped = False
        self.done = False
        self.failed = False
        self.failure_reason = ""
        self.last_result: ActionResult | None = None
        self.last_detail: dict[str, Any] = {}

    def _update_goto(self, context: dict[str, Any]) -> ActionResult:
        if self.goto_action is None:
            return self._fail("goto_failed")
        result = self.goto_action.update(context)
        if result.failed:
            return self._fail("goto_failed", {"goto_reason": result.reason, "goto": result.detail})
        if not result.done:
            return ActionResult(
                actions=result.actions,
                reason="recon_goto",
                detail=self._detail({"goto_reason": result.reason, "goto": result.detail}),
            )
        self.phase = "settle"
        self.settle_count = 0
        if self.settle_updates_per_waypoint == 0:
            self.phase = "capture"
            self.capture_count = 0
            return ActionResult(reason="recon_capture_started", detail=self._detail())
        return ActionResult(reason="recon_settle", detail=self._detail())

    def _update_settle(self) -> ActionResult:
        self.settle_count += 1
        if self.settle_count >= self.settle_updates_per_waypoint:
            self.phase = "capture"
            self.capture_count = 0
        return ActionResult(reason="recon_settle", detail=self._detail())

    def _update_capture(self, context: dict[str, Any]) -> ActionResult:
        detections, image_width, image_height = self._detections(context)
        buckets, signs = self._split_detections(detections, image_width, image_height)
        self._record_capture(buckets, signs, len(detections))
        self.capture_count += 1
        if self.capture_count < self.capture_updates_per_waypoint:
            return ActionResult(reason="recon_capture", detail=self._detail())
        if self.waypoint_index + 1 < len(self.waypoints):
            self.waypoint_index += 1
            self.phase = "goto"
            self.waypoint_update_count = 0
            self.settle_count = 0
            self.capture_count = 0
            self.goto_action = self._new_goto_action()
            return ActionResult(reason="recon_next_waypoint", detail=self._detail())
        return self._finish()

    def _record_capture(self, buckets: list[dict[str, Any]], signs: list[dict[str, Any]], detections_count: int) -> None:
        bucket_ids = []
        for bucket in buckets:
            bucket_id = f"bucket_{len(self.bucket_observations)}"
            observation = dict(bucket)
            observation.update({"bucket_temp_id": bucket_id, "waypoint_index": self.waypoint_index})
            self.bucket_observations.append(observation)
            bucket_ids.append(bucket_id)
        for sign in signs:
            sign_observation = dict(sign)
            sign_observation["waypoint_index"] = self.waypoint_index
            self.sign_observations.append(sign_observation)
            nearest = self._nearest_bucket(sign, buckets, bucket_ids)
            if nearest is not None:
                bucket, bucket_id, distance = nearest
                self.associations.append(
                    {
                        "waypoint_index": self.waypoint_index,
                        "bucket_temp_id": bucket_id,
                        "sign_class": sign["class_name"],
                        "sign_confidence": sign["confidence"],
                        "distance_norm": distance,
                    }
                )
        self.captures.append(
            {
                "waypoint_index": self.waypoint_index,
                "bucket_count": len(buckets),
                "sign_count": len(signs),
                "detections_count": detections_count,
            }
        )

    def _finish(self) -> ActionResult:
        if not self.bucket_observations:
            result = self._fail("no_recon_buckets")
            self.last_result = result
            return result
        barrels = self._build_barrels()
        self.recon_report = {"barrels": barrels}
        self.phase = "done"
        self.done = True
        return ActionResult(done=True, reason="recon_scan_done", detail=self._detail(done=True))

    def _build_barrels(self) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        bucket_to_cluster: dict[str, int] = {}
        for observation in self.bucket_observations:
            cluster_index = self._matching_cluster(observation, clusters)
            if cluster_index is None:
                cluster_index = len(clusters)
                clusters.append({"observations": [], "signs": []})
            clusters[cluster_index]["observations"].append(observation)
            bucket_to_cluster[observation["bucket_temp_id"]] = cluster_index
        for association in self.associations:
            cluster_index = bucket_to_cluster.get(association["bucket_temp_id"])
            if cluster_index is not None:
                clusters[cluster_index]["signs"].append(association)

        barrels = []
        for index, cluster in enumerate(clusters, start=1):
            observations = cluster["observations"]
            signs = cluster["signs"]
            local_points = [
                (item["local_x"], item["local_y"])
                for item in observations
                if item.get("local_x") is not None and item.get("local_y") is not None
            ]
            local_x = sum(item[0] for item in local_points) / len(local_points) if local_points else None
            local_y = sum(item[1] for item in local_points) / len(local_points) if local_points else None
            votes = {name: 0 for name in sorted(self.sign_class_names)}
            confidences = {name: 0.0 for name in sorted(self.sign_class_names)}
            for sign in signs:
                sign_class = sign["sign_class"]
                votes[sign_class] = votes.get(sign_class, 0) + 1
                confidences[sign_class] = max(confidences.get(sign_class, 0.0), float(sign["sign_confidence"]))
            best_class = None
            if signs:
                best_class = max(votes, key=lambda name: (votes.get(name, 0), confidences.get(name, 0.0)))
            best_confidence = confidences.get(best_class, 0.0) if best_class is not None else 0.0
            uncertain = bool(best_class and best_confidence < self.min_report_confidence)
            content = best_class if best_class and (best_confidence >= self.min_report_confidence or not self.blank_when_uncertain) else "blank"
            barrel = {
                "id": f"recon_{index}",
                "local_x": local_x,
                "local_y": local_y,
                "content": content,
                "confidence": best_confidence if content != "blank" else 0.0,
                "votes": votes,
                "observation_count": len(observations),
            }
            if uncertain:
                barrel["uncertain"] = True
            barrels.append(barrel)
        return barrels

    def _matching_cluster(self, observation: dict[str, Any], clusters: list[dict[str, Any]]) -> int | None:
        for index, cluster in enumerate(clusters):
            for item in cluster["observations"]:
                if observation.get("local_x") is not None and item.get("local_x") is not None:
                    distance = math.hypot(observation["local_x"] - item["local_x"], observation["local_y"] - item["local_y"])
                    if distance <= self.cluster_radius_m:
                        return index
                else:
                    distance = math.hypot(observation["ex"] - item["ex"], observation["ey"] - item["ey"])
                    if distance <= self.associate_max_distance_norm:
                        return index
        return None

    def _nearest_bucket(
        self,
        sign: dict[str, Any],
        buckets: list[dict[str, Any]],
        bucket_ids: list[str],
    ) -> tuple[dict[str, Any], str, float] | None:
        best = None
        for bucket, bucket_id in zip(buckets, bucket_ids):
            distance = math.hypot(sign["ex"] - bucket["ex"], sign["ey"] - bucket["ey"])
            if distance <= self.associate_max_distance_norm and (best is None or distance < best[2]):
                best = (bucket, bucket_id, distance)
        return best

    def _split_detections(
        self,
        detections: list[dict[str, Any]],
        image_width: int | float | None,
        image_height: int | float | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        buckets = []
        signs = []
        for detection in detections:
            parsed = self._parsed_detection(detection, image_width, image_height)
            if parsed is None:
                self.skipped_detection_count += 1
                continue
            class_name = parsed["class_name"]
            confidence = parsed["confidence"]
            if class_name in self.bucket_class_names and confidence >= self.min_bucket_confidence:
                buckets.append(parsed)
            elif class_name in self.sign_class_names and confidence >= self.min_sign_confidence:
                signs.append(parsed)
        return buckets, signs

    def _parsed_detection(
        self,
        detection: dict[str, Any],
        image_width: int | float | None,
        image_height: int | float | None,
    ) -> dict[str, Any] | None:
        class_name = str(detection.get("class_name") or detection.get("label") or detection.get("name") or "")
        confidence = self._float(detection.get("confidence", detection.get("conf", 0.0)))
        center = self._center(detection, image_width, image_height)
        if center is None:
            return None
        return {
            "class_name": class_name,
            "confidence": confidence,
            "track_id": detection.get("track_id"),
            "ex": center[0],
            "ey": center[1],
            "local_x": self._optional_float(detection.get("local_x", detection.get("x"))),
            "local_y": self._optional_float(detection.get("local_y", detection.get("y"))),
        }

    def _center(
        self,
        detection: dict[str, Any],
        image_width: int | float | None,
        image_height: int | float | None,
    ) -> tuple[float, float] | None:
        ex = self._optional_float(detection.get("ex"))
        ey = self._optional_float(detection.get("ey"))
        if ex is not None and ey is not None:
            return ex, ey
        cx = self._optional_float(detection.get("cx"))
        cy = self._optional_float(detection.get("cy"))
        bbox = detection.get("bbox")
        if (cx is None or cy is None) and isinstance(bbox, list) and len(bbox) >= 4:
            try:
                cx = (float(bbox[0]) + float(bbox[2])) / 2.0
                cy = (float(bbox[1]) + float(bbox[3])) / 2.0
            except (TypeError, ValueError):
                return None
        width = self._optional_float(image_width)
        height = self._optional_float(image_height)
        if cx is None or cy is None or width is None or height is None or width <= 0.0 or height <= 0.0:
            return None
        return (cx - width / 2.0) / (width / 2.0), (cy - height / 2.0) / (height / 2.0)

    def _detections(self, context: dict[str, Any]) -> tuple[list[dict[str, Any]], Any, Any]:
        if self.detection_source == "scene":
            scene = context.get("scene") if isinstance(context.get("scene"), dict) else {}
            detections = scene.get("detections") if isinstance(scene, dict) else []
            return list(detections) if isinstance(detections, list) else [], scene.get("image_width"), scene.get("image_height")
        perception = context.get("perception")
        if isinstance(perception, dict) and perception.get("target_valid", True):
            return [perception], perception.get("image_width"), perception.get("image_height")
        return [], None, None

    def _new_goto_action(self) -> GotoWaypointAction:
        waypoint = self.waypoints[self.waypoint_index]
        params: dict[str, Any] = {
            "x": waypoint["x"],
            "y": waypoint["y"],
            "altitude_m": waypoint["altitude_m"],
            "yaw_mode": self.yaw_mode,
            "frame": self.frame,
            "tolerance_xy_m": self.goto_tolerance_xy_m,
            "tolerance_z_m": self.goto_tolerance_z_m,
            "min_hold_updates": self.goto_min_hold_updates,
            "priority": self.priority,
            "key": f"recon_waypoint_{self.waypoint_index}",
        }
        if self.yaw_mode == "fixed":
            params["yaw_rad"] = self.yaw_rad
        action = GotoWaypointAction()
        action.start(params)
        return action

    def _validated_waypoint(self, item: Any) -> dict[str, float]:
        if not isinstance(item, dict):
            raise ValueError("waypoint must be a dict")
        waypoint = {"x": float(item["x"]), "y": float(item["y"]), "altitude_m": float(item["altitude_m"])}
        if waypoint["altitude_m"] <= 0.0:
            raise ValueError("waypoint altitude_m must be positive")
        return waypoint

    def _detail(self, extra: dict[str, Any] | None = None, *, done: bool = False) -> dict[str, Any]:
        detail = {
            "phase": self.phase,
            "waypoint_index": self.waypoint_index,
            "waypoint_count": len(self.waypoints),
            "capture_count": self.capture_count,
            "settle_count": self.settle_count,
            "captures": list(self.captures),
            "bucket_observation_count": len(self.bucket_observations),
            "sign_observation_count": len(self.sign_observations),
            "association_count": len(self.associations),
            "skipped_detection_count": self.skipped_detection_count,
            "localization_error_count": self.localization_error_count,
            "blank_when_uncertain": self.blank_when_uncertain,
            "min_report_confidence": self.min_report_confidence,
            "recon_report": dict(self.recon_report),
            "barrel_count": len(self.recon_report.get("barrels", [])),
        }
        if done:
            detail["done"] = True
        if extra:
            detail.update(extra)
        return detail

    def _fail(self, reason: str, extra: dict[str, Any] | None = None) -> ActionResult:
        self.phase = "failed"
        self.failed = True
        self.failure_reason = reason
        return ActionResult(failed=True, reason=reason, detail=self._detail(extra))

    def _clone_result(self, result: ActionResult | None) -> ActionResult:
        if result is None:
            return ActionResult(failed=True, reason="missing_cached_result")
        return ActionResult(
            actions=list(result.actions),
            done=result.done,
            failed=result.failed,
            reason=result.reason,
            detail=dict(result.detail),
        )

    def _confidence(self, value: Any, name: str) -> float:
        result = float(value)
        if result < 0.0 or result > 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
        return result

    def _bool_param(self, value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"{name} must be a bool")

    def _float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _optional_float(self, value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None
