from __future__ import annotations

from app.health_monitor import HealthStatus
from missions.common.control.types import MissionStageInput
from fusion.models import PerceptionTarget, SceneDetections, SceneObject
from missions.common.recce import RecceConfig
from missions.base import MissionContext
from missions.rescue_competition import (
    MissionZone,
    DropAlignConfig,
    PayloadRelease,
    PayloadReleaseTiming,
    PayloadSlot,
    RecceMissionConfig,
    RescueCompetitionMission,
    RescueCompetitionMissionConfig,
    RescueStage,
    RoutePoint,
    build_rescue_config,
)
from telemetry_link.models import DroneState, GimbalState, LinkStatus


def _health(vision_fresh: bool = False) -> HealthStatus:
    return HealthStatus(
        vision_fresh=vision_fresh,
        drone_fresh=False,
        gimbal_fresh=False,
        fusion_ready=False,
        control_ready=False,
        target_ready=False,
        hold_reason="not_ready",
    )


def _inputs(
    timestamp: float,
    target_ready: bool = False,
    ex_cam: float = 0.0,
    ey_cam: float = 0.0,
    target_size: float = 0.2,
) -> MissionStageInput:
    return MissionStageInput(
        timestamp=timestamp,
        target_valid=target_ready,
        target_locked=target_ready,
        target_stable=target_ready,
        ex_cam=ex_cam,
        ey_cam=ey_cam,
        target_size=target_size,
        target_size_valid=True,
    )


def _context(
    timestamp: float = 1.0,
    drone: DroneState | None = None,
    target_ready: bool = False,
    scene: SceneDetections | None = None,
    actions_enabled: bool = False,
    ex_cam: float = 0.0,
    ey_cam: float = 0.0,
    target_size: float = 0.2,
) -> MissionContext:
    return MissionContext(
        timestamp=timestamp,
        inputs=_inputs(
            timestamp,
            target_ready=target_ready,
            ex_cam=ex_cam,
            ey_cam=ey_cam,
            target_size=target_size,
        ),
        health=_health(vision_fresh=target_ready),
        perception=PerceptionTarget(timestamp=timestamp),
        drone=drone or DroneState(timestamp=timestamp),
        gimbal=GimbalState(timestamp=timestamp),
        link=LinkStatus(),
        scene=scene,
        actions_enabled=actions_enabled,
    )


def _scene(*detections: SceneObject, timestamp: float = 1.0) -> SceneDetections:
    return SceneDetections(
        timestamp=timestamp,
        frame_id=1,
        image_width=640,
        image_height=480,
        detections=list(detections),
        valid=True,
    )


def _object(
    track_id: int | None = 7,
    class_name: str = "cylinder",
    confidence: float = 0.8,
    ex: float = 0.1,
    ey: float = 0.1,
    cx: float = 352.0,
    cy: float = 264.0,
    x1: float = 300.0,
    y1: float = 220.0,
    x2: float = 400.0,
    y2: float = 320.0,
) -> SceneObject:
    return SceneObject(
        track_id=track_id,
        class_name=class_name,
        confidence=confidence,
        ex=ex,
        ey=ey,
        cx=cx,
        cy=cy,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )


def test_rescue_stage_enum_matches_planned_route() -> None:
    assert [stage.value for stage in RescueStage] == [
        "PREPARE",
        "TAKEOFF",
        "FOLLOW_ROUTE_TO_DROP_ZONE",
        "SEARCH_DROP_TARGETS",
        "ALIGN_AND_DROP",
        "WAIT_PAYLOAD_RELEASE",
        "RESUME_ROUTE_TO_RECCE_ZONE",
        "SCAN_RECCE_AREA",
        "FOLLOW_ROUTE_HOME",
        "LAND",
        "DONE",
        "ABORT",
    ]


def test_rescue_competition_mission_imports_and_stays_idle_by_default() -> None:
    mission = RescueCompetitionMission()

    output = mission.update(_context(timestamp=2.5))

    assert mission.name == "rescue_competition"
    assert output.active_mode == "IDLE"
    assert output.stage == "PREPARE"
    assert not output.done
    assert not output.aborted
    assert output.detail["timestamp"] == 2.5
    assert output.detail["route_points"] == 0


