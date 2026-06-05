from __future__ import annotations

import math

import pytest

from app.health_monitor import HealthStatus
from fusion.models import PerceptionTarget, SceneDetections, SceneObject
from missions.base import MissionContext
from missions.common.control.types import MissionStageInput
from missions.common.navigation import LocalMissionFrame
from missions.rescue_competition import (
    DropConfig,
    PayloadSlot,
    RescueCompetitionMission,
    RescueCompetitionMissionConfig,
    RescueStage,
    SurveyPoint,
    VisionConfig,
    build_rescue_config,
)
from missions.rescue_competition.geometry import (
    CameraGeometryConfig,
    detection_to_mission_xy,
    image_offset_to_ground,
)
from missions.rescue_competition.survey import EstimatedObject, cluster_estimates, select_targets
from telemetry_link.models import DroneState, GimbalState


def _health() -> HealthStatus:
    return HealthStatus(
        vision_fresh=True,
        drone_fresh=True,
        gimbal_fresh=False,
        fusion_ready=True,
        control_ready=True,
        target_ready=True,
        hold_reason="",
    )


def _inputs(**overrides) -> MissionStageInput:
    data = dict(
        timestamp=1.0,
        fused_valid=True,
        target_valid=True,
        target_locked=True,
        vision_valid=True,
        drone_valid=True,
        control_allowed=True,
        ex_cam=0.0,
        ey_cam=0.0,
        vision_age_s=0.01,
        drone_age_s=0.01,
    )
    data.update(overrides)
    return MissionStageInput(**data)


def _context(
    *,
    timestamp: float = 1.0,
    drone: DroneState | None = None,
    scene: SceneDetections | None = None,
    inputs: MissionStageInput | None = None,
) -> MissionContext:
    return MissionContext(
        timestamp=timestamp,
        inputs=inputs or _inputs(timestamp=timestamp),
        health=_health(),
        perception=PerceptionTarget(timestamp=timestamp),
        drone=drone or DroneState(timestamp=timestamp),
        gimbal=GimbalState(timestamp=timestamp),
        link=None,
        scene=scene,
        actions_enabled=False,
    )


def _drone(**overrides) -> DroneState:
    data = dict(
        timestamp=1.0,
        armed=True,
        local_position_valid=True,
        relative_alt_valid=True,
        local_x=0.0,
        local_y=0.0,
        local_z=-5.0,
        relative_altitude=5.0,
        yaw=0.0,
        vx=0.0,
        vy=0.0,
        vz=0.0,
    )
    data.update(overrides)
    return DroneState(**data)


def _obj(
    *,
    track_id: int = 1,
    class_name: str = "cylinder",
    confidence: float = 0.8,
    ex: float = 0.0,
    ey: float = 0.0,
    target_size: float = 0.08,
) -> SceneObject:
    return SceneObject(
        track_id=track_id,
        class_name=class_name,
        confidence=confidence,
        ex=ex,
        ey=ey,
        target_size=target_size,
    )


def _scene(*detections: SceneObject) -> SceneDetections:
    return SceneDetections(
        timestamp=1.0,
        frame_id=1,
        image_width=640,
        image_height=480,
        detections=list(detections),
        valid=True,
    )


def test_image_offset_to_ground_uses_height_and_fov() -> None:
    forward, right = image_offset_to_ground(
        nx=1.0,
        ny=0.0,
        altitude_m=5.0,
        config=CameraGeometryConfig(fov_x_deg=75.0, fov_y_deg=75.0),
    )

    assert forward == pytest.approx(0.0)
    assert right == pytest.approx(3.836, rel=1e-3)


def test_detection_to_mission_xy_rotates_camera_offset_by_drone_yaw() -> None:
    x, y = detection_to_mission_xy(
        _obj(ex=1.0, ey=0.0),
        drone_mission_x=10.0,
        drone_mission_y=5.0,
        altitude_m=5.0,
        config=CameraGeometryConfig(fov_x_deg=75.0, fov_y_deg=75.0),
        drone_yaw_rad=math.pi / 2.0,
        mission_yaw_rad=0.0,
    )

    assert x == pytest.approx(10.0 - 3.836, rel=1e-3)
    assert y == pytest.approx(5.0, abs=1e-6)


