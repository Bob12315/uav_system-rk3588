from __future__ import annotations

import math

import pytest

from fusion.fusion_manager import FusionManager
from fusion.models import FusionConfig, PerceptionTarget, SceneDetections, SceneObject
from telemetry_link.models import DroneState, GimbalState


def _drone(**overrides) -> DroneState:
    data = dict(
        timestamp=10.0,
        connected=True,
        stale=False,
        control_allowed=True,
        attitude_valid=True,
        yaw=0.3,
        vx=1.0,
    )
    data.update(overrides)
    return DroneState(**data)


def _target(**overrides) -> PerceptionTarget:
    data = dict(
        timestamp=9.8,
        frame_id=7,
        target_valid=True,
        tracking_state="locked",
        track_id=42,
        w=80.0,
        h=50.0,
        image_width=640.0,
        image_height=480.0,
        target_size=0.125,
        ex=0.1,
        ey=-0.2,
    )
    data.update(overrides)
    return PerceptionTarget(**data)


def test_locked_target_and_valid_telemetry_produce_fused_state() -> None:
    manager = FusionManager(FusionConfig(require_gimbal_feedback=True))
    gimbal = GimbalState(timestamp=9.9, gimbal_valid=True, yaw=30.0, pitch=-10.0)

    fused = manager.update(_target(), _drone(), gimbal)

    assert fused.target_locked is True
    assert fused.vision_valid is True
    assert fused.drone_valid is True
    assert fused.gimbal_valid is True
    assert fused.control_allowed is True
    assert fused.control_enabled is True
    assert fused.fusion_valid is True
    assert fused.gimbal_yaw == pytest.approx(math.radians(30.0))
    assert fused.gimbal_pitch == pytest.approx(math.radians(-10.0))
    assert fused.ex_body == pytest.approx(0.1 + math.radians(30.0))
    assert fused.ey_body == pytest.approx(-0.2 + math.radians(-10.0))
    assert fused.bbox_area == pytest.approx(4000.0)
    assert fused.target_size == pytest.approx(0.125)


def test_stale_drone_state_disables_control_and_fusion_validity() -> None:
    manager = FusionManager(FusionConfig(require_gimbal_feedback=False))
    gimbal = GimbalState(timestamp=9.9, gimbal_valid=False)

    fused = manager.update(_target(), _drone(stale=True), gimbal)

    assert fused.drone_valid is False
    assert fused.control_allowed is False
    assert fused.control_enabled is False
    assert fused.fusion_valid is False


def test_missing_gimbal_feedback_can_degrade_when_config_allows_it() -> None:
    manager = FusionManager(FusionConfig(require_gimbal_feedback=False))
    gimbal = GimbalState(timestamp=9.9, gimbal_valid=False, yaw=30.0, pitch=-10.0)

    fused = manager.update(_target(), _drone(), gimbal)

    assert fused.gimbal_valid is False
    assert fused.ex_body == pytest.approx(0.1)
    assert fused.ey_body == pytest.approx(-0.2)
    assert fused.fusion_valid is True


def test_unlocked_target_is_not_control_enabled() -> None:
    manager = FusionManager(FusionConfig(require_gimbal_feedback=False))

    fused = manager.update(
        _target(tracking_state="searching"),
        _drone(),
        GimbalState(timestamp=9.9, gimbal_valid=False),
    )

    assert fused.target_locked is False
    assert fused.control_allowed is True
    assert fused.control_enabled is False
    assert fused.fusion_valid is False


def test_scene_detections_model_defaults_and_objects() -> None:
    scene = SceneDetections(
        timestamp=1.0,
        frame_id=2,
        image_width=640,
        image_height=480,
        detections=[
            SceneObject(
                track_id=7,
                class_id=3,
                class_name="cylinder",
                confidence=0.8,
                cx=320.0,
                cy=240.0,
            )
        ],
        valid=True,
    )

    assert scene.valid is True
    assert scene.detections[0].track_id == 7
    assert scene.detections[0].class_name == "cylinder"
    assert scene.detections[0].confidence == 0.8