def test_prepare_captures_origin_but_does_not_autostart_by_default() -> None:
    mission = RescueCompetitionMission()
    drone = DroneState(
        local_position_valid=True,
        local_x=10.0,
        local_y=20.0,
        local_z=-2.0,
        yaw=0.25,
    )

    output = mission.update(_context(drone=drone))

    assert output.stage == "PREPARE"
    assert output.hold_reason == ""
    assert output.detail["origin_captured"] is True
    assert output.actions == []


def test_prepare_autostart_transitions_to_takeoff_without_emitting_action_yet() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(auto_start=True)
    )
    drone = DroneState(local_position_valid=True)

    output = mission.update(_context(drone=drone))

    assert output.stage == "TAKEOFF"
    assert output.previous_stage == "PREPARE"
    assert output.actions == []


def test_start_request_transitions_from_prepare_when_origin_is_ready() -> None:
    mission = RescueCompetitionMission()
    mission.start()
    drone = DroneState(local_position_valid=True)

    output = mission.update(_context(drone=drone))

    assert output.stage == "TAKEOFF"
    assert output.previous_stage == "PREPARE"


def test_takeoff_stage_emits_once_takeoff_action_and_advances_at_altitude() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.TAKEOFF,
            takeoff_altitude_m=8.0,
            takeoff_altitude_tolerance_m=0.5,
        )
    )
    low = DroneState(relative_alt_valid=True, relative_altitude=2.0)
    high = DroneState(relative_alt_valid=True, relative_altitude=7.6)

    first = mission.update(_context(drone=low))
    second = mission.update(_context(drone=high))

    assert first.stage == "TAKEOFF"
    assert first.actions[0].action_type == "takeoff"
    assert first.actions[0].params == {"altitude_m": 8.0}
    assert first.actions[0].key == "rescue_takeoff"
    assert second.stage == "FOLLOW_ROUTE_TO_DROP_ZONE"
    assert second.previous_stage == "TAKEOFF"


def test_route_follow_emits_local_position_in_ekf_frame_until_point_is_stable() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.FOLLOW_ROUTE_TO_DROP_ZONE,
            drop_route_end_name="wp1",
            route=[
                RoutePoint(
                    name="wp1",
                    x=5.0,
                    y=-2.0,
                    z=-3.0,
                    xy_tolerance_m=0.5,
                    z_tolerance_m=0.2,
                    max_speed_mps=0.3,
                )
            ],
        )
    )
    enroute = DroneState(
        local_position_valid=True,
        local_x=10.0,
        local_y=20.0,
        local_z=-1.0,
        vx=1.0,
    )
    at_target = DroneState(
        local_position_valid=True,
        local_x=15.0,
        local_y=18.0,
        local_z=-4.0,
        vx=0.0,
        vy=0.0,
        vz=0.0,
    )

    first = mission.update(_context(drone=enroute))
    second = mission.update(_context(drone=at_target))

    assert first.stage == "FOLLOW_ROUTE_TO_DROP_ZONE"
    assert first.hold_reason == "enroute:wp1"
    assert first.actions[0].action_type == "local_position"
    assert first.actions[0].params == {"x": 15.0, "y": 18.0, "z": -4.0, "frame": 1}
    assert second.stage == "SEARCH_DROP_TARGETS"
    assert second.previous_stage == "FOLLOW_ROUTE_TO_DROP_ZONE"
    assert second.detail["route_index"] == 1


def test_search_drop_targets_switches_to_overhead_hold_when_scene_target_stable() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SEARCH_DROP_TARGETS,
            drop_target_stable_frames=2,
        )
    )
    scene = _scene(_object(track_id=7, class_name="cylinder", confidence=0.8))

    searching = mission.update(_context(scene=scene))
    acquired = mission.update(_context(scene=scene))

    assert searching.stage == "SEARCH_DROP_TARGETS"
    assert searching.active_mode == "IDLE"
    assert searching.hold_reason == "searching_drop_targets"
    assert acquired.stage == "ALIGN_AND_DROP"
    assert acquired.previous_stage == "SEARCH_DROP_TARGETS"
    assert acquired.active_mode == "OVERHEAD_HOLD"
    assert acquired.hold_reason == "drop_target_acquired"
    assert acquired.actions[0].action_type == "yolo_lock_target"
    assert acquired.actions[0].params == {"track_id": 7}
    assert acquired.detail["selected_drop_target"]["track_id"] == 7
    assert acquired.detail["selected_drop_target"]["class_name"] == "cylinder"