def test_survey_clusters_duplicate_observations_and_selects_two_targets() -> None:
    estimates = [
        EstimatedObject("cylinder", 0.8, 0.08, 30.0, 0.0),
        EstimatedObject("cylinder", 0.7, 0.07, 30.2, 0.1),
        EstimatedObject("cylinder", 0.9, 0.09, 31.5, 1.0),
        EstimatedObject("cylinder", 0.6, 0.06, 35.0, 0.0),
    ]

    clusters = cluster_estimates(estimates, radius_m=0.8)
    selected = select_targets(clusters, count=2, min_separation_m=0.8)

    assert len(clusters) == 3
    assert clusters[0].seen_count == 2
    assert len(selected) == 2


def test_build_rescue_config_uses_new_defaults_and_strict_bools() -> None:
    config = build_rescue_config({})

    assert config.drop.survey_altitude_m == pytest.approx(5.0)
    assert config.drop.transit_altitude_m == pytest.approx(3.0)
    assert config.drop.release_altitude_m == pytest.approx(1.0)
    assert config.recce.identify_altitude_m == pytest.approx(2.0)
    assert config.recce.visual_descend_altitude_m == pytest.approx(1.0)
    assert [slot.servo_channel for slot in config.payload_slots] == [8, 9]

    with pytest.raises(ValueError):
        build_rescue_config({"auto_start": "false"})


def test_release_payload_uses_configured_servo_channel_and_pwm() -> None:
    config = RescueCompetitionMissionConfig(
        initial_stage=RescueStage.RELEASE_PAYLOAD,
        payload_slots=[
            PayloadSlot(payload_id=1, servo_channel=8, hold_pwm=1000, release_pwm=1800),
        ],
    )
    mission = RescueCompetitionMission(config)

    output = mission.update(_context(timestamp=10.0))

    assert output.stage == "RELEASE_PAYLOAD"
    assert output.actions[0].action_type == "set_servo"
    assert output.actions[0].params == {"channel": 8, "pwm": 1800}


def test_drop_gate_prevents_recce_when_required_payloads_not_complete() -> None:
    config = RescueCompetitionMissionConfig(initial_stage=RescueStage.GOTO_RECCE_SURVEY)
    mission = RescueCompetitionMission(config)

    output = mission.update(_context(drone=_drone()))

    assert output.stage == "FAILSAFE"
    assert output.aborted is True
    assert output.hold_reason == "drop_gate_failed"


def test_rescue_waypoint_actions_hold_captured_origin_yaw() -> None:
    config = RescueCompetitionMissionConfig(
        initial_stage=RescueStage.GOTO_DROP_SURVEY,
        drop=DropConfig(survey_points=[SurveyPoint(name="drop_p1", x=2.0, y=0.0)]),
    )
    mission = RescueCompetitionMission(config)
    mission._origin = LocalMissionFrame(origin_x=0.0, origin_y=0.0, origin_z=0.0, yaw_rad=1.25)

    output = mission.update(_context(drone=_drone(local_x=0.0, local_y=0.0, local_z=-5.0)))

    assert output.actions[0].action_type == "local_position"
    assert output.actions[0].params["yaw"] == pytest.approx(1.25)


def test_rescue_detail_reports_mission_frame_position_and_origin() -> None:
    config = RescueCompetitionMissionConfig(initial_stage=RescueStage.GOTO_DROP_SURVEY)
    mission = RescueCompetitionMission(config)
    mission._origin = LocalMissionFrame(origin_x=10.0, origin_y=-5.0, origin_z=-3.0, yaw_rad=1.5707963267948966)

    output = mission.update(_context(drone=_drone(local_x=10.0, local_y=0.0, local_z=-8.0)))

    assert output.detail["origin"] == {
        "local_x": 10.0,
        "local_y": -5.0,
        "local_z": -3.0,
        "yaw_rad": pytest.approx(1.5707963267948966),
    }
    assert output.detail["mission_position"] == pytest.approx({"x": 5.0, "y": 0.0, "z": -5.0})
    assert output.detail["drop_required_count"] == 2
    assert output.detail["recce_required_confirmed_count"] == 3


def test_lock_target_uses_scene_track_id_for_current_target() -> None:
    config = RescueCompetitionMissionConfig(initial_stage=RescueStage.LOCK_DROP_TARGET)
    mission = RescueCompetitionMission(config)
    mission._origin = LocalMissionFrame(origin_x=0.0, origin_y=0.0, origin_z=0.0, yaw_rad=0.0)
    mission._drop_targets = cluster_estimates(
        [EstimatedObject("cylinder", 0.9, 0.1, 0.0, 0.0)],
        radius_m=0.8,
    )

    output = mission.update(
        _context(
            drone=_drone(local_x=0.0, local_y=0.0, local_z=-5.0),
            scene=_scene(_obj(track_id=42)),
        )
    )

    assert output.actions[0].action_type == "yolo_lock_target"
    assert output.actions[0].params == {"track_id": 42}
    assert output.stage == "ALIGN_DESCEND_DROP"


