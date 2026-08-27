from __future__ import annotations

from missions.common.actions.gps_capture_view import GpsCaptureViewAction
from missions.common.actions.gps_fuse_views import _output_item
from guidance.gps_derived_enu_fusion import GpsLocalizedObject


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


def test_gps_fuse_output_uses_json_arrays_for_source_metadata() -> None:
    output = _output_item(GpsLocalizedObject(
        id=1, lat=34.0, lon=108.0, east_m=1.0, north_m=2.0,
        sample_count=2, raw_count=2, class_name="bucket", confidence=0.9,
        cluster_spread_m=0.1, source_waypoints=("VIEW_1", "VIEW_2"),
        source_frames=(101, 102),
    ))

    assert output["source_waypoints"] == ["VIEW_1", "VIEW_2"]
    assert output["source_frames"] == [101, 102]