def test_search_drop_targets_does_not_trigger_without_scene() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(initial_stage=RescueStage.SEARCH_DROP_TARGETS)
    )

    output = mission.update(_context(target_ready=True, scene=None))

    assert output.stage == "SEARCH_DROP_TARGETS"
    assert output.hold_reason == "searching_drop_targets"


def test_search_drop_targets_filters_scene_candidates() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SEARCH_DROP_TARGETS,
            drop_target_classes=["cylinder"],
            drop_target_min_confidence=0.5,
            drop_target_max_center_error=0.35,
            drop_target_stable_frames=1,
        )
    )

    wrong_class = mission.update(
        _context(scene=_scene(_object(class_name="person", confidence=0.9)))
    )
    low_confidence = mission.update(
        _context(scene=_scene(_object(class_name="cylinder", confidence=0.2)))
    )
    off_center = mission.update(
        _context(scene=_scene(_object(class_name="cylinder", confidence=0.9, ex=0.8, ey=0.0)))
    )

    assert wrong_class.stage == "SEARCH_DROP_TARGETS"
    assert low_confidence.stage == "SEARCH_DROP_TARGETS"
    assert off_center.stage == "SEARCH_DROP_TARGETS"


def test_search_drop_targets_selects_center_nearest_candidate() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SEARCH_DROP_TARGETS,
            drop_target_stable_frames=1,
        )
    )

    output = mission.update(
        _context(
            scene=_scene(
                _object(track_id=1, class_name="cylinder", confidence=0.95, ex=0.3, ey=0.0),
                _object(track_id=2, class_name="cylinder", confidence=0.8, ex=0.05, ey=0.0),
            )
        )
    )

    assert output.stage == "ALIGN_AND_DROP"
    assert output.detail["selected_drop_target"]["track_id"] == 2


def test_search_drop_targets_can_stabilize_untracked_candidate_by_center() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SEARCH_DROP_TARGETS,
            drop_target_stable_frames=2,
        )
    )

    first = mission.update(
        _context(scene=_scene(_object(track_id=None, class_name="cylinder", cx=320.0, cy=240.0)))
    )
    second = mission.update(
        _context(scene=_scene(_object(track_id=None, class_name="cylinder", cx=323.0, cy=244.0)))
    )

    assert first.stage == "SEARCH_DROP_TARGETS"
    assert second.stage == "ALIGN_AND_DROP"
    assert second.actions == []


def test_search_drop_targets_can_skip_vision_after_dry_run_hold() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SEARCH_DROP_TARGETS,
            dry_run_skip_vision=True,
            search_drop_duration_s=2.0,
        )
    )

    first = mission.update(_context(timestamp=10.0, target_ready=False))
    second = mission.update(_context(timestamp=11.0, target_ready=False))
    third = mission.update(_context(timestamp=12.1, target_ready=False))

    assert first.stage == "SEARCH_DROP_TARGETS"
    assert second.stage == "SEARCH_DROP_TARGETS"
    assert third.stage == "ALIGN_AND_DROP"
    assert third.previous_stage == "SEARCH_DROP_TARGETS"
    assert third.active_mode == "OVERHEAD_HOLD"
    assert third.hold_reason == "dry_run_drop_target_skip"


def test_align_and_drop_holds_safely_when_payload_release_is_not_configured() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(hold_s=0.0),
            payloads=[PayloadSlot(payload_id=2, label="water")],
        )
    )

    output = mission.update(_context(target_ready=True, actions_enabled=True))

    assert output.active_mode == "OVERHEAD_HOLD"
    assert output.stage == "ALIGN_AND_DROP"
    assert output.previous_stage is None
    assert output.hold_reason == "payload_release_not_configured"
    assert output.actions == []
    assert output.detail["payload_index"] == 0


