from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CameraProjectionConfig:
    fov_x_deg: float = 113.0
    fov_y_deg: float = 93.0
    image_x_sign: float = 1.0
    image_y_sign: float = -1.0
    min_altitude_m: float = 0.1

    def __post_init__(self) -> None:
        if not 0.0 < self.fov_x_deg < 180.0:
            raise ValueError("fov_x_deg must be greater than 0 and less than 180")
        if not 0.0 < self.fov_y_deg < 180.0:
            raise ValueError("fov_y_deg must be greater than 0 and less than 180")
        if self.image_x_sign not in {1.0, -1.0}:
            raise ValueError("image_x_sign must be 1.0 or -1.0")
        if self.image_y_sign not in {1.0, -1.0}:
            raise ValueError("image_y_sign must be 1.0 or -1.0")
        if self.min_altitude_m <= 0.0:
            raise ValueError("min_altitude_m must be positive")


class TargetLocalization:
    def __init__(
        self,
        camera: CameraProjectionConfig | None = None,
        *,
        min_confidence: float = 0.0,
        class_names: set[str] | None = None,
    ) -> None:
        self.camera = camera or CameraProjectionConfig()
        self.min_confidence = float(min_confidence)
        self.class_names = set(class_names) if class_names is not None else None

    def localize_detection(
        self,
        detection: dict[str, Any],
        drone: dict[str, Any],
        *,
        image_width: int | float | None = None,
        image_height: int | float | None = None,
    ) -> dict[str, Any]:
        ex, ey = self._detection_error(
            detection,
            image_width=image_width,
            image_height=image_height,
        )
        altitude_m = self._altitude_m(drone)
        local_x = self._required_float(drone, "local_x")
        local_y = self._required_float(drone, "local_y")
        yaw = self._required_float(drone, "yaw")

        half_fov_x = math.radians(self.camera.fov_x_deg) / 2.0
        half_fov_y = math.radians(self.camera.fov_y_deg) / 2.0
        angle_x = ex * half_fov_x
        angle_y = ey * half_fov_y

        body_right_m = self.camera.image_x_sign * altitude_m * math.tan(angle_x)
        body_forward_m = self.camera.image_y_sign * altitude_m * math.tan(angle_y)

        local_dx = body_forward_m * math.cos(yaw) - body_right_m * math.sin(yaw)
        local_dy = body_forward_m * math.sin(yaw) + body_right_m * math.cos(yaw)
        target_local_x = local_x + local_dx
        target_local_y = local_y + local_dy

        confidence = self._optional_float(detection.get("confidence"), "confidence")
        return {
            "track_id": detection.get("track_id"),
            "class_id": detection.get("class_id"),
            "class_name": detection.get("class_name"),
            "confidence": confidence,
            "x": target_local_x,
            "y": target_local_y,
            "z": 0.0,
            "local_x": target_local_x,
            "local_y": target_local_y,
            "local_z": 0.0,
            "source": {
                "ex": ex,
                "ey": ey,
                "cx": detection.get("cx"),
                "cy": detection.get("cy"),
                "image_width": image_width,
                "image_height": image_height,
            },
            "projection": {
                "model": "flat_ground_fov_downward_camera",
                "altitude_m": altitude_m,
                "yaw_rad": yaw,
                "body_forward_m": body_forward_m,
                "body_right_m": body_right_m,
                "local_dx": local_dx,
                "local_dy": local_dy,
                "fov_x_deg": self.camera.fov_x_deg,
                "fov_y_deg": self.camera.fov_y_deg,
                "image_x_sign": self.camera.image_x_sign,
                "image_y_sign": self.camera.image_y_sign,
            },
        }

    def localize_detections(
        self,
        detections: list[dict[str, Any]],
        drone: dict[str, Any],
        *,
        image_width: int | float | None = None,
        image_height: int | float | None = None,
    ) -> list[dict[str, Any]]:
        estimates: list[dict[str, Any]] = []
        for detection in detections:
            if not self._passes_filters(detection):
                continue
            try:
                estimates.append(
                    self.localize_detection(
                        detection,
                        drone,
                        image_width=image_width,
                        image_height=image_height,
                    )
                )
            except ValueError:
                continue
        return estimates

    def _passes_filters(self, detection: dict[str, Any]) -> bool:
        confidence = self._optional_float(detection.get("confidence"), "confidence")
        if confidence is not None and confidence < self.min_confidence:
            return False
        if confidence is None and self.min_confidence > 0.0:
            return False
        if self.class_names is not None and detection.get("class_name") not in self.class_names:
            return False
        return True

    def _detection_error(
        self,
        detection: dict[str, Any],
        *,
        image_width: int | float | None,
        image_height: int | float | None,
    ) -> tuple[float, float]:
        if "ex" in detection and "ey" in detection:
            return (
                self._float_value(detection["ex"], "ex"),
                self._float_value(detection["ey"], "ey"),
            )

        if image_width is None:
            image_width = detection.get("image_width")
        if image_height is None:
            image_height = detection.get("image_height")

        if "cx" not in detection or "cy" not in detection:
            raise ValueError("ex/ey or cx/cy with image size are required")

        width = self._float_value(image_width, "image_width")
        height = self._float_value(image_height, "image_height")
        if width <= 0.0:
            raise ValueError("image_width must be positive")
        if height <= 0.0:
            raise ValueError("image_height must be positive")

        cx = self._float_value(detection["cx"], "cx")
        cy = self._float_value(detection["cy"], "cy")
        return (
            (cx - width / 2.0) / (width / 2.0),
            (cy - height / 2.0) / (height / 2.0),
        )

    def _altitude_m(self, drone: dict[str, Any]) -> float:
        for name in ("relative_altitude", "relative_altitude_m"):
            if name in drone:
                return self._validated_altitude(drone[name], name)

        if "local_z" in drone:
            local_z = self._float_value(drone["local_z"], "local_z")
            if local_z < 0.0:
                return self._validated_altitude(-local_z, "local_z")

        for name in ("altitude", "altitude_m"):
            if name in drone:
                return self._validated_altitude(drone[name], name)

        raise ValueError("usable altitude is required")

    def _validated_altitude(self, value: Any, name: str) -> float:
        altitude_m = self._float_value(value, name)
        if altitude_m < self.camera.min_altitude_m:
            raise ValueError("altitude_m is below min_altitude_m")
        return altitude_m

    def _required_float(self, data: dict[str, Any], name: str) -> float:
        if name not in data:
            raise ValueError(f"{name} is required")
        return self._float_value(data[name], name)

    def _optional_float(self, value: Any, name: str) -> float | None:
        if value is None:
            return None
        return self._float_value(value, name)

    def _float_value(self, value: Any, name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
        if not math.isfinite(result):
            raise ValueError(f"{name} must be finite")
        return result
