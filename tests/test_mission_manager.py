from __future__ import annotations

from app.health_monitor import HealthStatus
from app.mission_manager import MissionManager, MissionManagerConfig
from missions.common.control.types import MissionStageInput


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


def test_default_mode_is_approach_track_and_config_can_start_idle() -> None:
    assert MissionManager().update(_inputs(), _health()).active_mode == "APPROACH_TRACK"
    assert (
        MissionManager(MissionManagerConfig(initial_mode="IDLE"))
        .update(_inputs(), _health(False))
        .active_mode
        == "IDLE"
    )


def test_enters_overhead_after_conditions_hold() -> None:
    manager = MissionManager(
        MissionManagerConfig(overhead_entry_target_size_thresh=0.3, overhead_entry_hold_s=0.5)
    )

    first = manager.update(_inputs(timestamp=1.0), _health())
    second = manager.update(_inputs(timestamp=1.6), _health())

    assert first.active_mode == "APPROACH_TRACK"
    assert second.active_mode == "OVERHEAD_HOLD"


def test_exits_overhead_on_target_lost_or_size_drop() -> None:
    manager = MissionManager(
        MissionManagerConfig(overhead_entry_target_size_thresh=0.3, overhead_entry_hold_s=0.0)
    )
    manager.update(_inputs(timestamp=1.0), _health())
    assert manager.update(_inputs(timestamp=1.1), _health()).active_mode == "OVERHEAD_HOLD"

    assert (
        manager.update(_inputs(timestamp=1.2, target_valid=False), _health()).active_mode
        == "APPROACH_TRACK"
    )

    manager = MissionManager(
        MissionManagerConfig(
            overhead_entry_target_size_thresh=0.3,
            overhead_entry_hold_s=0.0,
            overhead_exit_target_size_drop=0.06,
        )
    )
    manager.update(_inputs(timestamp=1.0, target_size=0.4), _health())
    manager.update(_inputs(timestamp=1.1, target_size=0.4), _health())
    assert (
        manager.update(_inputs(timestamp=1.2, target_size=0.3), _health()).active_mode
        == "APPROACH_TRACK"
    )


def test_health_not_ready_forces_idle() -> None:
    manager = MissionManager()

    state = manager.update(_inputs(), _health(False))

    assert state.active_mode == "IDLE"
    assert state.hold_reason == "fusion_invalid"