def test_align_and_drop_can_simulate_payload_release_in_dry_run() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            dry_run_skip_vision=True,
            dry_run_skip_payload_release=True,
            align_drop_duration_s=1.0,
        )
    )

    first = mission.update(_context(timestamp=5.0, target_ready=False))
    second = mission.update(_context(timestamp=6.1, target_ready=False))

    assert first.stage == "ALIGN_AND_DROP"
    assert first.actions == []
    assert first.hold_reason == "aligning_drop_dry_run"
    assert second.stage == "WAIT_PAYLOAD_RELEASE"
    assert second.previous_stage == "ALIGN_AND_DROP"
    assert second.hold_reason == "payload_release_simulated"
    assert second.actions == []


def test_align_and_drop_emits_configured_servo_release_action() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(hold_s=0.0),
            payloads=[
                PayloadSlot(
                    payload_id=2,
                    label="water",
                    release=PayloadRelease(type="servo", channel=9, pwm=1900),
                )
            ],
        )
    )

    output = mission.update(_context(target_ready=True, actions_enabled=True))

    assert output.stage == "WAIT_PAYLOAD_RELEASE"
    assert output.previous_stage == "ALIGN_AND_DROP"
    assert output.hold_reason == "payload_release_requested"
    assert output.actions[0].action_type == "set_servo"
    assert output.actions[0].params == {"channel": 9, "pwm": 1900}
    assert output.actions[0].key == "rescue_release_payload_2"
    assert output.detail["payload_index"] == 0


def test_align_and_drop_emits_configured_relay_release_action() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(hold_s=0.0),
            payloads=[
                PayloadSlot(
                    payload_id=3,
                    release=PayloadRelease(type="relay", relay_id=0, state=True),
                )
            ],
        )
    )

    output = mission.update(_context(target_ready=True, actions_enabled=True))

    assert output.stage == "WAIT_PAYLOAD_RELEASE"
    assert output.actions[0].action_type == "set_relay"
    assert output.actions[0].params == {"relay_id": 0, "state": True}
    assert output.actions[0].key == "rescue_release_payload_3"


def test_align_and_drop_holds_safely_without_payload_config() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(hold_s=0.0),
        )
    )

    output = mission.update(_context(target_ready=True, actions_enabled=True))

    assert output.stage == "ALIGN_AND_DROP"
    assert output.actions == []
    assert output.hold_reason == "no_payload_configured"


def test_align_and_drop_requires_centered_target_before_release() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(max_ex_cam=0.08, max_ey_cam=0.08, hold_s=0.0),
            payloads=[
                PayloadSlot(
                    payload_id=1,
                    release=PayloadRelease(type="servo", channel=9, pwm=1900),
                )
            ],
        )
    )

    output = mission.update(
        _context(
            target_ready=True,
            actions_enabled=True,
            ex_cam=0.2,
            ey_cam=0.0,
        )
    )

    assert output.stage == "ALIGN_AND_DROP"
    assert output.actions == []
    assert output.hold_reason == "aligning_drop"


def test_align_and_drop_requires_hold_time_before_release() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(hold_s=1.0),
            payloads=[
                PayloadSlot(
                    payload_id=1,
                    release=PayloadRelease(type="servo", channel=9, pwm=1900),
                )
            ],
        )
    )

    first = mission.update(_context(timestamp=1.0, target_ready=True, actions_enabled=True))
    second = mission.update(_context(timestamp=1.5, target_ready=True, actions_enabled=True))
    third = mission.update(_context(timestamp=2.1, target_ready=True, actions_enabled=True))

    assert first.stage == "ALIGN_AND_DROP"
    assert first.hold_reason == "aligning_drop"
    assert second.actions == []
    assert third.stage == "WAIT_PAYLOAD_RELEASE"
    assert third.actions[0].action_type == "set_servo"


def test_align_and_drop_returns_to_search_when_target_lost() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(lost_timeout_s=1.0),
        )
    )

    first = mission.update(_context(timestamp=1.0, target_ready=False))
    second = mission.update(_context(timestamp=2.1, target_ready=False))

    assert first.stage == "ALIGN_AND_DROP"
    assert first.hold_reason == "drop_target_vision_stale"
    assert second.stage == "SEARCH_DROP_TARGETS"
    assert second.hold_reason == "drop_target_lost"
    assert second.actions[0].action_type == "yolo_unlock_target"


