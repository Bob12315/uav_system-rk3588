from __future__ import annotations

import json
import math

import pytest

from missions.common.actions.target_localization import (
    CameraProjectionConfig,
    TargetLocalization,
)


def test_camera_projection_config_defaults_are_valid() -> None:
    config = CameraProjectionConfig()

    assert config.fov_x_deg == 75.0
    assert config.fov_y_deg == 75.0
    assert config.image_x_sign == 1.0
    assert config.image_y_sign == 1.0
    assert config.min_altitude_m == 0.1


def test_camera_projection_config_rejects_invalid_fov() -> None:
    with pytest.raises(ValueError):
        CameraProjectionConfig(fov_x_deg=0.0)
    with pytest.raises(ValueError):
        CameraProjectionConfig(fov_x_deg=180.0)
    with pytest.raises(ValueError):
        CameraProjectionConfig(fov_y_deg=-1.0)
    with pytest.raises(ValueError):
        CameraProjectionConfig(fov_y_deg=181.0)


def test_camera_projection_config_rejects_invalid_signs() -> None:
    with pytest.raises(ValueError):
        CameraProjectionConfig(image_x_sign=0.0)
    with pytest.raises(ValueError):
        CameraProjectionConfig(image_y_sign=2.0)


def test_camera_projection_config_rejects_invalid_min_altitude() -> None:
    with pytest.raises(ValueError):
        CameraProjectionConfig(min_altitude_m=0.0)


def test_center_detection_projects_under_drone() -> None:
    localizer = TargetLocalization()
    detection = {"ex": 0.0, "ey": 0.0, "confidence": 0.9}
    drone = {"local_x": 10.0, "local_y": 20.0, "local_z": -5.0, "yaw": 0.0}

    estimate = localizer.localize_detection(detection, drone)

    assert estimate["x"] == pytest.approx(10.0)
    assert estimate["y"] == pytest.approx(20.0)
    assert estimate["local_x"] == pytest.approx(10.0)
    assert estimate["local_y"] == pytest.approx(20.0)
    assert estimate["z"] == 0.0
    assert estimate["local_z"] == 0.0
    assert estimate["projection"]["altitude_m"] == pytest.approx(5.0)
    assert estimate["projection"]["model"] == "flat_ground_fov_downward_camera"


def test_relative_altitude_has_priority_over_local_z() -> None:
    localizer = TargetLocalization()
    drone = {
        "local_x": 0.0,
        "local_y": 0.0,
        "local_z": -10.0,
        "relative_altitude": 5.0,
        "yaw": 0.0,
    }

    estimate = localizer.localize_detection({"ex": 0.0, "ey": 0.0}, drone)

    assert estimate["projection"]["altitude_m"] == pytest.approx(5.0)


def test_relative_altitude_m_is_used_before_local_z() -> None:
    localizer = TargetLocalization()
    drone = {
        "local_x": 0.0,
        "local_y": 0.0,
        "local_z": -10.0,
        "relative_altitude_m": 4.0,
        "yaw": 0.0,
    }

    estimate = localizer.localize_detection({"ex": 0.0, "ey": 0.0}, drone)

    assert estimate["projection"]["altitude_m"] == pytest.approx(4.0)


def test_altitude_fallback_is_used_when_local_z_is_not_negative() -> None:
    localizer = TargetLocalization()
    drone = {
        "local_x": 0.0,
        "local_y": 0.0,
        "local_z": 1.0,
        "altitude": 7.0,
        "yaw": 0.0,
    }

    estimate = localizer.localize_detection({"ex": 0.0, "ey": 0.0}, drone)

    assert estimate["projection"]["altitude_m"] == pytest.approx(7.0)


def test_cx_cy_fallback_computes_center_error() -> None:
    localizer = TargetLocalization()
    detection = {"cx": 320, "cy": 240}
    drone = {"local_x": 2.0, "local_y": 3.0, "local_z": -5.0, "yaw": 0.0}

    estimate = localizer.localize_detection(
        detection,
        drone,
        image_width=640,
        image_height=480,
    )

    assert estimate["source"]["ex"] == pytest.approx(0.0)
    assert estimate["source"]["ey"] == pytest.approx(0.0)
    assert estimate["x"] == pytest.approx(2.0)
    assert estimate["y"] == pytest.approx(3.0)


def test_yaw_zero_maps_ex_to_local_y_and_ey_to_local_x() -> None:
    localizer = TargetLocalization(CameraProjectionConfig(fov_x_deg=90.0, fov_y_deg=90.0))
    drone = {"local_x": 0.0, "local_y": 0.0, "local_z": -10.0, "yaw": 0.0}

    ex_estimate = localizer.localize_detection({"ex": 0.5, "ey": 0.0}, drone)
    ey_estimate = localizer.localize_detection({"ex": 0.0, "ey": 0.5}, drone)

    expected_offset = 10.0 * math.tan(math.radians(90.0) / 4.0)
    assert ex_estimate["x"] == pytest.approx(0.0)
    assert ex_estimate["y"] == pytest.approx(expected_offset)
    assert ey_estimate["x"] == pytest.approx(expected_offset)
    assert ey_estimate["y"] == pytest.approx(0.0)


