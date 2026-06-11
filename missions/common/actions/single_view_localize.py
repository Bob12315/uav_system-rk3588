from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult
from .target_localization import CameraProjectionConfig, TargetLocalization


class SingleViewLocalizeAction(ActionModule):
    """Localize current-frame detections without moving or fusing."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("detection_source must be scene or perception")

        class_names = data.get("class_names", ["bucket"])
        self.class_names = {str(name) for name in class_names} if class_names is not None else None
        self.min_confidence = float(data.get("min_confidence", 0.35))
        self.localizer = TargetLocalization(
            self._camera_config(data.get("camera")),
            min_confidence=self.min_confidence,
            class_names=self.class_names,
        )
        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._empty_detail())

        data = context or {}
        detections, image_width, image_height = self._detections(data)
        try:
            drone = self._drone_context(data)
            altitude_m = self._altitude_m(drone)
        except ValueError as exc:
            return ActionResult(
                failed=True,
                reason="missing_drone_context",
                detail={
                    "error": str(exc),
                    "detection_source": self.detection_source,
                    "image_width": image_width,
                    "image_height": image_height,
                    "summary": self._summary([], len(detections), {}, None),
                    "debug": self._debug(len(detections), 0),
                },
            )

        if not detections:
            return ActionResult(
                done=True,
                reason="no_detections",
                detail=self._detail([], 0, image_width, image_height, drone, altitude_m),
            )

        raw_estimates = self.localizer.localize_detections(
            detections,
            drone,
            image_width=image_width,
            image_height=image_height,
        )
        return ActionResult(
            done=True,
            reason="single_view_localized",
            detail=self._detail(raw_estimates, len(detections), image_width, image_height, drone, altitude_m),
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.detection_source = "scene"
        self.class_names: set[str] | None = {"bucket"}
        self.min_confidence = 0.35
        self.localizer = TargetLocalization(
            CameraProjectionConfig(fov_x_deg=70.0, fov_y_deg=43.0),
            min_confidence=self.min_confidence,
            class_names=self.class_names,
        )
        self.started = False
        self.stopped = False

    def _camera_config(self, raw_camera: Any) -> CameraProjectionConfig:
        camera = dict(raw_camera or {})
        if "model" in camera and str(camera["model"]).strip().lower() != "pinhole":
            raise ValueError("camera.model must be pinhole")
        return CameraProjectionConfig(
            fov_x_deg=float(camera.get("horizontal_fov_deg", camera.get("fov_x_deg", 70.0))),
            fov_y_deg=float(camera.get("vertical_fov_deg", camera.get("fov_y_deg", 43.0))),
            image_x_sign=float(camera.get("image_x_sign", 1.0)),
            image_y_sign=float(camera.get("image_y_sign", 1.0)),
            min_altitude_m=float(camera.get("min_altitude_m", 0.1)),
        )

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
            "local_x",
            "local_y",
            "local_z",
            "yaw",
            "relative_altitude",
            "relative_altitude_m",
            "altitude",
            "altitude_m",
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
        raw_estimates: list[dict[str, Any]],
        detections_count: int,
        image_width: int | float | None,
        image_height: int | float | None,
        drone: dict[str, Any],
        altitude_m: float,
    ) -> dict[str, Any]:
        return {
            "raw_estimates": raw_estimates,
            "localized_objects": raw_estimates,
            "count": len(raw_estimates),
            "detection_source": self.detection_source,
            "image_width": image_width,
            "image_height": image_height,
            "drone": {
                "local_x": drone.get("local_x"),
                "local_y": drone.get("local_y"),
                "local_z": drone.get("local_z"),
                "yaw": drone.get("yaw"),
                "altitude_m": altitude_m,
            },
            "summary": self._summary(raw_estimates, detections_count, drone, altitude_m),
            "debug": self._debug(detections_count, len(raw_estimates)),
        }

    def _empty_detail(self) -> dict[str, Any]:
        return {
            "raw_estimates": [],
            "localized_objects": [],
            "count": 0,
            "detection_source": self.detection_source,
            "summary": self._summary([], 0, {}, None),
            "debug": self._debug(0, 0),
        }

    def _summary(
        self,
        raw_estimates: list[dict[str, Any]],
        detections_count: int,
        drone: dict[str, Any],
        altitude_m: float | None,
    ) -> dict[str, Any]:
        drone_x = self._optional_float(drone.get("local_x"))
        drone_y = self._optional_float(drone.get("local_y"))
        drone_z = self._optional_float(drone.get("local_z"))
        yaw_rad = self._optional_float(drone.get("yaw"))
        return {
            "detections_count": detections_count,
            "localized_count": len(raw_estimates),
            "drone_x": drone_x,
            "drone_y": drone_y,
            "drone_z": drone_z,
            "altitude_m": altitude_m,
            "yaw_rad": yaw_rad,
            "yaw_deg": yaw_rad * 180.0 / math.pi if yaw_rad is not None else None,
            "first_target": self._first_target_summary(raw_estimates, drone_x, drone_y),
        }

    def _first_target_summary(
        self,
        raw_estimates: list[dict[str, Any]],
        drone_x: float | None,
        drone_y: float | None,
    ) -> dict[str, Any] | None:
        if not raw_estimates:
            return None
        target = raw_estimates[0]
        local_x = self._optional_float(target.get("local_x", target.get("x")))
        local_y = self._optional_float(target.get("local_y", target.get("y")))
        dx = local_x - drone_x if local_x is not None and drone_x is not None else None
        dy = local_y - drone_y if local_y is not None and drone_y is not None else None
        distance = math.sqrt(dx * dx + dy * dy) if dx is not None and dy is not None else None
        source = target.get("source") if isinstance(target.get("source"), dict) else {}
        projection = target.get("projection") if isinstance(target.get("projection"), dict) else {}
        return {
            "class_name": target.get("class_name"),
            "confidence": target.get("confidence"),
            "track_id": target.get("track_id"),
            "ex": source.get("ex"),
            "ey": source.get("ey"),
            "local_x": local_x,
            "local_y": local_y,
            "dx_from_drone_m": dx,
            "dy_from_drone_m": dy,
            "distance_from_drone_m": distance,
            "body_x_m": self._first_present_float(projection, ("body_x_m", "body_forward_m")),
            "body_y_m": self._first_present_float(projection, ("body_y_m", "body_right_m")),
            "local_dx_m": self._first_present_float(projection, ("local_dx_m", "local_dx")),
            "local_dy_m": self._first_present_float(projection, ("local_dy_m", "local_dy")),
        }

    def _debug(self, detections_count: int, localized_count: int) -> dict[str, Any]:
        return {
            "detections_count": detections_count,
            "localized_count": localized_count,
            "class_names": sorted(self.class_names) if self.class_names is not None else None,
            "min_confidence": self.min_confidence,
        }

    def _first_present_float(self, data: dict[str, Any], names: tuple[str, ...]) -> float | None:
        for name in names:
            if name in data:
                return self._optional_float(data.get(name))
        return None

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(result):
            return None
        return result

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