def test_align_and_drop_timeout_returns_to_search() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.ALIGN_AND_DROP,
            align=DropAlignConfig(timeout_s=1.0, require_target_stable=False),
        )
    )

    first = mission.update(
        _context(timestamp=1.0, target_ready=True, ex_cam=0.2, actions_enabled=True)
    )
    second = mission.update(
        _context(timestamp=2.1, target_ready=True, ex_cam=0.2, actions_enabled=True)
    )

    assert first.stage == "ALIGN_AND_DROP"
    assert second.stage == "SEARCH_DROP_TARGETS"
    assert second.hold_reason == "drop_align_timeout"
    assert second.actions[0].action_type == "yolo_unlock_target"


def test_wait_payload_release_advances_after_delay_and_unlocks_target() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.WAIT_PAYLOAD_RELEASE,
            payload_release=PayloadReleaseTiming(delay_after_action_s=1.0),
            payloads=[PayloadSlot(payload_id=1)],
        )
    )

    first = mission.update(_context(timestamp=10.0, actions_enabled=True))
    second = mission.update(_context(timestamp=10.5, actions_enabled=True))
    third = mission.update(_context(timestamp=11.1, actions_enabled=True))

    assert first.stage == "WAIT_PAYLOAD_RELEASE"
    assert first.hold_reason == "waiting_payload_release"
    assert second.stage == "WAIT_PAYLOAD_RELEASE"
    assert third.stage == "RESUME_ROUTE_TO_RECCE_ZONE"
    assert third.hold_reason == "payload_release_complete"
    assert third.detail["payload_index"] == 1
    assert third.actions[0].action_type == "yolo_unlock_target"


def test_resume_route_to_recce_continues_route_before_scan_recce_area() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.RESUME_ROUTE_TO_RECCE_ZONE,
            recce_route_end_name="recce_center",
            route=[
                RoutePoint(name="recce_entry", x=5.0, y=0.0, z=-2.0),
                RoutePoint(name="recce_center", x=10.0, y=0.0, z=-2.0),
            ],
        )
    )
    enroute = DroneState(local_position_valid=True, local_x=0.0, local_y=0.0, local_z=0.0)
    at_entry = DroneState(local_position_valid=True, local_x=5.0, local_y=0.0, local_z=-2.0)
    at_center = DroneState(local_position_valid=True, local_x=10.0, local_y=0.0, local_z=-2.0)

    first = mission.update(_context(drone=enroute))
    second = mission.update(_context(drone=at_entry))
    third = mission.update(_context(drone=at_center))

    assert first.stage == "RESUME_ROUTE_TO_RECCE_ZONE"
    assert first.hold_reason == "enroute:recce_entry"
    assert first.actions[0].params == {"x": 5.0, "y": 0.0, "z": -2.0, "frame": 1}
    assert second.stage == "RESUME_ROUTE_TO_RECCE_ZONE"
    assert second.detail["route_index"] == 1
    assert third.stage == "SCAN_RECCE_AREA"
    assert third.previous_stage == "RESUME_ROUTE_TO_RECCE_ZONE"


def test_resume_route_to_recce_with_empty_route_advances_to_scan_recce_area() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(initial_stage=RescueStage.RESUME_ROUTE_TO_RECCE_ZONE)
    )

    output = mission.update(_context())

    assert output.stage == "SCAN_RECCE_AREA"
    assert output.previous_stage == "RESUME_ROUTE_TO_RECCE_ZONE"
    assert output.hold_reason == "route_empty"


def test_scan_recce_area_waits_then_advances_home() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SCAN_RECCE_AREA,
            recce=RecceMissionConfig(scan_duration_s=2.0, output_json=False, output_csv=False),
        )
    )

    first = mission.update(_context(timestamp=10.0))
    second = mission.update(_context(timestamp=11.0))
    third = mission.update(_context(timestamp=12.1))

    assert first.stage == "SCAN_RECCE_AREA"
    assert first.hold_reason == "scanning_recce_area"
    assert second.stage == "SCAN_RECCE_AREA"
    assert third.stage == "FOLLOW_ROUTE_HOME"
    assert third.previous_stage == "SCAN_RECCE_AREA"