def test_yaw_pi_over_two_rotates_body_offsets() -> None:
    localizer = TargetLocalization(CameraProjectionConfig(fov_x_deg=90.0, fov_y_deg=90.0))
    drone = {"local_x": 0.0, "local_y": 0.0, "local_z": -10.0, "yaw": math.pi / 2.0}

    ex_estimate = localizer.localize_detection({"ex": 0.5, "ey": 0.0}, drone)
    ey_estimate = localizer.localize_detection({"ex": 0.0, "ey": 0.5}, drone)

    expected_offset = 10.0 * math.tan(math.radians(90.0) / 4.0)
    assert ex_estimate["x"] == pytest.approx(-expected_offset)
    assert ex_estimate["y"] == pytest.approx(0.0, abs=1e-12)
    assert ey_estimate["x"] == pytest.approx(0.0, abs=1e-12)
    assert ey_estimate["y"] == pytest.approx(expected_offset)


def test_image_x_sign_reverses_lateral_offset() -> None:
    localizer = TargetLocalization(
        CameraProjectionConfig(fov_x_deg=90.0, image_x_sign=-1.0)
    )
    drone = {"local_x": 0.0, "local_y": 0.0, "local_z": -10.0, "yaw": 0.0}

    estimate = localizer.localize_detection({"ex": 0.5, "ey": 0.0}, drone)

    expected_offset = 10.0 * math.tan(math.radians(90.0) / 4.0)
    assert estimate["y"] == pytest.approx(-expected_offset)


@pytest.mark.parametrize(
    ("detection", "drone", "kwargs"),
    [
        ({"cx": 320}, {"local_x": 0, "local_y": 0, "local_z": -5, "yaw": 0}, {}),
        ({"ex": 0, "ey": 0}, {"local_y": 0, "local_z": -5, "yaw": 0}, {}),
        ({"ex": 0, "ey": 0}, {"local_x": 0, "local_z": -5, "yaw": 0}, {}),
        ({"ex": 0, "ey": 0}, {"local_x": 0, "local_y": 0, "local_z": -5}, {}),
        ({"ex": 0, "ey": 0}, {"local_x": 0, "local_y": 0, "yaw": 0}, {}),
        ({"ex": 0, "ey": 0}, {"local_x": 0, "local_y": 0, "local_z": -0.01, "yaw": 0}, {}),
    ],
)
def test_localize_detection_rejects_missing_or_invalid_inputs(
    detection: dict[str, object],
    drone: dict[str, object],
    kwargs: dict[str, object],
) -> None:
    localizer = TargetLocalization()

    with pytest.raises(ValueError):
        localizer.localize_detection(detection, drone, **kwargs)


def test_ex_ey_are_not_clamped() -> None:
    localizer = TargetLocalization(CameraProjectionConfig(fov_x_deg=60.0))
    drone = {"local_x": 0.0, "local_y": 0.0, "local_z": -5.0, "yaw": 0.0}

    estimate = localizer.localize_detection({"ex": 1.5, "ey": 0.0}, drone)

    assert estimate["source"]["ex"] == pytest.approx(1.5)
    assert estimate["projection"]["body_right_m"] == pytest.approx(
        5.0 * math.tan(1.5 * math.radians(60.0) / 2.0)
    )


def test_localize_detections_filters_and_skips_bad_detections() -> None:
    localizer = TargetLocalization(min_confidence=0.5, class_names={"cylinder"})
    drone = {"local_x": 1.0, "local_y": 2.0, "local_z": -5.0, "yaw": 0.0}
    detections = [
        {"track_id": 1, "class_name": "cylinder", "confidence": 0.9, "ex": 0.0, "ey": 0.0},
        {"track_id": 2, "class_name": "cylinder", "confidence": 0.4, "ex": 0.0, "ey": 0.0},
        {"track_id": 3, "class_name": "hazard", "confidence": 0.9, "ex": 0.0, "ey": 0.0},
        {"track_id": 4, "class_name": "cylinder", "confidence": 0.9, "cx": 10.0},
    ]

    estimates = localizer.localize_detections(detections, drone)

    assert len(estimates) == 1
    assert estimates[0]["track_id"] == 1
    assert estimates[0]["x"] == pytest.approx(1.0)
    assert estimates[0]["y"] == pytest.approx(2.0)


def test_localize_detections_returns_multiple_estimates() -> None:
    localizer = TargetLocalization()
    drone = {"local_x": 0.0, "local_y": 0.0, "local_z": -5.0, "yaw": 0.0}

    estimates = localizer.localize_detections(
        [
            {"track_id": 1, "ex": 0.0, "ey": 0.0},
            {"track_id": 2, "ex": 0.1, "ey": 0.0},
        ],
        drone,
    )

    assert [estimate["track_id"] for estimate in estimates] == [1, 2]


def test_output_is_plain_json_serializable_dict() -> None:
    localizer = TargetLocalization()
    detection = {
        "track_id": 7,
        "class_id": 2,
        "class_name": "cylinder",
        "confidence": 0.8,
        "cx": 320.0,
        "cy": 240.0,
        "ex": 0.0,
        "ey": 0.0,
    }
    drone = {"local_x": 10.0, "local_y": 20.0, "local_z": -5.0, "yaw": 0.0}

    estimate = localizer.localize_detection(detection, drone)

    assert isinstance(estimate, dict)
    assert estimate["track_id"] == 7
    assert estimate["class_id"] == 2
    assert estimate["class_name"] == "cylinder"
    assert estimate["confidence"] == pytest.approx(0.8)
    json.dumps(estimate)
