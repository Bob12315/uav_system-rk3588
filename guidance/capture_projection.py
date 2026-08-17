"""Pure extraction of image detections and capture-time vehicle pose."""
from __future__ import annotations

import math
from typing import Any


def parse_capture_telemetry(data: dict[str, Any]) -> dict[str, float] | None:
    lat = data.get("drone_lat", data.get("lat"))
    lon = data.get("drone_lon", data.get("lon"))
    yaw = data.get("drone_yaw_rad", data.get("yaw_rad", data.get("yaw")))
    altitude = data.get("relative_altitude_m", data.get("relative_altitude",
        data.get("altitude_m", data.get("altitude"))))
    try:
        values = tuple(float(value) for value in (lat, lon, yaw, altitude))
    except (TypeError, ValueError):
        return None
    lat_f, lon_f, yaw_f, altitude_f = values
    if not all(math.isfinite(value) for value in values):
        return None
    if not -90.0 <= lat_f <= 90.0 or not -180.0 <= lon_f <= 180.0 or altitude_f <= 0.0:
        return None
    return {"drone_lat": lat_f, "drone_lon": lon_f,
            "drone_yaw_rad": yaw_f, "relative_altitude_m": altitude_f}


def detection_pose(detection: dict[str, Any], context: dict[str, Any]) -> dict[str, float] | None:
    capture = detection.get("capture_telemetry")
    if isinstance(capture, dict):
        return parse_capture_telemetry(capture)
    source = detection.get("source")
    if isinstance(source, dict):
        pose = parse_capture_telemetry(source)
        if pose is not None:
            return pose
    scene = context.get("scene")
    if isinstance(scene, dict):
        capture = scene.get("capture_telemetry")
        if isinstance(capture, dict):
            pose = parse_capture_telemetry(capture)
            if pose is not None:
                return pose
        pose = parse_capture_telemetry(scene)
        if pose is not None:
            return pose
    drone = context.get("drone")
    return parse_capture_telemetry(drone) if isinstance(drone, dict) else None


def normalized_detection_error(
    detection: dict[str, Any], image_width: Any, image_height: Any,
) -> tuple[float, float] | None:
    try:
        if "ex" in detection and "ey" in detection:
            ex, ey = float(detection["ex"]), float(detection["ey"])
        else:
            width, height = float(image_width), float(image_height)
            ex = (float(detection["cx"]) - width / 2.0) / (width / 2.0)
            ey = (float(detection["cy"]) - height / 2.0) / (height / 2.0)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return (ex, ey) if math.isfinite(ex) and math.isfinite(ey) else None


def scene_detections(context: dict[str, Any]) -> tuple[list[dict[str, Any]], Any, Any]:
    scene = context.get("scene")
    if not isinstance(scene, dict):
        return [], None, None
    detections = scene.get("detections")
    return ([item for item in detections if isinstance(item, dict)]
            if isinstance(detections, list) else [],
            scene.get("image_width"), scene.get("image_height"))