def test_scan_recce_area_accumulates_results_and_writes_output(tmp_path) -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SCAN_RECCE_AREA,
            recce=RecceMissionConfig(
                config=RecceConfig(
                    cylinder_classes={"cylinder"},
                    hazard_classes={"flammable"},
                    vote_min_count=2,
                    vote_min_confidence_sum=1.0,
                ),
                scan_duration_s=2.0,
                output_dir=str(tmp_path),
                output_json=True,
                output_csv=True,
            ),
        )
    )
    scene = _scene(
        _object(
            track_id=12,
            class_name="cylinder",
            confidence=0.8,
            x1=100.0,
            y1=100.0,
            x2=220.0,
            y2=240.0,
            cx=160.0,
            cy=170.0,
        ),
        _object(
            track_id=30,
            class_name="flammable",
            confidence=0.7,
            x1=140.0,
            y1=145.0,
            x2=180.0,
            y2=185.0,
            cx=160.0,
            cy=165.0,
        ),
    )

    first = mission.update(_context(timestamp=10.0, scene=scene))
    second = mission.update(_context(timestamp=11.0, scene=scene))
    third = mission.update(_context(timestamp=12.1, scene=scene))

    assert first.stage == "SCAN_RECCE_AREA"
    assert second.detail["recce_observation_count"] == 2
    assert third.stage == "FOLLOW_ROUTE_HOME"
    assert third.detail["recce_confirmed_count"] == 1
    assert third.detail["recce_results"][0]["hazard_class"] == "flammable"
    assert third.detail["recce_results"][0]["status"] == "confirmed"
    assert len(third.detail["recce_output_paths"]) == 2
    assert sorted(path.suffix for path in tmp_path.iterdir()) == [".csv", ".json"]


def test_scan_recce_area_without_scene_still_advances_home(tmp_path) -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.SCAN_RECCE_AREA,
            recce=RecceMissionConfig(
                scan_duration_s=0.5,
                output_dir=str(tmp_path),
                output_json=True,
                output_csv=False,
            ),
        )
    )

    first = mission.update(_context(timestamp=1.0, scene=None))
    second = mission.update(_context(timestamp=1.6, scene=None))

    assert first.stage == "SCAN_RECCE_AREA"
    assert second.stage == "FOLLOW_ROUTE_HOME"
    assert second.detail["recce_observation_count"] == 0
    assert second.detail["recce_results"] == []
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_follow_route_home_emits_local_position_until_home_is_stable() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.FOLLOW_ROUTE_HOME,
            home_route_end_name="home",
            route=[
                RoutePoint(
                    name="home",
                    x=0.0,
                    y=0.0,
                    z=-2.0,
                    xy_tolerance_m=0.5,
                    z_tolerance_m=0.2,
                    max_speed_mps=0.3,
                )
            ],
        )
    )
    enroute = DroneState(
        local_position_valid=True,
        local_x=10.0,
        local_y=20.0,
        local_z=-1.0,
        vx=1.0,
    )
    home = DroneState(
        local_position_valid=True,
        local_x=10.0,
        local_y=20.0,
        local_z=-3.0,
        vx=0.0,
        vy=0.0,
        vz=0.0,
    )

    first = mission.update(_context(drone=enroute))
    second = mission.update(_context(drone=home))

    assert first.stage == "FOLLOW_ROUTE_HOME"
    assert first.hold_reason == "returning_home:home"
    assert first.actions[0].action_type == "local_position"
    assert first.actions[0].params == {"x": 10.0, "y": 20.0, "z": -3.0, "frame": 1}
    assert second.stage == "LAND"
    assert second.previous_stage == "FOLLOW_ROUTE_HOME"


def test_follow_route_home_without_route_advances_to_land() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(initial_stage=RescueStage.FOLLOW_ROUTE_HOME)
    )

    output = mission.update(_context())

    assert output.stage == "LAND"
    assert output.previous_stage == "FOLLOW_ROUTE_HOME"
    assert output.hold_reason == "route_empty"
    assert output.actions == []


def test_route_hold_time_delays_route_index_advance() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.FOLLOW_ROUTE_TO_DROP_ZONE,
            drop_route_end_name="drop_center",
            route_hold_s=1.0,
            route=[RoutePoint(name="drop_center", x=0.0, y=0.0, z=0.0)],
        )
    )
    drone = DroneState(local_position_valid=True, vx=0.0, vy=0.0, vz=0.0)

    first = mission.update(_context(timestamp=1.0, drone=drone))
    second = mission.update(_context(timestamp=1.5, drone=drone))
    third = mission.update(_context(timestamp=2.1, drone=drone))

    assert first.stage == "FOLLOW_ROUTE_TO_DROP_ZONE"
    assert first.hold_reason == "arrived:drop_center"
    assert first.detail["route_index"] == 0
    assert second.detail["route_index"] == 0
    assert third.stage == "SEARCH_DROP_TARGETS"
    assert third.detail["route_index"] == 1


