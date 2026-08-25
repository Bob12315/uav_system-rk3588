from __future__ import annotations

from missions.common.actions.gps_capture_view import GpsCaptureViewAction


def test_gps_capture_view_projects_without_effects() -> None:
    action = GpsCaptureViewAction()
    action.start({"class_names": ["bucket"], "min_confidence": 0.3,
                  "source_waypoint": "DROP_SCAN_1"})
    result = action.update({
        "drone": {"lat": 34.0, "lon": 108.0, "yaw": 0.0, "relative_altitude": 4.0},
        "scene": {"image_width": 640, "image_height": 480, "detections": [
            {"class_name": "bucket", "confidence": 0.9, "cx": 320, "cy": 240,
             "track_id": 3, "frame_id": 7},
        ]},
    })
    assert result.done and not result.failed
    assert result.actions == []
    assert result.detail["count"] == 1
    assert result.detail["raw_estimates"][0]["source_waypoint"] == "DROP_SCAN_1"
