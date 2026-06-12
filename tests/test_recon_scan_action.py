from __future__ import annotations

import pytest

from missions.common.actions.recon_scan import ReconScanAction


def _params(**overrides):
    data = {
        "waypoints": [{"x": 0.0, "y": 50.0, "altitude_m": 2.2}],
        "yaw_mode": "arm_heading",
        "capture_updates_per_waypoint": 1,
        "settle_updates_per_waypoint": 0,
        "max_updates_per_waypoint": 20,
    }
    data.update(overrides)
    return data


def _at_waypoint(x: float = 0.0, y: float = 50.0, altitude_m: float = 2.2, detections=None):
    return {
        "local_position": {"x": x, "y": y, "z": -altitude_m},
        "arm_heading_yaw_rad": 0.0,
        "scene": {"detections": detections or []},
    }


def _run_single_capture(detections, **params):
    action = ReconScanAction()
    action.start(_params(**params))
    action.update(_at_waypoint())
    return action.update(_at_waypoint(detections=detections))


def test_recon_scan_update_before_start_fails() -> None:
    action = ReconScanAction()

    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_recon_scan_start_defaults_to_goto_first_waypoint() -> None:
    action = ReconScanAction()

    action.start({})

    assert action.phase == "goto"
    assert action.waypoint_index == 0


def test_recon_scan_goto_outputs_local_position() -> None:
    action = ReconScanAction()
    action.start(_params())

    result = action.update(
        {
            "local_position": {"x": -1.0, "y": 50.0, "z": -2.2},
            "arm_heading_yaw_rad": 0.0,
        }
    )

    assert result.reason == "recon_goto"
    assert result.actions[0]["action_type"] == "local_position"


def test_recon_scan_reaches_waypoint_then_enters_settle() -> None:
    action = ReconScanAction()
    action.start(_params(settle_updates_per_waypoint=1))

    result = action.update(_at_waypoint())

    assert result.reason == "recon_settle"
    assert action.phase == "settle"


def test_recon_scan_bucket_and_sign_generate_report() -> None:
    result = _run_single_capture(
        [
            {"class_name": "recon_bucket", "confidence": 0.9, "ex": 0.0, "ey": 0.0},
            {"class_name": "danger_1", "confidence": 0.8, "ex": 0.05, "ey": 0.04},
        ]
    )

    assert result.done is True
    assert result.reason == "recon_scan_done"
    assert result.detail["recon_report"]["barrels"][0]["content"] == "danger_1"


def test_recon_scan_low_report_confidence_outputs_blank() -> None:
    result = _run_single_capture(
        [
            {"class_name": "recon_bucket", "confidence": 0.9, "ex": 0.0, "ey": 0.0},
            {"class_name": "danger_1", "confidence": 0.5, "ex": 0.05, "ey": 0.04},
        ]
    )

    assert result.done is True
    assert result.detail["recon_report"]["barrels"][0]["content"] == "blank"


def test_recon_scan_bucket_without_sign_is_blank_not_failed() -> None:
    result = _run_single_capture(
        [{"class_name": "recon_bucket", "confidence": 0.9, "ex": 0.0, "ey": 0.0}]
    )

    assert result.done is True
    assert result.detail["recon_report"]["barrels"][0]["content"] == "blank"


def test_recon_scan_without_bucket_fails() -> None:
    result = _run_single_capture(
        [{"class_name": "danger_1", "confidence": 0.9, "ex": 0.0, "ey": 0.0}]
    )

    assert result.failed is True
    assert result.reason == "no_recon_buckets"


def test_recon_scan_multiple_buckets_associate_nearest_signs() -> None:
    result = _run_single_capture(
        [
            {"class_name": "recon_bucket", "confidence": 0.9, "ex": 0.0, "ey": 0.0},
            {"class_name": "recon_bucket", "confidence": 0.9, "ex": 0.8, "ey": 0.0},
            {"class_name": "danger_1", "confidence": 0.8, "ex": 0.05, "ey": 0.0},
            {"class_name": "danger_2", "confidence": 0.85, "ex": 0.75, "ey": 0.0},
        ]
    )

    contents = [item["content"] for item in result.detail["recon_report"]["barrels"]]
    assert contents == ["danger_1", "danger_2"]


def test_recon_scan_waypoint_timeout() -> None:
    action = ReconScanAction()
    action.start(_params(max_updates_per_waypoint=1))

    action.update({"local_position": {"x": 10.0, "y": 50.0, "z": -2.2}, "arm_heading_yaw_rad": 0.0})
    result = action.update({"local_position": {"x": 10.0, "y": 50.0, "z": -2.2}, "arm_heading_yaw_rad": 0.0})

    assert result.failed is True
    assert result.reason == "waypoint_timeout"


@pytest.mark.parametrize(
    "params",
    [
        {"waypoints": []},
        {"waypoints": [{"x": 0, "y": 0, "altitude_m": 0}]},
        {"min_bucket_confidence": 1.1},
        {"capture_updates_per_waypoint": 0},
        {"cluster_radius_m": 0},
    ],
)
def test_recon_scan_rejects_invalid_params(params) -> None:
    action = ReconScanAction()

    with pytest.raises(ValueError):
        action.start(_params(**params))