def test_invalid_runtime_route_end_aborts_safely() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.FOLLOW_ROUTE_TO_DROP_ZONE,
            drop_route_end_name="missing",
            route=[RoutePoint(name="wp1", x=0.0, y=0.0, z=0.0)],
        )
    )

    output = mission.update(_context(drone=DroneState(local_position_valid=True)))

    assert output.stage == "ABORT"
    assert output.aborted
    assert output.hold_reason == "route_invalid"


def test_land_emits_land_action_and_completes_near_ground() -> None:
    mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(
            initial_stage=RescueStage.LAND,
            land_complete_altitude_m=0.4,
        )
    )
    high = DroneState(relative_alt_valid=True, relative_altitude=2.0)
    low = DroneState(relative_alt_valid=True, relative_altitude=0.3)

    first = mission.update(_context(drone=high))
    second = mission.update(_context(drone=low))

    assert first.stage == "LAND"
    assert first.actions[0].action_type == "land"
    assert first.actions[0].key == "rescue_land"
    assert second.stage == "DONE"
    assert second.previous_stage == "LAND"
    assert second.done


def test_rescue_competition_mission_can_start_done_or_abort_for_future_tests() -> None:
    done_mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(initial_stage=RescueStage.DONE)
    )
    abort_mission = RescueCompetitionMission(
        RescueCompetitionMissionConfig(initial_stage=RescueStage.ABORT)
    )

    assert done_mission.update(_context()).done
    assert abort_mission.update(_context()).aborted