def test_goto_recce_target_commands_current_target_position() -> None:
    config = RescueCompetitionMissionConfig(initial_stage=RescueStage.GOTO_RECCE_TARGET)
    mission = RescueCompetitionMission(config)
    mission._origin = LocalMissionFrame(
        origin_x=10.0,
        origin_y=-5.0,
        origin_z=-1.0,
        yaw_rad=1.5707963267948966,
    )
    mission._recce_targets = cluster_estimates(
        [EstimatedObject("cylinder", 0.9, 0.1, 6.0, 2.0)],
        radius_m=0.8,
    )

    output = mission.update(
        _context(
            drone=_drone(
                local_x=10.0,
                local_y=-5.0,
                local_z=-5.0,
            )
        )
    )

    assert output.stage == "GOTO_RECCE_TARGET"
    assert output.hold_reason == "goto_recce_target"
    assert output.actions[0].action_type == "local_position"
    assert output.actions[0].params == pytest.approx(
        {
            "x": 8.0,
            "y": 1.0,
            "z": -3.0,
            "frame": 1,
            "yaw": 1.5707963267948966,
        }
    )


def test_goto_recce_target_transitions_after_reaching_target() -> None:
    config = RescueCompetitionMissionConfig(initial_stage=RescueStage.GOTO_RECCE_TARGET)
    mission = RescueCompetitionMission(config)
    mission._origin = LocalMissionFrame(
        origin_x=10.0,
        origin_y=-5.0,
        origin_z=-1.0,
        yaw_rad=1.5707963267948966,
    )
    mission._recce_targets = cluster_estimates(
        [EstimatedObject("cylinder", 0.9, 0.1, 6.0, 2.0)],
        radius_m=0.8,
    )

    output = mission.update(
        _context(
            drone=_drone(
                local_x=8.0,
                local_y=1.0,
                local_z=-3.0,
                vx=0.0,
                vy=0.0,
                vz=0.0,
            )
        )
    )

    assert output.stage == "LOCK_RECCE_TARGET"
    assert output.previous_stage == "GOTO_RECCE_TARGET"
    assert output.hold_reason == "at_recce_target"


def test_lock_recce_target_chooses_bucket_nearest_image_center() -> None:
    config = RescueCompetitionMissionConfig(
        initial_stage=RescueStage.LOCK_RECCE_TARGET,
        vision=VisionConfig(cylinder_classes={"bucket"}),
    )
    mission = RescueCompetitionMission(config)
    mission._origin = LocalMissionFrame(origin_x=0.0, origin_y=0.0, origin_z=0.0, yaw_rad=0.0)
    mission._recce_targets = cluster_estimates(
        [EstimatedObject("cylinder", 0.9, 0.1, 6.0, 2.0)],
        radius_m=0.8,
    )

    output = mission.update(
        _context(
            drone=_drone(local_x=6.0, local_y=2.0, local_z=-2.0, relative_altitude=2.0),
            scene=_scene(
                _obj(track_id=10, class_name="bucket", ex=0.1, ey=-0.1),
                _obj(track_id=11, class_name="bucket", ex=0.01, ey=0.02),
            ),
        )
    )

    assert output.actions[0].action_type == "yolo_lock_target"
    assert output.actions[0].params == {"track_id": 11}
    assert output.stage == "ALIGN_DESCEND_RECCE"


def test_align_descend_recce_uses_visual_mode_until_one_meter() -> None:
    config = RescueCompetitionMissionConfig(initial_stage=RescueStage.ALIGN_DESCEND_RECCE)
    mission = RescueCompetitionMission(config)

    output = mission.update(_context(drone=_drone(local_z=-1.5, relative_altitude=1.5)))

    assert output.stage == "ALIGN_DESCEND_RECCE"
    assert output.active_mode == "DOWNWARD_ALIGN_DESCEND"
    assert output.hold_reason == "align_descend_recce"


def test_align_descend_recce_transitions_at_visual_descend_altitude() -> None:
    config = RescueCompetitionMissionConfig(initial_stage=RescueStage.ALIGN_DESCEND_RECCE)
    mission = RescueCompetitionMission(config)

    output = mission.update(_context(drone=_drone(local_z=-1.0, relative_altitude=1.0)))

    assert output.stage == "CAPTURE_RECCE"
    assert output.previous_stage == "ALIGN_DESCEND_RECCE"
    assert output.hold_reason == "recce_visual_descend_altitude_reached"
