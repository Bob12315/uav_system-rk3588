from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from guidance.target_fusion import MultiPhotoFusion, MultiPhotoFusionConfig
from .result import ActionResult
from guidance.target_localization import CameraProjectionConfig, TargetLocalization


class FixedViewLocalizeAction(ActionModule):
    """Stay at current point, collect multiple YOLO frames, and fuse localized objects."""

    def __init__(self) -> None:
        self.reset()

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("detection_source must be scene or perception")

        class_names = data.get("class_names", ["bucket"])
        self.class_names = {str(name) for name in class_names} if class_names is not None else None
        self.min_confidence = float(data.get("min_confidence", 0.35))

        self.settle_updates = int(data.get("settle_updates", 8))
        self.capture_updates = int(data.get("capture_updates", 12))
        self.max_updates = int(data.get("max_updates", 40))
        self.save_result = bool(data.get("save_result", True))

        camera_config = CameraProjectionConfig(
            **self._normalized_camera_params(dict(data.get("camera") or {}))
        )
        fusion_config = MultiPhotoFusionConfig(**dict(data.get("fusion") or {}))

        self.localizer = TargetLocalization(
            camera_config,
            min_confidence=self.min_confidence,
            class_names=self.class_names,
        )
        self.fusion = MultiPhotoFusion(fusion_config, class_names=self.class_names)

        self.update_count = 0
        self.settle_count = 0
        self.capture_count = 0
        self.raw_estimates: list[dict[str, Any]] = []
        self.captures: list[dict[str, Any]] = []
        self.phase = "settle"
        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail(reason="stopped"))

        self.update_count += 1
        data = context or {}

        if self.phase == "settle":
            return self._update_settle()
        if self.phase == "capture":
            return self._update_capture(data)
        if self.phase == "done":
            return ActionResult(
                done=True,
                reason=self._last_reason or "fixed_view_localized",
                detail=self._detail(done=True, fused_objects=self._last_fused, reason=self._last_reason or "fixed_view_localized"),
            )
        return ActionResult(failed=True, reason="invalid_phase", detail=self._detail())

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.detection_source = "scene"
        self.class_names: set[str] | None = {"bucket"}
        self.min_confidence = 0.35
        self.settle_updates = 8
        self.capture_updates = 12
        self.max_updates = 40
        self.save_result = True
        self.localizer = TargetLocalization(CameraProjectionConfig())
        self.fusion = MultiPhotoFusion(MultiPhotoFusionConfig())
        self.update_count = 0
        self.settle_count = 0
        self.capture_count = 0
        self.raw_estimates = []
        self.captures = []
        self.phase = "idle"
        self._last_fused: list[dict[str, Any]] = []
        self._last_reason = ""
        self.started = False
        self.stopped = False

    # ── phase handlers ──────────────────────────────────────────────

    def _update_settle(self) -> ActionResult:
        self.settle_count += 1
        if self.settle_count >= self.settle_updates:
            self.phase = "capture"
            self.capture_count = 0
            return ActionResult(reason="fixed_view_capture", detail=self._detail())
        if self.update_count > self.max_updates:
            return ActionResult(
                failed=True,
                reason="no_target_fused",
                detail=self._detail(reason="fixed_view_localize_timeout_settle"),
            )
        return ActionResult(reason="fixed_view_settle", detail=self._detail())

    def _update_capture(self, context: dict[str, Any]) -> ActionResult:
        detections, image_width, image_height = self._detections(context)
        try:
            drone = self._drone_context(context)
            self._altitude_m(drone)
        except ValueError:
            drone = None

        estimates: list[dict[str, Any]] = []
        if drone is not None and detections:
            try:
                estimates = self.localizer.localize_detections(
                    detections,
                    drone,
                    image_width=image_width,
                    image_height=image_height,
                )
            except Exception:
                estimates = []
            self.raw_estimates.extend(estimates)

        self.capture_count += 1
        self.captures.append({
            "capture_index": len(self.captures),
            "detections_count": len(detections),
            "estimates_count": len(estimates),
            "drone": {
                "local_x": drone.get("local_x") if drone else None,
                "local_y": drone.get("local_y") if drone else None,
                "local_z": drone.get("local_z") if drone else None,
                "yaw": drone.get("yaw") if drone else None,
                "relative_altitude": drone.get("relative_altitude") if drone else None,
            } if drone else {},
        })

        if self.capture_count >= self.capture_updates:
            return self._fuse(reason="fixed_view_localized")

        if self.update_count > self.max_updates:
            if self.raw_estimates:
                return self._fuse(reason="fixed_view_localized_timeout_partial")
            return ActionResult(
                failed=True,
                reason="no_target_fused",
                detail=self._detail(reason="fixed_view_localize_timeout"),
            )

        return ActionResult(reason="fixed_view_capture", detail=self._detail())

    def _fuse(self, *, reason: str) -> ActionResult:
        fused_objects = self.fusion.fuse(self.raw_estimates) if self.fusion else []
        if not fused_objects:
            return ActionResult(
                failed=True,
                reason="no_target_fused",
                detail=self._detail(reason=reason),
            )
        self.phase = "done"
        self._last_fused = fused_objects
        self._last_reason = reason
        return ActionResult(
            done=True,
            reason=reason,
            detail=self._detail(done=True, fused_objects=fused_objects, reason=reason),
        )

    # ── helpers ─────────────────────────────────────────────────────

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
        drone = context.get("drone")
        if isinstance(drone, dict):
            return dict(drone)
        data: dict[str, Any] = {}
        for name in (
            "local_x", "local_y", "local_z", "yaw",
            "relative_altitude", "relative_altitude_m",
            "altitude", "altitude_m",
        ):
            if name in context:
                data[name] = context[name]
        return data

    def _altitude_m(self, drone: dict[str, Any]) -> float:
        self._required_float(drone, "local_x")
        self._required_float(drone, "local_y")
        self._required_float(drone, "yaw")
        for name in ("relative_altitude", "relative_altitude_m", "altitude", "altitude_m"):
            if name in drone:
                altitude_m = self._required_float(drone, name)
                if altitude_m < self.localizer.camera.min_altitude_m:
                    raise ValueError("altitude_m is below min_altitude_m")
                return altitude_m
        if "local_z" in drone:
            local_z = self._required_float(drone, "local_z")
            if local_z < 0.0:
                altitude_m = -local_z
                if altitude_m < self.localizer.camera.min_altitude_m:
                    raise ValueError("altitude_m is below min_altitude_m")
                return altitude_m
        raise ValueError("usable altitude is required")

    def _detail(
        self,
        *,
        done: bool = False,
        fused_objects: list[dict[str, Any]] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "raw_estimates": self.raw_estimates,
            "localized_objects": [],
            "count": len(self.raw_estimates),
            "detection_source": self.detection_source,
            "captures": self.captures,
            "summary": {
                "raw_estimate_count": len(self.raw_estimates),
                "fused_count": len(fused_objects) if fused_objects else 0,
                "capture_updates": self.capture_updates,
                "settle_updates": self.settle_updates,
                "max_updates": self.max_updates,
            },
            "debug": {
                "fusion": self.fusion.last_debug if self.fusion else {},
                "localizer": self.localizer.last_debug if self.localizer else {},
            },
        }
        if done and fused_objects:
            localized_objects: list[dict[str, Any]] = []
            for obj in fused_objects:
                localized_objects.append({
                    "id": obj.get("id"),
                    "target_id": obj.get("id"),
                    "class_name": obj.get("class_name"),
                    "x": obj.get("x"),
                    "y": obj.get("y"),
                    "z": obj.get("z", 0.0),
                    "local_x": obj.get("local_x", obj.get("x")),
                    "local_y": obj.get("local_y", obj.get("y")),
                    "local_z": obj.get("local_z", obj.get("z", 0.0)),
                    "seen_count": obj.get("count"),
                    "count": obj.get("count"),
                    "raw_count": obj.get("raw_count"),
                    "weight": obj.get("weight"),
                    "track_ids": obj.get("track_ids", []),
                })
            detail["localized_objects"] = localized_objects
            detail["count"] = len(localized_objects)
        if reason:
            detail["reason"] = reason
        return detail

    # ── validation helpers ──────────────────────────────────────────

    def _normalized_camera_params(self, camera: dict[str, Any]) -> dict[str, Any]:
        if "horizontal_fov_deg" in camera and "fov_x_deg" not in camera:
            camera["fov_x_deg"] = camera["horizontal_fov_deg"]
        if "vertical_fov_deg" in camera and "fov_y_deg" not in camera:
            camera["fov_y_deg"] = camera["vertical_fov_deg"]
        for name in ("horizontal_fov_deg", "vertical_fov_deg", "model"):
            camera.pop(name, None)
        return camera

    def _required_float(self, data: dict[str, Any], name: str) -> float:
        if name not in data:
            raise ValueError(f"{name} is required")
        try:
            value = float(data[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value