def test_build_rescue_config_parses_route_zones_and_payloads(tmp_path) -> None:
    config = build_rescue_config(
        {
            "initial_stage": "TAKEOFF",
            "idle_mode": "CORRIDOR_FOLLOW",
            "auto_start": True,
            "takeoff_altitude_m": 6.5,
            "takeoff_altitude_tolerance_m": 0.6,
            "local_position_frame": 9,
            "drop_route_end_name": "drop_center",
            "recce_route_end_name": "recce_center",
            "home_route_end_name": "home",
            "route_hold_s": 0.5,
            "align_mode": "OVERHEAD_HOLD",
            "dry_run_skip_vision": True,
            "dry_run_skip_payload_release": "true",
            "search_drop_duration_s": 2.5,
            "align_drop_duration_s": 1.5,
            "drop_target_classes": ["drop_cylinder", "cylinder"],
            "drop_target_min_confidence": 0.55,
            "drop_target_stable_frames": 3,
            "drop_target_max_center_error": 0.25,
            "align": {
                "max_ex_cam": 0.07,
                "max_ey_cam": 0.06,
                "min_target_size": 0.1,
                "require_target_locked": "true",
                "require_target_stable": "false",
                "hold_s": 0.4,
                "timeout_s": 12.0,
                "lost_timeout_s": 1.5,
            },
            "payload_release": {"delay_after_action_s": 1.2},
            "recce": {
                "cylinder_classes": ["recce_cylinder", "cylinder"],
                "hazard_classes": ["flammable", "toxic"],
                "min_cylinder_confidence": 0.4,
                "min_hazard_confidence": 0.45,
                "vote_min_count": 4,
                "vote_min_confidence_sum": 2.5,
                "scan_duration_s": 6.0,
                "output_dir": str(tmp_path),
                "output_json": "true",
                "output_csv": "false",
            },
            "scan_duration_s": 4.5,
            "land_complete_altitude_m": 0.25,
            "route": [
                {
                    "name": "wp1",
                    "x": 1.0,
                    "y": 2.0,
                    "z": -3.0,
                    "xy_tolerance_m": 1.5,
                    "z_tolerance_m": 0.4,
                    "max_speed_mps": 0.2,
                },
                {"name": "drop_center", "x": 2.0, "y": 0.0, "z": -3.0},
                {"name": "recce_center", "x": 3.0, "y": 0.0, "z": -3.0},
                {"name": "home", "x": 0.0, "y": 0.0, "z": -3.0},
            ],
            "drop_zones": [{"name": "drop_a", "x": 4.0, "y": 5.0, "radius_m": 6.0}],
            "recce_zones": [{"x": 7.0, "y": 8.0, "z": -2.0, "radius_m": 9.0}],
            "payloads": [
                {
                    "payload_id": 2,
                    "label": "water",
                    "release": {"type": "servo", "channel": 9, "pwm": 1900},
                },
                {
                    "payload_id": 3,
                    "release": {"type": "relay", "relay_id": 0, "state": "on"},
                },
            ],
        }
    )

    assert config.initial_stage == RescueStage.TAKEOFF
    assert config.idle_mode == "CORRIDOR_FOLLOW"
    assert config.auto_start is True
    assert config.takeoff_altitude_m == 6.5
    assert config.takeoff_altitude_tolerance_m == 0.6
    assert config.local_position_frame == 9
    assert config.drop_route_end_name == "drop_center"
    assert config.recce_route_end_name == "recce_center"
    assert config.home_route_end_name == "home"
    assert config.route_hold_s == 0.5
    assert config.align_mode == "OVERHEAD_HOLD"
    assert config.dry_run_skip_vision is True
    assert config.dry_run_skip_payload_release is True
    assert config.search_drop_duration_s == 2.5
    assert config.align_drop_duration_s == 1.5
    assert config.drop_target_classes == ["drop_cylinder", "cylinder"]
    assert config.drop_target_min_confidence == 0.55
    assert config.drop_target_stable_frames == 3
    assert config.drop_target_max_center_error == 0.25
    assert config.align == DropAlignConfig(
        max_ex_cam=0.07,
        max_ey_cam=0.06,
        min_target_size=0.1,
        require_target_locked=True,
        require_target_stable=False,
        hold_s=0.4,
        timeout_s=12.0,
        lost_timeout_s=1.5,
    )
    assert config.payload_release == PayloadReleaseTiming(delay_after_action_s=1.2)
    assert config.recce.config.cylinder_classes == {"recce_cylinder", "cylinder"}
    assert config.recce.config.hazard_classes == {"flammable", "toxic"}
    assert config.recce.config.min_cylinder_confidence == 0.4
    assert config.recce.config.min_hazard_confidence == 0.45
    assert config.recce.config.vote_min_count == 4
    assert config.recce.config.vote_min_confidence_sum == 2.5
    assert config.recce.scan_duration_s == 6.0
    assert config.recce.output_dir == str(tmp_path)
    assert config.recce.output_json is True
    assert config.recce.output_csv is False
    assert config.scan_duration_s == 4.5
    assert config.land_complete_altitude_m == 0.25
    assert config.route == [
        RoutePoint(
            name="wp1",
            x=1.0,
            y=2.0,
            z=-3.0,
            xy_tolerance_m=1.5,
            z_tolerance_m=0.4,
            max_speed_mps=0.2,
        ),
        RoutePoint(name="drop_center", x=2.0, y=0.0, z=-3.0),
        RoutePoint(name="recce_center", x=3.0, y=0.0, z=-3.0),
        RoutePoint(name="home", x=0.0, y=0.0, z=-3.0),
    ]
    assert config.drop_zones == [MissionZone(name="drop_a", x=4.0, y=5.0, radius_m=6.0)]
    assert config.recce_zones == [
        MissionZone(name="recce_zone_1", x=7.0, y=8.0, z=-2.0, radius_m=9.0)
    ]
    assert config.payloads == [
        PayloadSlot(
            payload_id=2,
            label="water",
            release=PayloadRelease(type="servo", channel=9, pwm=1900),
        ),
        PayloadSlot(
            payload_id=3,
            release=PayloadRelease(type="relay", relay_id=0, state=True),
        ),
    ]


def test_build_rescue_config_rejects_missing_route_end_name() -> None:
    import pytest

    with pytest.raises(ValueError, match="drop_route_end_name"):
        build_rescue_config(
            {
                "route": [{"name": "wp1", "x": 0.0, "y": 0.0, "z": -1.0}],
                "drop_route_end_name": "missing",
                "recce_route_end_name": "wp1",
                "home_route_end_name": "wp1",
            }
        )
