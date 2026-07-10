"""GPS-first target lock action.

Matches YOLO detections to a GPS target by projecting each detection
to GPS using capture-time telemetry, then comparing via gps_enu_deltas.
"""

from __future__ import annotations

import math
from typing import Any

from app.field_reference import gps_enu_deltas

from .base import ActionModule
from .result import ActionResult
from .gps_target_projection import GpsProjectionCamera, GpsTargetProjector


class GpsTargetLockAction(ActionModule):
    """Lock onto a GPS target using GPS-correlated detection matching.

    For each detection frame, projects detections to GPS using capture-time
    telemetry, then finds the closest match to the selected target GPS.
    """

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        target = data.get("target")
        if not isinstance(target, dict):
            raise ValueError("target must be a dict")
        self.target_lat = float(target["lat"])
        self.target_lon = float(target["lon"])
        self.target_class = str(target.get("class_name", ""))
        self.target_id = str(target.get("id", target.get("target_id", "")))

        self.max_match_distance_m = float(data.get("max_match_distance_m", 1.2))
        self.max_updates = int(data.get("max_updates", 40))
        self.min_confidence = float(data.get("min_confidence", 0.35))
        class_names = data.get("class_names")
        self.class_names = {str(n) for n in class_names} if class_names else None

        cam_raw = dict(data.get("camera") or {})
        cam_raw.setdefault("fov_x_deg", 51.3)
        cam_raw.setdefault("fov_y_deg", 39.6)
        self.camera = GpsProjectionCamera(**cam_raw)
        self.projector = GpsTargetProjector(self.camera)

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        self.update_count = 0
        self.locked_track_id: int | None = None
        self.best_distance_m: float | None = None
        self.matched_detection_gps: dict[str, Any] | None = None

        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")
        self.update_count += 1
        if self.update_count > self.max_updates:
            return ActionResult(failed=True, reason="gps_target_lock_timeout",
                                detail={"update_count": self.update_count})

        data = context or {}
        detections, image_width, image_height = self._detections(data)
        drone_snapshot = self._drone_snapshot(data)

        best_dist = float("inf")
        best_track_id = None
        best_gps = None

        for det in detections:
            class_name = str(det.get("class_name") or "")
            if self.class_names and class_name not in self.class_names:
                continue
            conf = det.get("confidence")
            if conf is not None:
                try:
                    if float(conf) < self.min_confidence:
                        continue
                except (TypeError, ValueError):
                    continue

            telem = self._resolve_telemetry(det, data, drone_snapshot)
            if telem is None:
                continue

            ex, ey = self._detection_ex_ey(det, image_width, image_height)
            if ex is None:
                continue

            try:
                est = self.projector.project(
                    drone_lat=telem["drone_lat"],
                    drone_lon=telem["drone_lon"],
                    drone_yaw_rad=telem["drone_yaw_rad"],
                    relative_altitude_m=telem["relative_altitude_m"],
                    ex=ex, ey=ey,
                    class_name=class_name,
                    confidence=conf,
                    track_id=_opt_int(det.get("track_id")),
                )
            except Exception:
                continue

            d_north, d_east = gps_enu_deltas(
                self.target_lat, self.target_lon, est.lat, est.lon
            )
            dist = math.hypot(d_north, d_east)
            if dist < best_dist and dist <= self.max_match_distance_m:
                best_dist = dist
                best_track_id = est.track_id
                best_gps = {"lat": est.lat, "lon": est.lon, "distance_m": dist}

        if best_track_id is not None and best_track_id != self.locked_track_id:
            self.locked_track_id = best_track_id
            self.best_distance_m = best_dist
            self.matched_detection_gps = best_gps
            return ActionResult(
                done=True, reason="gps_target_locked",
                actions=[{"action_type": "yolo_lock_target", "params": {"track_id": best_track_id}}],
                detail={
                    "locked_track_id": best_track_id,
                    "best_distance_m": best_dist,
                    "matched_detection_gps": best_gps,
                    "target_gps": {"lat": self.target_lat, "lon": self.target_lon},
                },
            )

        if self.update_count >= self.max_updates:
            return ActionResult(
                failed=True, reason="gps_target_lock_timeout",
                detail={"update_count": self.update_count},
            )

        return ActionResult(reason="gps_target_lock_searching",
                           detail={"update_count": self.update_count, "best_distance_m": best_dist if best_dist != float("inf") else None})

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.target_lat = 0.0; self.target_lon = 0.0
        self.update_count = 0
        self.locked_track_id = None
        self.best_distance_m = None
        self.started = False; self.stopped = False

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _drone_snapshot(context: dict[str, Any]) -> dict[str, Any] | None:
        drone = context.get("drone", {})
        if not isinstance(drone, dict): return None
        lat = drone.get("lat"); lon = drone.get("lon"); yaw = drone.get("yaw")
        if lat is None or lon is None or yaw is None: return None
        alt = drone.get("relative_altitude")
        if alt is None: alt = drone.get("relative_altitude_m")
        if alt is None: alt = drone.get("altitude")
        if alt is None: alt = drone.get("altitude_m")
        if alt is None: return None
        try:
            lat_f = float(lat); lon_f = float(lon)
            if not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180): return None
            if not math.isfinite(lat_f) or not math.isfinite(lon_f): return None
            yaw_f = float(yaw)
            if not math.isfinite(yaw_f): return None
            alt_f = float(alt)
            if not math.isfinite(alt_f) or alt_f <= 0.0: return None
            return {"drone_lat": lat_f, "drone_lon": lon_f,
                    "drone_yaw_rad": yaw_f, "relative_altitude_m": alt_f}
        except (TypeError, ValueError): return None

    @staticmethod
    def _resolve_telemetry(det: dict[str, Any], context: dict[str, Any],
                           drone_snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        ct = det.get("capture_telemetry")
        if ct is not None:
            if isinstance(ct, dict):
                r = GpsTargetLockAction._parse_telem(ct)
                if r is not None: return r
            return None
        src = det.get("source")
        if isinstance(src, dict):
            r = GpsTargetLockAction._parse_telem(src)
            if r is not None: return r
        scene = context.get("scene", {})
        if isinstance(scene, dict):
            sct = scene.get("capture_telemetry")
            if isinstance(sct, dict):
                r = GpsTargetLockAction._parse_telem(sct)
                if r is not None: return r
            r = GpsTargetLockAction._parse_telem(scene)
            if r is not None: return r
        if drone_snapshot is not None:
            return dict(drone_snapshot)
        return None

    @staticmethod
    def _parse_telem(d: dict[str, Any]) -> dict[str, Any] | None:
        lat = d.get("drone_lat"); lon = d.get("drone_lon")
        yaw = d.get("drone_yaw_rad")
        if yaw is None: yaw = d.get("yaw_rad")
        if yaw is None: yaw = d.get("yaw")
        alt = d.get("relative_altitude_m")
        if alt is None: alt = d.get("altitude_m")
        if alt is None: alt = d.get("relative_altitude")
        if alt is None: alt = d.get("altitude")
        if lat is None or lon is None or yaw is None or alt is None: return None
        try:
            lat_f = float(lat); lon_f = float(lon)
            if not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180): return None
            yaw_f = float(yaw); alt_f = float(alt)
            if not math.isfinite(lat_f) or not math.isfinite(lon_f): return None
            if not math.isfinite(yaw_f): return None
            if not math.isfinite(alt_f) or alt_f <= 0.0: return None
            return {"drone_lat": lat_f, "drone_lon": lon_f,
                    "drone_yaw_rad": yaw_f, "relative_altitude_m": alt_f}
        except (TypeError, ValueError): return None

    @staticmethod
    def _detection_ex_ey(det: dict[str, Any], img_w, img_h) -> tuple[float, float] | tuple[None, None]:
        if "ex" in det and "ey" in det:
            try: return float(det["ex"]), float(det["ey"])
            except (TypeError, ValueError): return None, None
        if "cx" in det and "cy" in det and img_w is not None and img_h is not None:
            try:
                w = float(img_w); h = float(img_h)
                return (float(det["cx"]) - w/2) / (w/2), (float(det["cy"]) - h/2) / (h/2)
            except: return None, None
        return None, None

    def _detections(self, context: dict[str, Any]) -> tuple:
        if self.detection_source == "scene":
            scene = context.get("scene", {})
            if not isinstance(scene, dict): return [], None, None
            dets = scene.get("detections", [])
            return ([d for d in dets if isinstance(d, dict)] if isinstance(dets, list) else [],
                    scene.get("image_width"), scene.get("image_height"))
        perception = context.get("perception", {})
        if not isinstance(perception, dict): return [], None, None
        return [perception], perception.get("image_width"), perception.get("image_height")


def _opt_int(v): 
    if v is None: return None
    try: return int(v)
    except: return None
