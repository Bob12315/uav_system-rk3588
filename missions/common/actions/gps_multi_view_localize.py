"""GPS-first multi-view localize action (runtime context integration).

Feature 2.4 — GPS-first scan localization via Action Lab + runtime context.

Reads ``context["field_reference"]`` in first ``update()`` to initialise
the resolver.  All params are JSON-safe dicts (no Python objects).
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

    On first ``update(context)``, reads ``context["field_reference"]`` to
    initialise the resolver.  Flies to 4 GLOBAL scan points, captures
    detections, GPS-projects, and fuses.
    """

    def __init__(self) -> None:
        self.reset()

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        # Store params for deferred init
        self._params_profile_id: str = str(data.get("profile_id") or "")
        self._params_capture_updates: int = int(data.get("capture_updates_per_waypoint", 3))
        self._params_settle_updates: int = int(data.get("settle_updates_per_waypoint", 2))
        self._params_max_updates: int = int(data.get("max_updates_per_waypoint", 100))
        self._params_tolerance_xy: float = float(data.get("tolerance_xy_m", 0.35))
        self._params_tolerance_z: float = float(data.get("tolerance_z_m", 0.35))
        self._params_goto_min_hold: int = int(data.get("goto_min_hold_updates", 1))
        self._params_priority: int = int(data.get("priority", 5))
        self._params_detection_source: str = str(data.get("detection_source", "scene"))
        self._params_class_names: list[str] | None = (
            [str(n) for n in data["class_names"]] if data.get("class_names") else None
        )
        self._params_min_confidence: float = float(data.get("min_confidence", 0.35))

        cam_raw = dict(data.get("camera") or {})
        cam_raw.setdefault("fov_x_deg", 51.3)
        cam_raw.setdefault("fov_y_deg", 39.6)
        self.camera = GpsProjectionCamera(**cam_raw)

        fusion_raw = dict(data.get("fusion") or {})
        self._fusion_config = GpsFusionConfig(**{
            k: v for k, v in fusion_raw.items()
            if k in GpsFusionConfig.__dataclass_fields__
        })

        self.yaw_mode = str(data.get("yaw_mode", "hold")).strip().lower()

        # Deferred init
        self._initialized = False
        self.resolver: RuntimeFieldTargetResolver | None = None
        self.projector: GpsTargetProjector | None = None
        self.fuser: GpsDerivedEnuFusion | None = None
        self.scan_targets: list[Any] = []
        self.home_target: Any = None

        # State
        self.phase = "init"
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
        self.rejected_by_reason: dict[str, int] = {}

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

        # Shared timeout: covers goto + settle + capture per waypoint
        if self.phase != "init":
            self.update_count_at_waypoint += 1
            if self.update_count_at_waypoint > self._params_max_updates:
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
        return ActionResult(failed=True, reason="invalid_phase")

    def stop(self) -> None:
        self.stopped = True
        if self.goto_action is not None:
            self.goto_action.stop()

    def reset(self) -> None:
        self._initialized = False
        self.resolver = None
        self.projector = None
        self.fuser = None
        self.scan_targets = []
        self.waypoint_index = 0
        self.phase = "idle"
        self.goto_action = None
        self.raw_estimates = []
        self.fused_objects = []
        self.captures = []
        self.rejected_by_reason = {}
        self.failure_reason = ""
        self.run_id = ""
        self.started = False
        self.stopped = False

    # ── deferred init ─────────────────────────────────────────────────

    def _update_init(self, context: dict[str, Any]) -> ActionResult:
        """First update: initialise resolver from context["field_reference"]."""
        fr = context.get("field_reference")
        if not isinstance(fr, dict):
            self.phase = "failed"
            self.failure_reason = "missing_field_reference_context"
            return ActionResult(failed=True, reason="missing_field_reference_context")

        try:
            self.resolver = RuntimeFieldTargetResolver(fr)
        except Exception as exc:
            self.phase = "failed"
            self.failure_reason = f"resolver_init_failed: {exc}"
            return ActionResult(failed=True, reason="resolver_init_failed")

        if not self.resolver.is_ready:
            self.phase = "failed"
            self.failure_reason = self.resolver.error or "resolver not ready"
            return ActionResult(failed=True, reason="resolver_not_ready")

        # Profile ID check
        if self._params_profile_id:
            if self._params_profile_id != self.resolver.profile_id:
                self.phase = "failed"
                self.failure_reason = f"profile_id mismatch: params={self._params_profile_id} runtime={self.resolver.profile_id}"
                return ActionResult(failed=True, reason="profile_id_mismatch")

        # Scan targets
        self.scan_targets = list(self.resolver.scan_waypoints())

        # Projector
        self.projector = GpsTargetProjector(self.camera)

        # Fuser
        rb = fr.get("runtime_binding", {})
        origin_lat = None
        origin_lon = None
        geom = rb.get("geometry", {}) if isinstance(rb, dict) else {}
        home = geom.get("home", {}) if isinstance(geom, dict) else {}
        if isinstance(home, dict):
            origin_lat = home.get("lat")
            origin_lon = home.get("lon")
        if origin_lat is None or origin_lon is None:
            self.phase = "failed"
            self.failure_reason = "missing_origin_in_geometry"
            return ActionResult(failed=True, reason="missing_origin_in_geometry")

        self.fuser = GpsDerivedEnuFusion(
            origin_lat=float(origin_lat),
            origin_lon=float(origin_lon),
            config=self._fusion_config,
            class_names=set(self._params_class_names) if self._params_class_names else None,
        )

        self._initialized = True
        self.phase = "goto"
        self.waypoint_index = 0
        self.goto_action = self._new_goto_action()
        return self._update_goto(context)

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
        if self.settle_count >= self._params_settle_updates:
            self.phase = "capture"
            self.capture_count = 0
            return ActionResult(reason="gps_multi_view_capture", detail=self._detail())
        return ActionResult(reason="gps_multi_view_settle", detail=self._detail())

    def _update_capture(self, context: dict[str, Any]) -> ActionResult:
        # ── capture-time: per-detection telemetry priority ───────────
        drone_snapshot = self._drone_snapshot(context)
        detections, image_width, image_height = self._detections(context)
        if drone_snapshot is None:
            self.phase = "failed"
            self.failure_reason = "invalid_capture_telemetry"
            return ActionResult(failed=True, reason="invalid_capture_telemetry",
                                detail=self._detail())

        new_estimates: list[GpsRawEstimate] = []

        for det in detections:
            try:
                # Class filter
                class_name = str(det.get("class_name") or "")
                if self._params_class_names and class_name not in self._params_class_names:
                    self._inc_reject("class_not_allowed")
                    continue

                # Confidence filter
                conf = det.get("confidence")
                if conf is not None:
                    try:
                        cf = float(conf)
                    except (TypeError, ValueError):
                        self._inc_reject("invalid_confidence")
                        continue
                    if cf < self._params_min_confidence:
                        self._inc_reject("low_confidence")
                        continue

                # Extract ex/ey
                ex, ey = self._detection_ex_ey(det, image_width, image_height)
                if ex is None:
                    self._inc_reject("missing_ex_ey")
                    continue

                # ── per-detection telemetry resolution ─────────────
                # Priority: 1) detection.capture_telemetry  2) detection.source
                #           3) scene.capture_telemetry      4) drone snapshot
                telem = self._resolve_detection_telemetry(det, context, drone_snapshot)
                if telem is None:
                    self._inc_reject("invalid_detection_capture_telemetry")
                    continue

                # GPS project
                est = self.projector.project(
                    drone_lat=telem["drone_lat"],
                    drone_lon=telem["drone_lon"],
                    drone_yaw_rad=telem["drone_yaw_rad"],
                    relative_altitude_m=telem["relative_altitude_m"],
                    ex=ex, ey=ey,
                    class_name=class_name,
                    confidence=conf,
                    track_id=_opt_int(det.get("track_id")),
                    frame_id=_opt_int(det.get("frame_id")),
                    timestamp=_opt_float(det.get("timestamp")),
                    source_waypoint=f"DROP_SCAN_{self.waypoint_index + 1}",
                )
                new_estimates.append(est)
            except (GpsProjectionError, ValueError, TypeError):
                self._inc_reject("projection_failed")
                continue

        self.raw_estimates.extend(new_estimates)
        self.captures.append({
            "waypoint_index": self.waypoint_index,
            "detections_count": len(detections),
            "new_estimates_count": len(new_estimates),
            "drone_snapshot": {k: v for k, v in (drone_snapshot or {}).items() if k != "source_waypoint"},
        })

        self.capture_count += 1
        detail = self._detail(extra={
            "detections_count": len(detections),
            "new_estimates_count": len(new_estimates),
        })

        if self.capture_count < self._params_capture_updates:
            return ActionResult(reason="gps_multi_view_capture", detail=detail)

        # Next waypoint or finish
        if self.waypoint_index + 1 < len(self.scan_targets):
            self.waypoint_index += 1
            self.phase = "goto"
            self.capture_count = 0
            self.goto_action = self._new_goto_action()
            return ActionResult(reason="gps_multi_view_next_waypoint", detail=self._detail())

        # Fuse
        if not self.raw_estimates:
            self.phase = "failed"
            self.failure_reason = "no_targets"
            return ActionResult(failed=True, reason="no_targets", detail=self._detail())

        self.fused_objects = self.fuser.fuse(self.raw_estimates)
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
            "lat": t.lat,
            "lon": t.lon,
            "altitude_m": t.altitude_m,
            "target_frame": "global",
            "waypoint_mode": "absolute",
            "yaw_mode": self.yaw_mode,
            "frame": GLOBAL_RELATIVE_ALT_INT,
            "tolerance_xy_m": self._params_tolerance_xy,
            "tolerance_z_m": self._params_tolerance_z,
            "min_hold_updates": self._params_goto_min_hold,
            "priority": self._params_priority,
            "key": f"gps_scan_{self.waypoint_index}",
        }
        action = GotoWaypointAction()
        action.start(gp)
        return action

    def _drone_snapshot(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Capture current drone telemetry as fallback snapshot."""
        drone = (context or {}).get("drone", {})
        if not isinstance(drone, dict):
            return None
        lat = drone.get("lat")
        lon = drone.get("lon")
        yaw = drone.get("yaw")
        alt = drone.get("relative_altitude") or drone.get("relative_altitude_m")
        if alt is None:
            alt = drone.get("altitude") or drone.get("altitude_m")
        if lat is None or lon is None or yaw is None or alt is None:
            return None
        try:
            lat_f = float(lat); lon_f = float(lon)
            if not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180):
                return None
            alt_f = float(alt)
            if alt_f <= 0:
                return None
            import math
            if not math.isfinite(lat_f) or not math.isfinite(lon_f):
                return None
            yaw_f = float(yaw)
            if not math.isfinite(yaw_f):
                return None
            return {"drone_lat": lat_f, "drone_lon": lon_f,
                    "drone_yaw_rad": yaw_f, "relative_altitude_m": alt_f}
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_detection_telemetry(
        det: dict[str, Any],
        context: dict[str, Any],
        drone_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Resolve capture-time telemetry for a single detection.

        Priority: 1) det.capture_telemetry  2) det.source fields
                  3) scene.capture_telemetry  4) drone_snapshot
        """
        # Priority 1: detection-bound capture telemetry
        ct = det.get("capture_telemetry")
        if ct is not None:
            if isinstance(ct, dict):
                r = GpsMultiViewLocalizeAction._parse_telem_dict(ct)
                if r is not None:
                    return r
            # capture_telemetry present but invalid → reject
            return None

        # Priority 2: detection.source fields
        src = det.get("source")
        if isinstance(src, dict):
            r = GpsMultiViewLocalizeAction._parse_telem_dict(src)
            if r is not None:
                return r

        # Priority 3: scene capture_telemetry
        scene = (context or {}).get("scene", {})
        if isinstance(scene, dict):
            sct = scene.get("capture_telemetry")
            if isinstance(sct, dict):
                r = GpsMultiViewLocalizeAction._parse_telem_dict(sct)
                if r is not None:
                    return r
            # Also check scene top-level fields
            r = GpsMultiViewLocalizeAction._parse_telem_dict(scene)
            if r is not None:
                return r

        # Priority 4: drone snapshot
        if drone_snapshot is not None:
            return dict(drone_snapshot)

        return None

    @staticmethod
    def _parse_telem_dict(d: dict[str, Any]) -> dict[str, Any] | None:
        """Try to extract drone_lat/lon/yaw/alt from a dict."""
        lat = d.get("drone_lat")
        lon = d.get("drone_lon")
        yaw = d.get("drone_yaw_rad") or d.get("yaw_rad") or d.get("yaw")
        alt = d.get("relative_altitude_m") or d.get("altitude_m") or d.get("relative_altitude") or d.get("altitude")
        if lat is None or lon is None or yaw is None or alt is None:
            return None
        try:
            lat_f = float(lat); lon_f = float(lon)
            if not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180):
                return None
            alt_f = float(alt)
            if alt_f <= 0:
                return None
            import math
            if not math.isfinite(lat_f) or not math.isfinite(lon_f) or not math.isfinite(alt_f):
                return None
            yaw_f = float(yaw)
            if not math.isfinite(yaw_f):
                return None
            return {"drone_lat": lat_f, "drone_lon": lon_f,
                    "drone_yaw_rad": yaw_f, "relative_altitude_m": alt_f}
        except (TypeError, ValueError):
            return None

    def _detections(self, context: dict[str, Any]) -> tuple[list[dict[str, Any]], int | float | None, int | float | None]:
        if self._params_detection_source == "scene":
            scene = (context or {}).get("scene", {})
            if not isinstance(scene, dict):
                return [], None, None
            dets = scene.get("detections", [])
            if not isinstance(dets, list):
                dets = []
            return ([d for d in dets if isinstance(d, dict)],
                    scene.get("image_width"), scene.get("image_height"))
        perception = (context or {}).get("perception", {})
        if not isinstance(perception, dict):
            return [], None, None
        return [perception], perception.get("image_width"), perception.get("image_height")

    @staticmethod
    def _detection_ex_ey(det: dict[str, Any], img_w: Any, img_h: Any) -> tuple[float, float] | tuple[None, None]:
        if "ex" in det and "ey" in det:
            try:
                return float(det["ex"]), float(det["ey"])
            except (TypeError, ValueError):
                return None, None
        if "cx" in det and "cy" in det and img_w is not None and img_h is not None:
            try:
                w = float(img_w)
                h = float(img_h)
                cx = float(det["cx"])
                cy = float(det["cy"])
                return (cx - w / 2.0) / (w / 2.0), (cy - h / 2.0) / (h / 2.0)
            except (TypeError, ValueError, ZeroDivisionError):
                return None, None
        return None, None

    def _inc_reject(self, reason: str) -> None:
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1

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
            "rejected_by_reason": dict(self.rejected_by_reason),
        }
        if done and self.fused_objects:
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


def _opt_int(v: Any) -> int | None:
    if v is None: return None
    try: return int(v)
    except (TypeError, ValueError): return None

def _opt_float(v: Any) -> float | None:
    if v is None: return None
    try:
        f = float(v)
        import math
        return f if math.isfinite(f) else None
    except (TypeError, ValueError): return None
