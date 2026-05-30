from __future__ import annotations

from app.health_monitor import HealthStatus
from missions.common.control.types import MissionStageInput
from fusion.models import PerceptionTarget
from missions.base import MissionContext
from missions.visual_tracking import VisualTrackingMission, VisualTrackingMissionConfig
from telemetry_link.models import DroneState, GimbalState, LinkStatus


def _health(ready: bool = True) -> HealthStatus:
    return HealthStatus(
        vision_fresh=ready,
        drone_fresh=ready,
        gimbal_fresh=ready,
        fusion_ready=ready,
        control_ready=ready,
        target_ready=ready,
        hold_reason="" if ready else "fusion_invalid",
    )


def _inputs(**overrides) -> MissionStageInput:
    data = dict(
        timestamp=1.0,
        fused_valid=True,
        target_valid=True,
        target_locked=True,
        vision_valid=True,
        drone_valid=True,
        gimbal_valid=True,
        control_allowed=True,
        track_switched=False,
        target_stable=True,
        target_size=0.4,
        target_size_valid=True,
        gimbal_pitch=-1.5707963267948966,
        gimbal_yaw=0.0,
    )
    data.update(overrides)
    return MissionStageInput(**data)


def _context(inputs: MissionStageInput, health: HealthStatus) -> MissionContext:
    return MissionContext(
        timestamp=float(inputs.timestamp),
        inputs=inputs,
        health=health,
        perception=PerceptionTarget(),
        drone=DroneState(),
        gimbal=GimbalState(),
        link=LinkStatus(),
    )


def test_default_mode_is_approach_track() -> None:
    mission = VisualTrackingMission()

    output = mission.update(_context(_inputs(), _health()))

    assert output.active_mode == "APPROACH_TRACK"
    assert output.stage == "APPROACH_TRACK"


def test_enters_overhead_after_conditions_hold() -> None:
    mission = VisualTrackingMission(
        VisualTrackingMissionConfig(
            overhead_entry_target_size_thresh=0.3,
            overhead_entry_hold_s=0.5,
        )
    )

    first = mission.update(_context(_inputs(timestamp=1.0), _health()))
    second = mission.update(_context(_inputs(timestamp=1.6), _health()))

    assert first.active_mode == "APPROACH_TRACK"
    assert second.active_mode == "OVERHEAD_HOLD"
    assert second.previous_stage == "APPROACH_TRACK"


def test_exits_overhead_on_target_lost_or_size_drop() -> None:
    mission = VisualTrackingMission(
        VisualTrackingMissionConfig(
            overhead_entry_target_size_thresh=0.3,
            overhead_entry_hold_s=0.0,
        )
    )
    mission.update(_context(_inputs(timestamp=1.0), _health()))
    assert mission.update(_context(_inputs(timestamp=1.1), _health())).active_mode == "OVERHEAD_HOLD"

    output = mission.update(_context(_inputs(timestamp=1.2, target_valid=False), _health()))

    assert output.active_mode == "APPROACH_TRACK"
    assert output.hold_reason == "exit_overhead"


def test_fusion_not_ready_forces_idle() -> None:
    mission = VisualTrackingMission()

    output = mission.update(_context(_inputs(), _health(False)))

    assert output.active_mode == "IDLE"
    assert output.hold_reason == "fusion_invalid"
