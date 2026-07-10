"""GPS-first multi-view localize action.

Feature 2.4 — GPS-first scan localization.

Flown sequence:
    1. Resolve DROP_SCAN_1..4 as GLOBAL GPS targets from frozen runtime reference.
    2. Fly to each with ``GotoWaypointAction`` (target_frame=global).
    3. At each scan point, capture detections with capture-time telemetry snapshot.
    4. Project each detection to raw GPS estimate via ``GpsTargetProjector``.
    5. Fuse all raw estimates into ``localized_objects`` with lat/lon.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT

from app.runtime_field_target_resolver import (
    RuntimeFieldTargetResolver,
    RuntimeFieldTargetError,
)

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .gps_target_projection import (
    GpsProjectionCamera,
    GpsProjectionError,
    GpsRawEstimate,
    GpsTargetProjector,
)
from .gps_derived_enu_fusion import (
    GpsDerivedEnuFusion,
    GpsFusionConfig,
    GpsLocalizedObject,
)
from .result import ActionResult


class GpsMultiViewLocalizeAction(ActionModule):
    """GPS-first multi-view scan localization.

    Requires a *frozen* runtime field reference.  Flies to 4 GLOBAL
    scan points derived from the v3 profile's drop_scan waypoints,
    captures YOLO detections at each, projects them to GPS, and
    fuses into GPS-localized objects.
    """

    def __init__(self) -> None:
        self.reset()

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        # Resolver inputs
        profile = data.get("profile")
        reference = data.get("field_reference")
        if profile is None:
            raise ValueError("profile is required for GPS multi-view localize")
        if reference is None:
            raise ValueError("field_reference is required")

        self.resolver = RuntimeFieldTargetResolver(profile, reference)
        if not self.resolver.is_ready:
            raise RuntimeFieldTargetError(self.resolver.error or "resolver not ready")

        # Scan targets
        self.scan_targets = list(self.resolver.scan_waypoints())
        self.home_target = self.resolver.home()

        # Camera
        cam_raw = dict(data.get("camera") or {})
        if "fov_x_deg" not in cam_raw:
            cam_raw["fov_x_deg"] = 51.3
        if "fov_y_deg" not in cam_raw:
            cam_raw["fov_y_deg"] = 39.6
        self.camera = GpsProjectionCamera(**cam_raw)
        self.projector = GpsTargetProjector(self.camera)

        # Fusion
        fusion_cfg = dict(data.get("fusion") or {})
        origin_lat = reference.origin_lat
        origin_lon = reference.origin_lon
        self.fuser = GpsDerivedEnuFusion(
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            config=GpsFusionConfig(**{k: v for k, v in fusion_cfg.items()
                                       if k in GpsFusionConfig.__dataclass_fields__}),
            class_names=(set(data["class_names"]) if data.get("class_names") else None),
        )

        # Goto params
        self.yaw_mode = str(data.get("yaw_mode", "hold")).strip().lower()
        self.goto_tolerance_xy_m = float(data.get("tolerance_xy_m", 0.3))
        self.goto_tolerance_z_m = float(data.get("tolerance_z_m", 0.3))
        self.goto_min_hold_updates = int(data.get("goto_min_hold_updates", 1))
        self.priority = int(data.get("priority", 5))

        # Capture params
        self.capture_updates_per_waypoint = int(data.get("capture_updates_per_waypoint", 3))
        self.settle_updates_per_waypoint = int(data.get("settle_updates_per_waypoint", 3))
        self.max_updates_per_waypoint = int(data.get("max_updates_per_waypoint", 100))

        self.min_confidence = float(data.get("min_confidence", 0.25))
        class_names = data.get("class_names")
        self.class_names = {str(n) for n in class_names} if class_names else None

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()

        # State
        self.phase = "goto"
        self.waypoint_index = 0
        self.raw_estimates: list[GpsRawEstimate] = []
        self.fused_objects: list[GpsLocalizedObject] = []
        self.settle_count = 0
        self.capture_count = 0
        self.update_count_at_waypoint = 0
        self.captures: list[dict[str, Any]] = []
        self.failure_reason = ""
        self.goto_action: GotoWaypointAction | None = None
        self.run_id = str(uuid.uuid4())[:8]

        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")
        if self.phase == "done":
            return ActionResult(done=True, reason="gps_multi_view_localized",
                                detail=self._detail(done=True))
        if self.phase == "failed":
            return ActionResult(failed=True, reason=self.failure_reason or "gps_multi_view_failed",
                                detail=self._detail())

        self.update_count_at_waypoint += 1
        if self.update_count_at_waypoint > self.max_updates_per_waypoint:
            self.phase = "failed"
            self.failure_reason = "waypoint_timeout"
            return ActionResult(failed=True, reason="waypoint_timeout", detail=self._detail())

        data = context or {}

        if self.phase == "goto":
            return self._update_goto(data)
        if self.phase == "settle":
            return self._update_settle()
        if self.phase == "capture":
            return self._update_capture(data)
        return ActionResult(failed=True, reason="invalid_phase")

    def stop(self) -> None:
        self.stopped = True
        if self.goto_action is not None:
            self.goto_action.stop()

    def reset(self) -> None:
        self.resolver = None
        self.scan_targets = []
        self.home_target = None
        self.camera = GpsProjectionCamera()
        self.projector = GpsTargetProjector()
        self.fuser = None
        self.waypoint_index = 0
        self.phase = "idle"
        self.goto_action = None
        self.raw_estimates = []
        self.fused_objects = []
        self.settle_count = 0
        self.capture_count = 0
        self.update_count_at_waypoint = 0
        self.captures = []
        self.failure_reason = ""
        self.run_id = ""
        self.started = False
        self.stopped = False

    # ── phase handlers ──────────────────────────────────────────────

    def _update_goto(self, context: dict[str, Any]) -> ActionResult:
        if self.goto_action is None:
            self.goto_action = self._new_goto_action()
        result = self.goto_action.update(context)
        if result.failed:
            self.phase = "failed"
            self.failure_reason = "goto_failed"
            return ActionResult(failed=True, reason="goto_failed", detail=self._detail(extra={"goto": result.detail}))
        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_multi_view_goto", detail=self._detail(extra={"goto": result.detail}))

        self.phase = "settle"
        self.settle_count = 0
        return ActionResult(reason="gps_multi_view_settle", detail=self._detail())

    def _update_settle(self) -> ActionResult:
        self.settle_count += 1
        if self.settle_count >= self.settle_updates_per_waypoint:
            self.phase = "capture"
            self.capture_count = 0
            return ActionResult(reason="gps_multi_view_capture", detail=self._detail())
        return ActionResult(reason="gps_multi_view_settle", detail=self._detail())

    def _update_capture(self, context: dict[str, Any]) -> ActionResult:
        # Snapshot capture-time telemetry — record BEFORE any fusion step
        capture_snapshot = self._capture_snapshot(context)

        detections, image_width, image_height = self._detections(context)
        new_estimates: list[GpsRawEstimate] = []

        for det in detections:
            # Class filter
            class_name = str(det.get("class_name") or "")
            if self.class_names and class_name not in self.class_names:
                continue
            # Confidence filter
            conf = det.get("confidence")
            if conf is not None and float(conf) < self.min_confidence:
                continue

            try:
                est = self.projector.project_detection(
                    det, capture_snapshot,
                    image_width=image_width, image_height=image_height,
                )
                # Tag with waypoint
                est = GpsRawEstimate(
                    lat=est.lat, lon=est.lon,
                    east_offset_m=est.east_offset_m, north_offset_m=est.north_offset_m,
                    capture_drone_lat=est.capture_drone_lat,
                    capture_drone_lon=est.capture_drone_lon,
                    capture_yaw_rad=est.capture_yaw_rad,
                    capture_relative_altitude_m=est.capture_relative_altitude_m,
                    ex=est.ex, ey=est.ey,
                    class_name=est.class_name, confidence=est.confidence,
                    track_id=est.track_id, frame_id=est.frame_id,
                    timestamp=est.timestamp,
                    source_waypoint=f"DROP_SCAN_{self.waypoint_index + 1}",
                )
                new_estimates.append(est)
            except GpsProjectionError:
                continue

        self.raw_estimates.extend(new_estimates)
        self.captures.append({
            "waypoint_index": self.waypoint_index,
            "detections_count": len(detections),
            "new_estimates_count": len(new_estimates),
            "drone_snapshot": capture_snapshot,
        })

        self.capture_count += 1
        detail = self._detail(extra={
            "detections_count": len(detections),
            "new_estimates_count": len(new_estimates),
        })

        if self.capture_count < self.capture_updates_per_waypoint:
            return ActionResult(reason="gps_multi_view_capture", detail=detail)

        # Next waypoint or finish
        if self.waypoint_index + 1 < len(self.scan_targets):
            self.waypoint_index += 1
            self.phase = "goto"
            self.capture_count = 0
            self.update_count_at_waypoint = 0
            self.goto_action = self._new_goto_action()
            return ActionResult(reason="gps_multi_view_next_waypoint", detail=self._detail())

        # Fuse
        if not self.raw_estimates:
            self.phase = "failed"
            self.failure_reason = "no_targets"
            return ActionResult(failed=True, reason="no_targets", detail=self._detail())

        self.fused_objects = self.fuser.fuse(self.raw_estimates) if self.fuser else []
        if not self.fused_objects:
            self.phase = "failed"
            self.failure_reason = "no_target_fused"
            return ActionResult(failed=True, reason="no_target_fused", detail=self._detail())

        self.phase = "done"
        return ActionResult(done=True, reason="gps_multi_view_localized", detail=self._detail(done=True))

    # ── helpers ─────────────────────────────────────────────────────

    def _new_goto_action(self) -> GotoWaypointAction:
        t = self.scan_targets[self.waypoint_index]
        gp: dict[str, Any] = {
            "x": t.lat,
            "y": t.lon,
            "altitude_m": t.altitude_m,
            "waypoint_mode": "absolute",
            "target_frame": "global",
            "yaw_mode": self.yaw_mode,
            "frame": GLOBAL_RELATIVE_ALT_INT,
            "tolerance_xy_m": self.goto_tolerance_xy_m,
            "tolerance_z_m": self.goto_tolerance_z_m,
            "min_hold_updates": self.goto_min_hold_updates,
            "priority": self.priority,
            "key": f"gps_scan_{self.waypoint_index}",
        }
        action = GotoWaypointAction()
        action.start(gp)
        return action

    def _capture_snapshot(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract capture-time telemetry from context.

        Records the drone's GPS, yaw, and altitude at capture time.
        Subsequent drone movement must not affect this snapshot.
        """
        drone = (context or {}).get("drone")
        if not isinstance(drone, dict):
            raise ValueError("drone context required for GPS capture")

        lat = drone.get("lat")
        lon = drone.get("lon")
        yaw = drone.get("yaw")
        alt = drone.get("relative_altitude") or drone.get("relative_altitude_m")
        if alt is None:
            alt = drone.get("altitude") or drone.get("altitude_m")

        return {
            "drone_lat": float(lat) if lat is not None else None,
            "drone_lon": float(lon) if lon is not None else None,
            "drone_yaw_rad": float(yaw) if yaw is not None else None,
            "relative_altitude_m": float(alt) if alt is not None else None,
            "source_waypoint": f"DROP_SCAN_{self.waypoint_index + 1}",
        }

    def _detections(self, context: dict[str, Any]) -> tuple[list[dict[str, Any]], int | float | None, int | float | None]:
        if self.detection_source == "scene":
            scene = (context or {}).get("scene")
            if not isinstance(scene, dict):
                return [], None, None
            dets = scene.get("detections")
            if not isinstance(dets, list):
                dets = []
            return ([d for d in dets if isinstance(d, dict)],
                    scene.get("image_width"), scene.get("image_height"))
        perception = (context or {}).get("perception")
        if not isinstance(perception, dict):
            return [], None, None
        return [perception], perception.get("image_width"), perception.get("image_height")

    def _detail(self, *, done: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "run_id": self.run_id,
            "phase": self.phase,
            "waypoint_index": self.waypoint_index,
            "waypoint_count": len(self.scan_targets),
            "capture_count": self.capture_count,
            "captures_count": len(self.captures),
            "raw_estimates_count": len(self.raw_estimates),
            "coordinate_frame": "GLOBAL",
            "target_frame": "global",
        }
        if done:
            localized_objects: list[dict[str, Any]] = []
            for obj in self.fused_objects:
                localized_objects.append({
                    "id": obj.id,
                    "lat": obj.lat,
                    "lon": obj.lon,
                    "east_m": obj.east_m,
                    "north_m": obj.north_m,
                    "sample_count": obj.sample_count,
                    "raw_count": obj.raw_count,
                    "class_name": obj.class_name,
                    "confidence": obj.confidence,
                    "cluster_spread_m": obj.cluster_spread_m,
                    "source_waypoints": list(obj.source_waypoints),
                    "source_frames": list(obj.source_frames),
                })
            detail["localized_objects"] = localized_objects
            detail["object_count"] = len(localized_objects)
            # Raw estimates as plain dicts for serialization
            detail["raw_estimates"] = [
                {
                    "lat": e.lat, "lon": e.lon,
                    "east_offset_m": e.east_offset_m, "north_offset_m": e.north_offset_m,
                    "capture_drone_lat": e.capture_drone_lat,
                    "capture_drone_lon": e.capture_drone_lon,
                    "capture_yaw_rad": e.capture_yaw_rad,
                    "capture_relative_altitude_m": e.capture_relative_altitude_m,
                    "ex": e.ex, "ey": e.ey,
                    "class_name": e.class_name, "confidence": e.confidence,
                    "source_waypoint": e.source_waypoint,
                }
                for e in self.raw_estimates
            ]
            detail["captures"] = self.captures
        if extra:
            detail.update(extra)
        return detail
