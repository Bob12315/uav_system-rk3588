from __future__ import annotations

import time
import uuid
from typing import Any

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .multi_photo_fusion import MultiPhotoFusion, MultiPhotoFusionConfig
from .result import ActionResult
from .target_localization import CameraProjectionConfig, TargetLocalization


class MultiViewLocalizeAction(ActionModule):
    """Fly to four observation points around the starting position, collect
    YOLO detections at each, and fuse them into localized object coordinates.

    No best_target selection, no auto-lock, no payload release.  The output
    is a list of *localized_objects* that the caller can display or use.
    """

    def __init__(self) -> None:
        self.reset()

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        self.waypoint_mode = str(data.get("waypoint_mode", "relative_to_start")).strip().lower()
        if self.waypoint_mode not in {"relative_to_start", "absolute"}:
            raise ValueError("waypoint_mode must be relative_to_start or absolute")

        waypoints_raw = data.get("waypoints")
        self.waypoints: list[dict[str, float]] | None = None
        if self.waypoint_mode == "absolute":
            if not isinstance(waypoints_raw, list) or not waypoints_raw:
                raise ValueError("waypoints must be a non-empty list when waypoint_mode=absolute")
            self.waypoints = [self._validated_waypoint(item) for item in waypoints_raw]

        self.radius_m = float(data.get("radius_m", 0.8))
        self.altitude_m_obs = float(data.get("altitude_m", 3.0))
        if self.altitude_m_obs <= 0.0:
            raise ValueError("altitude_m must be positive")

        self.yaw_mode = str(data.get("yaw_mode", "arm_heading")).strip().lower()
        if self.yaw_mode not in {"hold", "fixed", "arm_heading"}:
            raise ValueError("yaw_mode must be hold, fixed, or arm_heading")
        self.yaw_rad = None
        if self.yaw_mode == "fixed":
            self.yaw_rad = self._required_float(data, "yaw_rad")
        self.frame = int(data.get("frame", 1))

        self.capture_updates_per_waypoint = int(data.get("capture_updates_per_waypoint", 3))
        if self.capture_updates_per_waypoint < 1:
            raise ValueError("capture_updates_per_waypoint must be at least 1")
        self.settle_updates_per_waypoint = int(data.get("settle_updates_per_waypoint", 3))
        self.max_updates_per_waypoint = int(data.get("max_updates_per_waypoint", 100))
        if self.max_updates_per_waypoint < (self.settle_updates_per_waypoint + self.capture_updates_per_waypoint):
            raise ValueError("max_updates_per_waypoint must be >= settle + capture updates")

        self.goto_tolerance_xy_m = float(data.get("tolerance_xy_m", 0.3))
        self.goto_tolerance_z_m = float(data.get("tolerance_z_m", 0.3))
        self.goto_min_hold_updates = int(data.get("goto_min_hold_updates", 1))
        self.priority = int(data.get("priority", 5))

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("detection_source must be scene or perception")

        class_names = data.get("class_names")
        self.class_names = {str(name) for name in class_names} if class_names is not None else None
        camera_config = CameraProjectionConfig(
            **self._normalized_camera_params(dict(data.get("camera") or {}))
        )
        fusion_config = MultiPhotoFusionConfig(**dict(data.get("fusion") or {}))
        self.localizer = TargetLocalization(
            camera_config,
            min_confidence=float(data.get("min_confidence", 0.25)),
            class_names=self.class_names,
        )
        self.fusion = MultiPhotoFusion(fusion_config, class_names=self.class_names)

        self.save_result = bool(data.get("save_result", True))
        self.run_id = str(uuid.uuid4())[:8]

        self.phase = "init" if self.waypoints is None else "goto"
        self.waypoint_index = 0
        self.raw_estimates: list[dict[str, Any]] = []
        self.captures: list[dict[str, Any]] = []
        self.settle_count = 0
        self.capture_count = 0
        self.update_count_at_waypoint = 0
        self.fused_objects: list[dict[str, Any]] = []
        self.failure_reason = ""
        self.yaw_defaulted = False
        self.started = True
        self.stopped = False
        self.goto_action: GotoWaypointAction | None = None
        if self.waypoints is not None:
            self.goto_action = self._new_goto_action()

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")
        if self.phase == "done":
            return ActionResult(
                done=True,
                reason="multi_view_localized",
                detail=self._detail(done=True),
            )
        if self.phase == "failed":
            return ActionResult(
                failed=True,
                reason=self.failure_reason or "multi_view_failed",
                detail=self._detail(),
            )

        self.update_count_at_waypoint += 1
        if self.update_count_at_waypoint > self.max_updates_per_waypoint:
            self.phase = "failed"
            self.failure_reason = "waypoint_timeout"
            return ActionResult(failed=True, reason="waypoint_timeout", detail=self._detail())

        data = context or {}

        if self.phase == "init":
            return self._update_init(data)
        if self.phase == "goto":
            return self._update_goto(data)
        if self.phase == "settle":
            return self._update_settle()
        if self.phase == "capture":
            return self._update_capture(data)
        return ActionResult(failed=True, reason="invalid_phase", detail=self._detail())

    def stop(self) -> None:
        self.stopped = True
        if self.goto_action is not None:
            self.goto_action.stop()

    def reset(self) -> None:
        self.waypoints = None
        self.waypoint_index = 0
        self.phase = "idle"
        self.goto_action = None
        self.localizer = TargetLocalization(CameraProjectionConfig())
        self.fusion = MultiPhotoFusion(MultiPhotoFusionConfig())
        self.raw_estimates = []
        self.captures = []
        self.fused_objects = []
        self.settle_count = 0
        self.capture_count = 0
        self.update_count_at_waypoint = 0
        self.waypoint_mode = "relative_to_start"
        self.radius_m = 0.8
        self.altitude_m_obs = 3.0
        self.yaw_mode = "hold"
        self.yaw_rad = None
        self.frame = 1
        self.capture_updates_per_waypoint = 3
        self.settle_updates_per_waypoint = 3
        self.max_updates_per_waypoint = 100
        self.goto_tolerance_xy_m = 0.3
        self.goto_tolerance_z_m = 0.3
        self.goto_min_hold_updates = 1
        self.priority = 5
        self.detection_source = "scene"
        self.class_names = None
        self.save_result = True
        self.run_id = ""
        self.yaw_defaulted = False
        self.failure_reason = ""
        self.started = False
        self.stopped = False

    # ── phase handlers ──────────────────────────────────────────────

    def _update_init(self, context: dict[str, Any]) -> ActionResult:
        """Generate four waypoints around the current drone position."""
        center_x, center_y = self._current_position(context)
        r = self.radius_m
        alt = self.altitude_m_obs
        self.waypoints = [
            {"x": center_x + r, "y": center_y,        "altitude_m": alt},
            {"x": center_x - r, "y": center_y,        "altitude_m": alt},
            {"x": center_x,      "y": center_y + r,    "altitude_m": alt},
            {"x": center_x,      "y": center_y - r,    "altitude_m": alt},
        ]
        self.phase = "goto"
        self.waypoint_index = 0
        self.update_count_at_waypoint = 0
        self.goto_action = self._new_goto_action()
        return self._update_goto(context)

    def _update_goto(self, context: dict[str, Any]) -> ActionResult:
        if self.goto_action is None:
            return ActionResult(failed=True, reason="goto_failed", detail=self._detail())
        result = self.goto_action.update(context)
        if result.failed:
            self.phase = "failed"
            self.failure_reason = "goto_failed"
            return ActionResult(
                failed=True,
                reason="goto_failed",
                detail=self._detail(extra={"goto": result.detail, "goto_reason": result.reason}),
            )
        if not result.done:
            return ActionResult(
                actions=result.actions,
                reason="multi_view_goto",
                detail=self._detail(extra={"goto": result.detail, "goto_reason": result.reason}),
            )

        self.phase = "settle"
        self.settle_count = 0
        return ActionResult(reason="multi_view_settle", detail=self._detail())

    def _update_settle(self) -> ActionResult:
        self.settle_count += 1
        if self.settle_count >= self.settle_updates_per_waypoint:
            self.phase = "capture"
            self.capture_count = 0
            return ActionResult(reason="multi_view_capture", detail=self._detail())
        return ActionResult(reason="multi_view_settle", detail=self._detail())

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
                self.phase = "failed"
                self.failure_reason = "localization_failed"
                return ActionResult(
                    failed=True,
                    reason="localization_failed",
                    detail=self._detail(extra={"error": str(exc)}),
                )
            self.raw_estimates.extend(estimates)

        self.capture_count += 1
        self.captures.append({
            "waypoint_index": self.waypoint_index,
            "detections_count": len(detections),
            "estimates_count": len(estimates),
            "drone": {k: drone.get(k) for k in ("local_x", "local_y", "local_z", "yaw", "relative_altitude")},
        })
        detail = self._detail(extra={
            "detections_count": len(detections),
            "new_estimates_count": len(estimates),
            "yaw_defaulted": self.yaw_defaulted,
        })
        if self.capture_count < self.capture_updates_per_waypoint:
            return ActionResult(reason="multi_view_capture", detail=detail)

        # move to next waypoint or finish
        if self.waypoint_index + 1 < len(self.waypoints or []):
            self.waypoint_index += 1
            self.phase = "goto"
            self.capture_count = 0
            self.update_count_at_waypoint = 0
            self.goto_action = self._new_goto_action()
            return ActionResult(reason="multi_view_next_waypoint", detail=self._detail())

        # fuse all estimates
        self.fused_objects = (
            self.fusion.fuse(self.raw_estimates) if self.fusion is not None else []
        )
        if not self.fused_objects:
            self.phase = "failed"
            self.failure_reason = "no_target_fused"
            return ActionResult(failed=True, reason="no_target_fused", detail=self._detail())
        self.phase = "done"
        return ActionResult(done=True, reason="multi_view_localized", detail=self._detail(done=True))

    # ── helpers ─────────────────────────────────────────────────────

    def _new_goto_action(self) -> GotoWaypointAction:
        wp = self.waypoints[self.waypoint_index]  # type: ignore[index]
        gp: dict[str, Any] = {
            "x": wp["x"],
            "y": wp["y"],
            "altitude_m": wp["altitude_m"],
            "yaw_mode": self.yaw_mode,
            "frame": self.frame,
            "tolerance_xy_m": self.goto_tolerance_xy_m,
            "tolerance_z_m": self.goto_tolerance_z_m,
            "min_hold_updates": self.goto_min_hold_updates,
            "priority": self.priority,
            "key": f"mvl_waypoint_{self.waypoint_index}",
        }
        if self.yaw_mode == "fixed":
            gp["yaw_rad"] = self.yaw_rad
        action = GotoWaypointAction()
        action.start(gp)
        return action

    def _current_position(self, context: dict[str, Any]) -> tuple[float, float]:
        drone = context.get("drone")
        if isinstance(drone, dict):
            if "local_x" in drone and "local_y" in drone:
                return (float(drone["local_x"]), float(drone["local_y"]))
            lp = drone.get("local_position")
            if isinstance(lp, dict) and "x" in lp and "y" in lp:
                return (float(lp["x"]), float(lp["y"]))
        lp = context.get("local_position")
        if isinstance(lp, dict):
            return (float(lp.get("x", 0.0)), float(lp.get("y", 0.0)))
        raise ValueError("current position unavailable — need drone.local_x/local_y or local_position.x/y")

    def _detections(
        self, context: dict[str, Any],
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
        self, local_position: dict[str, Any], yaw: Any,
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

    def _detail(self, *, done: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "run_id": self.run_id,
            "phase": self.phase,
            "waypoint_index": self.waypoint_index,
            "waypoint_count": len(self.waypoints or []),
            "capture_count": self.capture_count,
            "captures_count": len(self.captures),
            "raw_estimates_count": len(self.raw_estimates),
            "update_count_at_waypoint": self.update_count_at_waypoint,
            "coordinate_frame": "LOCAL_NED",
        }
        if self.yaw_defaulted:
            detail["yaw_defaulted"] = True
        if done:
            # build localized_objects — flatten MultiPhotoFusion output into the canonical format
            localized_objects: list[dict[str, Any]] = []
            for obj in self.fused_objects:
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
            detail["object_count"] = len(localized_objects)
            detail["captures"] = self.captures
            detail["waypoints"] = self.waypoints
            if self.fusion is not None:
                detail["fusion_debug"] = self.fusion.last_debug
        if extra:
            detail.update(extra)
        return detail

    # ── validation ──────────────────────────────────────────────────

    def _validated_waypoint(self, value: Any) -> dict[str, float]:
        if not isinstance(value, dict):
            raise ValueError("waypoint must be a dict")
        x = self._required_float(value, "x")
        y = self._required_float(value, "y")
        altitude_m = self._required_float(value, "altitude_m")
        if altitude_m <= 0.0:
            raise ValueError("altitude_m must be positive")
        return {"x": x, "y": y, "altitude_m": altitude_m}

    def _normalized_camera_params(self, camera: dict[str, Any]) -> dict[str, Any]:
        if "horizontal_fov_deg" in camera and "fov_x_deg" not in camera:
            camera["fov_x_deg"] = camera["horizontal_fov_deg"]
        if "vertical_fov_deg" in camera and "fov_y_deg" not in camera:
            camera["fov_y_deg"] = camera["vertical_fov_deg"]
        for name in ("horizontal_fov_deg", "vertical_fov_deg", "model"):
            camera.pop(name, None)
        return camera

    def _required_float(self, params: dict[str, Any], name: str) -> float:
        if name not in params:
            raise ValueError(f"{name} is required")
        try:
            return float(params[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
