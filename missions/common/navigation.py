from __future__ import annotations

import math
from dataclasses import dataclass

from telemetry_link.models import DroneState


@dataclass(slots=True)
class LocalMissionFrame:
    origin_x: float
    origin_y: float
    origin_z: float
    yaw_rad: float = 0.0


@dataclass(slots=True)
class LocalGoal:
    name: str
    x: float
    y: float
    z: float
    xy_tolerance_m: float = 1.0
    z_tolerance_m: float = 0.5
    max_speed_mps: float = 0.5


def to_mission_position(
    drone: DroneState,
    frame: LocalMissionFrame,
) -> tuple[float, float, float]:
    return (
        float(drone.local_x) - float(frame.origin_x),
        float(drone.local_y) - float(frame.origin_y),
        float(drone.local_z) - float(frame.origin_z),
    )


def mission_to_local_position(
    point: tuple[float, float, float],
    frame: LocalMissionFrame,
) -> tuple[float, float, float]:
    return (
        float(frame.origin_x) + float(point[0]),
        float(frame.origin_y) + float(point[1]),
        float(frame.origin_z) + float(point[2]),
    )


def goal_target_tuple(goal) -> tuple[float, float, float]:
    return (float(goal.x), float(goal.y), float(goal.z))


def local_goal_reached(
    current: tuple[float, float, float],
    target: tuple[float, float, float],
    xy_tolerance_m: float,
    z_tolerance_m: float,
) -> bool:
    if xy_tolerance_m < 0.0 or z_tolerance_m < 0.0:
        return False
    dx = float(current[0]) - float(target[0])
    dy = float(current[1]) - float(target[1])
    dz = float(current[2]) - float(target[2])
    values = (dx, dy, dz, float(xy_tolerance_m), float(z_tolerance_m))
    if not all(math.isfinite(value) for value in values):
        return False
    return math.hypot(dx, dy) <= xy_tolerance_m and abs(dz) <= z_tolerance_m


def local_goal_stable(
    drone: DroneState,
    current: tuple[float, float, float],
    target: tuple[float, float, float],
    xy_tolerance_m: float,
    z_tolerance_m: float,
    max_speed_mps: float,
) -> bool:
    if max_speed_mps < 0.0:
        return False
    if not local_goal_reached(current, target, xy_tolerance_m, z_tolerance_m):
        return False
    speed = math.sqrt(
        float(drone.vx) * float(drone.vx)
        + float(drone.vy) * float(drone.vy)
        + float(drone.vz) * float(drone.vz)
    )
    if not math.isfinite(speed) or not math.isfinite(float(max_speed_mps)):
        return False
    return speed <= max_speed_mps


def hold_elapsed(now: float, since: float | None, hold_s: float) -> bool:
    if since is None:
        return False
    hold = max(float(hold_s), 0.0)
    elapsed = float(now) - float(since)
    return math.isfinite(elapsed) and elapsed >= hold
