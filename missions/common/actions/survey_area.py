from __future__ import annotations

from typing import Any

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .multi_photo_fusion import MultiPhotoFusion, MultiPhotoFusionConfig
from .result import ActionResult
from .target_localization import CameraProjectionConfig, TargetLocalization


class SurveyAreaAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        waypoints = data.get("waypoints")
        if not isinstance(waypoints, list) or not waypoints:
            raise ValueError("waypoints must be a non-empty list")

        self.waypoints = [self._validated_waypoint(item) for item in waypoints]
        self.yaw_mode = str(data.get("yaw_mode", "hold")).strip().lower()
        if self.yaw_mode not in {"hold", "fixed", "arm_heading"}:
            raise ValueError("yaw_mode must be hold, fixed, or arm_heading")
        self.yaw_rad = None
        if self.yaw_mode == "fixed":
            self.yaw_rad = self._required_float(data, "yaw_rad")
        self.frame = int(data.get("frame", 1))
        self.goto_tolerance_xy_m = float(data.get("goto_tolerance_xy_m", 0.3))
        self.goto_tolerance_z_m = float(data.get("goto_tolerance_z_m", 0.3))
        self.goto_min_hold_updates = int(data.get("goto_min_hold_updates", 1))
        self.priority = int(data.get("priority", 4))

        self.capture_updates_per_waypoint = int(data.get("capture_updates_per_waypoint", 3))
        if self.capture_updates_per_waypoint < 1:
            raise ValueError("capture_updates_per_waypoint must be at least 1")
        self.max_updates_per_waypoint = int(data.get("max_updates_per_waypoint", 200))
        if self.max_updates_per_waypoint < self.capture_updates_per_waypoint:
            raise ValueError("max_updates_per_waypoint must be >= capture_updates_per_waypoint")

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("detection_source must be scene or perception")

        class_names = data.get("class_names")
        self.class_names = {str(name) for name in class_names} if class_names is not None else None
        camera_config = CameraProjectionConfig(**dict(data.get("camera") or {}))
        fusion_config = MultiPhotoFusionConfig(**dict(data.get("fusion") or {}))
        self.localizer = TargetLocalization(
            camera_config,
            min_confidence=float(data.get("min_confidence", 0.0)),
            class_names=self.class_names,
        )
        self.fusion = MultiPhotoFusion(fusion_config, class_names=self.class_names)

        self.waypoint_index = 0
        self.state = "goto"
        self.collected_estimates = []
        self.fused_objects = []
        self.waypoint_update_count = 0
        self.capture_count = 0
        self.yaw_defaulted = False
        self.stopped = False
        self.started = True
        self.goto_action = self._new_goto_action()

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")
        if self.state == "done":
            return ActionResult(done=True, reason="survey_done", detail=self._detail(done=True))
        if self.state == "failed":
            return ActionResult(
                failed=True,
                reason=self.failure_reason or "survey_failed",
                detail=self._detail(),
            )

        self.waypoint_update_count += 1
        if self.waypoint_update_count > self.max_updates_per_waypoint:
            self.state = "failed"
            self.failure_reason = "waypoint_timeout"
            return ActionResult(failed=True, reason="waypoint_timeout", detail=self._detail())

        data = context or {}
        if self.state == "goto":
            return self._update_goto(data)
        if self.state == "capture":
            return self._update_capture(data)
        return ActionResult(failed=True, reason="invalid_survey_state", detail=self._detail())

    def stop(self) -> None:
        self.stopped = True
        if self.goto_action is not None:
            self.goto_action.stop()

    def reset(self) -> None:
        self.waypoints: list[dict[str, float]] = []
        self.waypoint_index = 0
        self.state = "idle"
        self.goto_action: GotoWaypointAction | None = None
        self.localizer: TargetLocalization | None = None
        self.fusion: MultiPhotoFusion | None = None
        self.collected_estimates: list[dict[str, Any]] = []
        self.fused_objects: list[dict[str, Any]] = []
        self.waypoint_update_count = 0
        self.capture_count = 0
        self.capture_updates_per_waypoint = 3
        self.max_updates_per_waypoint = 200
        self.detection_source = "scene"
        self.class_names: set[str] | None = None
        self.yaw_mode = "hold"
        self.yaw_rad: float | None = None
        self.frame = 1
        self.goto_tolerance_xy_m = 0.3
        self.goto_tolerance_z_m = 0.3
        self.goto_min_hold_updates = 1
        self.priority = 4
        self.yaw_defaulted = False
        self.failure_reason = ""
        self.started = False
        self.stopped = False

    def _update_goto(self, context: dict[str, Any]) -> ActionResult:
        if self.goto_action is None:
            return ActionResult(failed=True, reason="goto_failed", detail=self._detail())
        result = self.goto_action.update(context)
        if result.failed:
            self.state = "failed"
            self.failure_reason = "goto_failed"
            return ActionResult(
                failed=True,
                reason="goto_failed",
                detail=self._detail(extra={"goto": result.detail, "goto_reason": result.reason}),
            )
        if not result.done:
            return ActionResult(
                actions=result.actions,
                reason="survey_goto",
                detail=self._detail(extra={"goto": result.detail, "goto_reason": result.reason}),
            )

        self.state = "capture"
        self.capture_count = 0
        return ActionResult(reason="survey_capture_started", detail=self._detail())

    def _update_capture(self, context: dict[str, Any]) -> ActionResult:
        drone = self._drone_context(context)
        detections, image_width, image_height = self._detections(context)
        estimates: list[dict[str, Any]] = []
        if self.localizer is not None and detections:
            try:
                estimates = self.localizer.localize_detections(
                    detections,
                    drone,
                    image_width=image_width,
                    image_height=image_height,
                )
            except Exception as exc:
                self.state = "failed"
                self.failure_reason = "localization_failed"
                return ActionResult(
                    failed=True,
                    reason="localization_failed",
                    detail=self._detail(extra={"error": str(exc)}),
                )
            self.collected_estimates.extend(estimates)

        self.capture_count += 1
        detail = self._detail(
            extra={
                "detections_count": len(detections),
                "new_estimates_count": len(estimates),
                "yaw_defaulted": self.yaw_defaulted,
            }
        )
        if self.capture_count < self.capture_updates_per_waypoint:
            return ActionResult(reason="survey_capture", detail=detail)

        if self.waypoint_index + 1 < len(self.waypoints):
            self.waypoint_index += 1
            self.state = "goto"
            self.capture_count = 0
            self.waypoint_update_count = 0
            self.goto_action = self._new_goto_action()
            return ActionResult(reason="survey_next_waypoint", detail=self._detail())

        self.fused_objects = (
            self.fusion.fuse(self.collected_estimates) if self.fusion is not None else []
        )
        self.state = "done"
        return ActionResult(done=True, reason="survey_done", detail=self._detail(done=True))

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
            "key": f"survey_waypoint_{self.waypoint_index}",
        }
        if self.yaw_mode == "fixed":
            params["yaw_rad"] = self.yaw_rad
        action = GotoWaypointAction()
        action.start(params)
        return action

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

    def _detail(
        self,
        *,
        done: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "state": self.state,
            "waypoint_index": self.waypoint_index,
            "waypoint_count": len(self.waypoints),
            "capture_count": self.capture_count,
            "collected_count": len(self.collected_estimates),
            "waypoint_update_count": self.waypoint_update_count,
        }
        if self.yaw_defaulted:
            detail["yaw_defaulted"] = True
        if done:
            detail["estimated_objects"] = self.fused_objects
        if extra:
            detail.update(extra)
        return detail

    def _validated_waypoint(self, value: Any) -> dict[str, float]:
        if not isinstance(value, dict):
            raise ValueError("waypoint must be a dict")
        x = self._required_float(value, "x")
        y = self._required_float(value, "y")
        altitude_m = self._required_float(value, "altitude_m")
        if altitude_m <= 0.0:
            raise ValueError("altitude_m must be positive")
        return {"x": x, "y": y, "altitude_m": altitude_m}

    def _required_float(self, params: dict[str, Any], name: str) -> float:
        if name not in params:
            raise ValueError(f"{name} is required")
        try:
            return float(params[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
