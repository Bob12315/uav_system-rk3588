"""Target lock action supporting GPS association or image-centre selection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from field.models import gps_enu_deltas
from guidance.target_projection import GpsProjectionCamera, GpsTargetProjector

from .base import ActionModule
from .result import ActionResult


_NEAREST_GPS = "nearest_gps"
_NEAREST_IMAGE_CENTER = "nearest_image_center"
_SELECTION_MODES = {_NEAREST_GPS, _NEAREST_IMAGE_CENTER}


@dataclass(frozen=True, slots=True)
class _Candidate:
    track_id: int | None
    center_distance_norm: float
    gps_distance_m: float | None = None
    gps: dict[str, float] | None = None


class GpsTargetLockAction(ActionModule):
    """Select a detection and optionally wait for YOLO lock confirmation.

    ``nearest_gps`` projects detections using capture-time telemetry and applies
    the configured GPS radius. ``nearest_image_center`` skips GPS projection and
    selects the eligible detection nearest the camera image centre.
    """

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self._configure_target(data.get("target"))

        self.selection_mode = str(
            data.get("selection_mode", _NEAREST_GPS)
        ).strip().lower()
        if self.selection_mode not in _SELECTION_MODES:
            raise ValueError(
                "selection_mode must be 'nearest_gps' or 'nearest_image_center'"
            )

        self.max_match_distance_m = float(data.get("max_match_distance_m", 1.2))
        self.min_match_margin_m = float(data.get("min_match_margin_m", 0.0))
        if self.min_match_margin_m < 0.0:
            raise ValueError("min_match_margin_m must be non-negative")

        self.max_updates = int(data.get("max_updates", 40))
        self.min_confidence = float(data.get("min_confidence", 0.35))
        class_names = data.get("class_names")
        self.class_names = {str(name) for name in class_names} if class_names else None

        camera_params = dict(data.get("camera") or {})
        camera_params.setdefault("fov_x_deg", 51.3)
        camera_params.setdefault("fov_y_deg", 39.6)
        self.camera = GpsProjectionCamera(**camera_params)
        self.projector = GpsTargetProjector(self.camera)

        self.detection_source = str(
            data.get("detection_source", "scene")
        ).strip().lower()
        self.require_track_id = bool(data.get("require_track_id", True))
        self.require_class_match = bool(data.get("require_class_match", True))
        self.require_lock_confirmation = bool(
            data.get("require_lock_confirmation", True)
        )
        self.max_target_age_s = float(data.get("max_target_age_s", 0.5))
        self._validate_lock_configuration()

        self.update_count = 0
        self.locked_track_id = None
        self.lock_requested_track_id = None
        self.best_distance_m = None
        self.best_center_distance_norm = None
        self.matched_detection_gps = None
        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")

        self.update_count += 1
        if self.update_count > self.max_updates:
            return self._timeout_result()

        data = context or {}
        if self.lock_requested_track_id is not None:
            return self._update_lock_confirmation(data)

        candidates = self._collect_candidates(data)
        ambiguity = self._gps_ambiguity_result(candidates)
        if ambiguity is not None:
            return ambiguity
        if not candidates:
            return self._search_result()

        candidate = candidates[0]
        self._remember_candidate(candidate)
        return self._lock_candidate(candidate)

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.target_lat = 0.0
        self.target_lon = 0.0
        self.target_class = ""
        self.target_id = ""
        self.selection_mode = _NEAREST_GPS
        self.max_match_distance_m = 1.2
        self.min_match_margin_m = 0.0
        self.max_updates = 40
        self.min_confidence = 0.35
        self.class_names: set[str] | None = None
        self.detection_source = "scene"
        self.require_track_id = True
        self.require_class_match = True
        self.require_lock_confirmation = True
        self.max_target_age_s = 0.5
        self.camera = GpsProjectionCamera()
        self.projector = GpsTargetProjector(self.camera)

        self.update_count = 0
        self.locked_track_id: int | None = None
        self.lock_requested_track_id: int | None = None
        self.best_distance_m: float | None = None
        self.best_center_distance_norm: float | None = None
        self.matched_detection_gps: dict[str, float] | None = None
        self.started = False
        self.stopped = False

    def _configure_target(self, target: Any) -> None:
        if not isinstance(target, dict):
            raise ValueError("target must be a dict")
        if target.get("valid") is False:
            raise ValueError("target must be valid")

        self.target_lat = float(target["lat"])
        self.target_lon = float(target["lon"])
        if not math.isfinite(self.target_lat) or not math.isfinite(self.target_lon):
            raise ValueError("target lat/lon must be finite")
        self.target_class = str(target.get("class_name", ""))
        self.target_id = str(target.get("id", target.get("target_id", "")))

    def _validate_lock_configuration(self) -> None:
        if self.max_target_age_s <= 0.0:
            raise ValueError("max_target_age_s must be positive")
        if self.require_lock_confirmation and not self.require_track_id:
            raise ValueError("lock confirmation requires require_track_id=true")
        if self.require_lock_confirmation and self.max_updates < 2:
            raise ValueError(
                "max_updates must be at least 2 when lock confirmation is required"
            )

    def _collect_candidates(self, context: dict[str, Any]) -> list[_Candidate]:
        detections, image_width, image_height = self._detections(context)
        drone_snapshot = (
            self._drone_snapshot(context)
            if self.selection_mode == _NEAREST_GPS
            else None
        )
        candidates: list[_Candidate] = []

        for detection in detections:
            if not self._eligible_detection(detection):
                continue
            error = self._detection_ex_ey(detection, image_width, image_height)
            if error is None:
                continue
            ex, ey = error
            center_distance = self._center_distance_norm(
                detection, image_width, image_height, ex, ey
            )
            candidate = self._build_candidate(
                detection,
                context,
                drone_snapshot,
                ex,
                ey,
                center_distance,
            )
            if candidate is None:
                continue
            if self.require_track_id and candidate.track_id is None:
                continue
            candidates.append(candidate)

        if self.selection_mode == _NEAREST_IMAGE_CENTER:
            candidates.sort(key=lambda item: item.center_distance_norm)
        else:
            candidates.sort(
                key=lambda item: (
                    _required_distance(item),
                    item.center_distance_norm,
                )
            )
        return candidates

    def _eligible_detection(self, detection: dict[str, Any]) -> bool:
        class_name = str(detection.get("class_name") or "")
        if self.class_names and class_name not in self.class_names:
            return False
        if self.require_class_match and self.target_class and class_name != self.target_class:
            return False

        confidence = detection.get("confidence")
        if confidence is None:
            return True
        parsed_confidence = self._optional_float(confidence)
        return parsed_confidence is not None and parsed_confidence >= self.min_confidence

    def _build_candidate(
        self,
        detection: dict[str, Any],
        context: dict[str, Any],
        drone_snapshot: dict[str, float] | None,
        ex: float,
        ey: float,
        center_distance: float,
    ) -> _Candidate | None:
        track_id = _optional_int(detection.get("track_id"))
        if self.selection_mode == _NEAREST_IMAGE_CENTER:
            return _Candidate(
                track_id=track_id,
                center_distance_norm=center_distance,
            )

        telemetry = self._resolve_telemetry(detection, context, drone_snapshot)
        if telemetry is None:
            return None
        try:
            estimate = self.projector.project(
                drone_lat=telemetry["drone_lat"],
                drone_lon=telemetry["drone_lon"],
                drone_yaw_rad=telemetry["drone_yaw_rad"],
                relative_altitude_m=telemetry["relative_altitude_m"],
                ex=ex,
                ey=ey,
                class_name=str(detection.get("class_name") or ""),
                confidence=detection.get("confidence"),
                track_id=track_id,
            )
        except (TypeError, ValueError):
            return None

        north_m, east_m = gps_enu_deltas(
            self.target_lat,
            self.target_lon,
            estimate.lat,
            estimate.lon,
        )
        distance_m = math.hypot(north_m, east_m)
        if distance_m > self.max_match_distance_m:
            return None
        return _Candidate(
            track_id=estimate.track_id,
            center_distance_norm=center_distance,
            gps_distance_m=distance_m,
            gps={
                "lat": estimate.lat,
                "lon": estimate.lon,
                "distance_m": distance_m,
            },
        )

    def _gps_ambiguity_result(
        self, candidates: list[_Candidate]
    ) -> ActionResult | None:
        if self.selection_mode != _NEAREST_GPS or len(candidates) < 2:
            return None

        best_distance = _required_distance(candidates[0])
        second_distance = _required_distance(candidates[1])
        if second_distance - best_distance >= self.min_match_margin_m:
            return None

        detail = {
            "update_count": self.update_count,
            "best_distance_m": best_distance,
            "second_best_distance_m": second_distance,
            "required_match_margin_m": self.min_match_margin_m,
        }
        if self.update_count >= self.max_updates:
            return self._timeout_result(detail)
        return ActionResult(reason="gps_target_lock_ambiguous", detail=detail)

    def _remember_candidate(self, candidate: _Candidate) -> None:
        self.locked_track_id = candidate.track_id
        self.best_distance_m = candidate.gps_distance_m
        self.best_center_distance_norm = candidate.center_distance_norm
        self.matched_detection_gps = candidate.gps

    def _lock_candidate(self, candidate: _Candidate) -> ActionResult:
        detail = self._lock_detail()
        if candidate.track_id is None:
            detail.pop("locked_track_id")
            detail["matched_without_track_id"] = True
            return ActionResult(
                done=True,
                reason="gps_target_locked",
                output={},
                detail=detail,
            )

        effect = {
            "action_type": "yolo_lock_target",
            "params": {"track_id": candidate.track_id},
        }
        if self.require_lock_confirmation:
            self.lock_requested_track_id = candidate.track_id
            return ActionResult(
                reason="gps_target_lock_requested",
                effects=ActionResult.typed([effect]),
                detail=detail,
            )
        return ActionResult(
            done=True,
            reason="gps_target_locked",
            effects=ActionResult.typed([effect]),
            output={"locked_track_id": candidate.track_id},
            detail=detail,
        )

    def _update_lock_confirmation(self, context: dict[str, Any]) -> ActionResult:
        confirmation_error = self._lock_confirmation_error(context)
        if confirmation_error is None:
            return ActionResult(
                done=True,
                reason="gps_target_locked",
                output={"locked_track_id": self.lock_requested_track_id},
                detail=self._lock_detail(),
            )

        detail = {**self._lock_detail(), "lock_error": confirmation_error}
        if self.update_count >= self.max_updates:
            return self._timeout_result(detail)
        return ActionResult(reason="gps_target_lock_waiting", detail=detail)

    def _search_result(self) -> ActionResult:
        detail = {
            "update_count": self.update_count,
            "best_distance_m": None,
        }
        if self.update_count >= self.max_updates:
            return self._timeout_result(detail)
        return ActionResult(reason="gps_target_lock_searching", detail=detail)

    def _timeout_result(self, detail: dict[str, Any] | None = None) -> ActionResult:
        return ActionResult(
            failed=True,
            reason="gps_target_lock_timeout",
            detail=detail or {"update_count": self.update_count},
        )

    def _lock_detail(self) -> dict[str, Any]:
        return {
            "locked_track_id": self.locked_track_id,
            "best_distance_m": self.best_distance_m,
            "best_center_distance_norm": self.best_center_distance_norm,
            "selection_mode": self.selection_mode,
            "matched_detection_gps": self.matched_detection_gps,
            "target_gps": {"lat": self.target_lat, "lon": self.target_lon},
            "target_class": self.target_class,
            "update_count": self.update_count,
        }

    def _lock_confirmation_error(self, context: dict[str, Any]) -> str | None:
        perception = context.get("perception")
        if not isinstance(perception, dict):
            return "perception_unavailable"
        if not bool(perception.get("target_valid", False)):
            return "target_not_valid"
        if str(perception.get("tracking_state", "")).lower() != "locked":
            return "target_not_locked"
        if _optional_int(perception.get("track_id")) != self.lock_requested_track_id:
            return "target_track_id_mismatch"

        perception_class = str(perception.get("class_name") or "")
        if (
            self.require_class_match
            and self.target_class
            and perception_class
            and perception_class != self.target_class
        ):
            return "target_class_mismatch"

        age_s = self._optional_float(perception.get("target_age_s"))
        if age_s is not None and age_s > self.max_target_age_s:
            return "target_stale"
        return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _drone_snapshot(context: dict[str, Any]) -> dict[str, float] | None:
        drone = context.get("drone")
        if not isinstance(drone, dict):
            return None
        altitude = drone.get("relative_altitude")
        if altitude is None:
            altitude = drone.get("relative_altitude_m")
        if altitude is None:
            altitude = drone.get("altitude")
        if altitude is None:
            altitude = drone.get("altitude_m")
        return GpsTargetLockAction._parse_telemetry({
            "drone_lat": drone.get("lat"),
            "drone_lon": drone.get("lon"),
            "drone_yaw_rad": drone.get("yaw"),
            "relative_altitude_m": altitude,
        })

    @staticmethod
    def _resolve_telemetry(
        detection: dict[str, Any],
        context: dict[str, Any],
        drone_snapshot: dict[str, float] | None,
    ) -> dict[str, float] | None:
        capture_telemetry = detection.get("capture_telemetry")
        if capture_telemetry is not None:
            return GpsTargetLockAction._parse_telemetry(capture_telemetry)

        source = detection.get("source")
        if isinstance(source, dict):
            parsed = GpsTargetLockAction._parse_telemetry(source)
            if parsed is not None:
                return parsed

        scene = context.get("scene")
        if isinstance(scene, dict):
            scene_capture = scene.get("capture_telemetry")
            if isinstance(scene_capture, dict):
                parsed = GpsTargetLockAction._parse_telemetry(scene_capture)
                if parsed is not None:
                    return parsed
            parsed = GpsTargetLockAction._parse_telemetry(scene)
            if parsed is not None:
                return parsed

        return dict(drone_snapshot) if drone_snapshot is not None else None

    @staticmethod
    def _parse_telemetry(value: Any) -> dict[str, float] | None:
        if not isinstance(value, dict):
            return None

        lat = value.get("drone_lat", value.get("lat"))
        lon = value.get("drone_lon", value.get("lon"))
        yaw = value.get("drone_yaw_rad")
        if yaw is None:
            yaw = value.get("yaw_rad", value.get("yaw"))
        altitude = value.get("relative_altitude_m")
        if altitude is None:
            altitude = value.get("altitude_m")
        if altitude is None:
            altitude = value.get("relative_altitude")
        if altitude is None:
            altitude = value.get("altitude")
        if lat is None or lon is None or yaw is None or altitude is None:
            return None

        try:
            parsed = {
                "drone_lat": float(lat),
                "drone_lon": float(lon),
                "drone_yaw_rad": float(yaw),
                "relative_altitude_m": float(altitude),
            }
        except (TypeError, ValueError):
            return None

        if not -90.0 <= parsed["drone_lat"] <= 90.0:
            return None
        if not -180.0 <= parsed["drone_lon"] <= 180.0:
            return None
        if not all(math.isfinite(number) for number in parsed.values()):
            return None
        if parsed["relative_altitude_m"] <= 0.0:
            return None
        return parsed

    @staticmethod
    def _detection_ex_ey(
        detection: dict[str, Any],
        image_width: Any,
        image_height: Any,
    ) -> tuple[float, float] | None:
        try:
            if "ex" in detection and "ey" in detection:
                ex = float(detection["ex"])
                ey = float(detection["ey"])
            elif (
                "cx" in detection
                and "cy" in detection
                and image_width is not None
                and image_height is not None
            ):
                width = float(image_width)
                height = float(image_height)
                if width <= 0.0 or height <= 0.0:
                    return None
                ex = (float(detection["cx"]) - width / 2.0) / (width / 2.0)
                ey = (float(detection["cy"]) - height / 2.0) / (height / 2.0)
            else:
                return None
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        if not math.isfinite(ex) or not math.isfinite(ey):
            return None
        return ex, ey

    @staticmethod
    def _center_distance_norm(
        detection: dict[str, Any],
        image_width: Any,
        image_height: Any,
        ex: float,
        ey: float,
    ) -> float:
        """Return pixel distance from image centre, normalised by half diagonal."""
        try:
            width = float(image_width)
            height = float(image_height)
            if width <= 0.0 or height <= 0.0:
                raise ValueError
            if "cx" in detection and "cy" in detection:
                dx_px = float(detection["cx"]) - width / 2.0
                dy_px = float(detection["cy"]) - height / 2.0
            else:
                dx_px = ex * width / 2.0
                dy_px = ey * height / 2.0
            half_diagonal = math.hypot(width / 2.0, height / 2.0)
            return math.hypot(dx_px, dy_px) / half_diagonal
        except (TypeError, ValueError):
            return math.hypot(ex, ey)

    def _detections(
        self, context: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], Any, Any]:
        source = context.get(self.detection_source)
        if not isinstance(source, dict):
            return [], None, None
        if self.detection_source == "scene":
            raw_detections = source.get("detections")
            detections = (
                [item for item in raw_detections if isinstance(item, dict)]
                if isinstance(raw_detections, list)
                else []
            )
        else:
            detections = [source]
        return detections, source.get("image_width"), source.get("image_height")


def _required_distance(candidate: _Candidate) -> float:
    if candidate.gps_distance_m is None:
        raise ValueError("GPS candidate must contain gps_distance_m")
    return candidate.gps_distance_m


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
