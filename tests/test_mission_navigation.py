from __future__ import annotations

from missions.common.navigation import (
    LocalGoal,
    LocalMissionFrame,
    goal_target_tuple,
    hold_elapsed,
    local_goal_reached,
    local_goal_stable,
    mission_to_local_position,
    to_mission_position,
)
from telemetry_link.models import DroneState


def test_to_mission_position_uses_local_origin_translation() -> None:
    drone = DroneState(local_x=12.5, local_y=-3.0, local_z=-8.0)
    frame = LocalMissionFrame(origin_x=10.0, origin_y=-5.0, origin_z=-3.0)

    assert to_mission_position(drone, frame) == (2.5, 2.0, -5.0)


def test_mission_to_local_position_uses_local_origin_translation() -> None:
    frame = LocalMissionFrame(origin_x=10.0, origin_y=-5.0, origin_z=-3.0)

    assert mission_to_local_position((2.5, 2.0, -5.0), frame) == (12.5, -3.0, -8.0)


def test_goal_target_tuple_reads_goal_coordinates() -> None:
    goal = LocalGoal(name="wp", x=1.0, y=2.0, z=-3.0)

    assert goal_target_tuple(goal) == (1.0, 2.0, -3.0)


def test_local_goal_reached_uses_xy_radius_and_z_tolerance() -> None:
    assert local_goal_reached(
        current=(3.0, 4.0, -1.2),
        target=(0.0, 0.0, -1.0),
        xy_tolerance_m=5.0,
        z_tolerance_m=0.25,
    )
    assert not local_goal_reached(
        current=(3.1, 4.0, -1.2),
        target=(0.0, 0.0, -1.0),
        xy_tolerance_m=5.0,
        z_tolerance_m=0.25,
    )
    assert not local_goal_reached(
        current=(3.0, 4.0, -1.4),
        target=(0.0, 0.0, -1.0),
        xy_tolerance_m=5.0,
        z_tolerance_m=0.25,
    )


def test_local_goal_reached_rejects_invalid_tolerances() -> None:
    assert not local_goal_reached((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), -1.0, 1.0)
    assert not local_goal_reached((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0, -1.0)


def test_local_goal_stable_requires_position_and_speed() -> None:
    slow_drone = DroneState(vx=0.2, vy=0.1, vz=0.0)
    fast_drone = DroneState(vx=1.0, vy=1.0, vz=0.0)

    assert local_goal_stable(
        slow_drone,
        current=(0.2, 0.2, -1.0),
        target=(0.0, 0.0, -1.0),
        xy_tolerance_m=0.5,
        z_tolerance_m=0.2,
        max_speed_mps=0.3,
    )
    assert not local_goal_stable(
        fast_drone,
        current=(0.2, 0.2, -1.0),
        target=(0.0, 0.0, -1.0),
        xy_tolerance_m=0.5,
        z_tolerance_m=0.2,
        max_speed_mps=0.3,
    )
    assert not local_goal_stable(
        slow_drone,
        current=(1.0, 1.0, -1.0),
        target=(0.0, 0.0, -1.0),
        xy_tolerance_m=0.5,
        z_tolerance_m=0.2,
        max_speed_mps=0.3,
    )


def test_hold_elapsed_handles_missing_since_and_non_positive_hold() -> None:
    assert not hold_elapsed(now=10.0, since=None, hold_s=0.0)
    assert hold_elapsed(now=10.0, since=10.0, hold_s=0.0)
    assert hold_elapsed(now=10.0, since=10.0, hold_s=-1.0)
    assert not hold_elapsed(now=10.5, since=10.0, hold_s=1.0)
    assert hold_elapsed(now=11.0, since=10.0, hold_s=1.0)
