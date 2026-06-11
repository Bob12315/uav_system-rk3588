from __future__ import annotations

import math

import pytest

from missions.common.actions.single_view_localize import SingleViewLocalizeAction


def test_single_view_localize_center_detection_returns_drone_xy() -> None:
    action = SingleViewLocalizeAction()
    action.start(
        {
            "detection_source": "scene",
            "class_names": ["bucket"],
            "min_confidence": 0.35,
            "camera": {
                "horizontal_fov_deg": 113.0,
                "vertical_fov_deg": 93.0,
                "image_x_sign": 1,
                "image_y_sign": -1,
                "model": "pinhole",
            },
        }
    )

    result = action.update(
        {
            "scene": {
                "detections": [
                    {
                        "ex": 0.0,
                        "ey": 0.0,
                        "class_name": "bucket",
                        "confidence": 0.9,
                    }
                ],
            },
            "drone": {
                "local_x": 1.0,
                "local_y": 2.0,
                "local_z": -5.0,
                "yaw": 0.0,
            },
        }
    )

    assert result.done is True
    assert result.failed is False
    assert result.reason == "single_view_localized"
    assert result.actions == []
    assert result.detail["count"] == 1
    estimate = result.detail["raw_estimates"][0]
    assert estimate["local_x"] == pytest.approx(1.0)
    assert estimate["local_y"] == pytest.approx(2.0)
    assert result.detail["localized_objects"] == result.detail["raw_estimates"]
    summary = result.detail["summary"]
    assert summary["detections_count"] == 1
    assert summary["localized_count"] == 1
    assert summary["yaw_deg"] == pytest.approx(0.0)
    assert summary["first_target"]["distance_from_drone_m"] == pytest.approx(0.0)
    assert summary["first_target"]["local_x"] == pytest.approx(1.0)
    assert summary["first_target"]["local_y"] == pytest.approx(2.0)
    assert summary["first_target"]["body_x_m"] == pytest.approx(0.0)
    assert summary["first_target"]["body_y_m"] == pytest.approx(0.0)
    assert summary["first_target"]["local_dx_m"] == pytest.approx(0.0)
    assert summary["first_target"]["local_dy_m"] == pytest.approx(0.0)


def test_single_view_localize_summary_yaw_degrees() -> None:
    action = SingleViewLocalizeAction()
    action.start()

    result = action.update(
        {
            "scene": {
                "detections": [
                    {
                        "ex": 0.0,
                        "ey": 0.0,
                        "class_name": "bucket",
                        "confidence": 0.9,
                    }
                ],
            },
            "drone": {
                "local_x": 1.0,
                "local_y": 2.0,
                "local_z": -5.0,
                "yaw": math.pi / 2.0,
            },
        }
    )

    assert result.done is True
    assert result.detail["summary"]["yaw_rad"] == pytest.approx(math.pi / 2.0)
    assert result.detail["summary"]["yaw_deg"] == pytest.approx(90.0)


def test_single_view_localize_non_center_detection_with_calibrated_camera() -> None:
    action = SingleViewLocalizeAction()
    action.start(
        {
            "detection_source": "scene",
            "class_names": ["bucket"],
            "min_confidence": 0.35,
            "camera": {
                "horizontal_fov_deg": 113.0,
                "vertical_fov_deg": 93.0,
                "image_x_sign": 1,
                "image_y_sign": -1,
                "model": "pinhole",
            },
        }
    )

    result = action.update(
        {
            "scene": {
                "detections": [
                    {
                        "ex": 0.43,
                        "ey": 0.38,
                        "class_name": "bucket",
                        "confidence": 0.9,
                    }
                ],
            },
            "drone": {
                "local_x": 1.0,
                "local_y": 30.0,
                "local_z": -3.5,
                "yaw": 0.0,
            },
        }
    )

    estimate = result.detail["raw_estimates"][0]
    assert result.done is True
    assert estimate["local_x"] == pytest.approx(-0.115, abs=0.02)
    assert estimate["local_y"] == pytest.approx(31.58, abs=0.02)
    assert estimate["projection"]["fov_x_deg"] == pytest.approx(113.0)
    assert estimate["projection"]["fov_y_deg"] == pytest.approx(93.0)
    assert estimate["projection"]["image_x_sign"] == pytest.approx(1.0)
    assert estimate["projection"]["image_y_sign"] == pytest.approx(-1.0)


def test_single_view_localize_no_detections_is_done_not_failed() -> None:
    action = SingleViewLocalizeAction()
    action.start()

    result = action.update(
        {
            "scene": {"detections": []},
            "drone": {
                "local_x": 1.0,
                "local_y": 2.0,
                "local_z": -5.0,
                "yaw": 0.0,
            },
        }
    )

    assert result.done is True
    assert result.failed is False
    assert result.reason == "no_detections"
    assert result.detail["count"] == 0
    assert result.detail["summary"]["first_target"] is None


def test_single_view_localize_missing_drone_context_fails() -> None:
    action = SingleViewLocalizeAction()
    action.start()

    result = action.update(
        {
            "scene": {
                "detections": [
                    {
                        "ex": 0.0,
                        "ey": 0.0,
                        "class_name": "bucket",
                        "confidence": 0.9,
                    }
                ],
            },
        }
    )

    assert result.failed is True
    assert result.reason == "missing_drone_context"
