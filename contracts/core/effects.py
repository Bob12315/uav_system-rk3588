from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import TypeAlias

from contracts.platform.field import ReferenceVersion


class EffectKind(str, Enum):
    SET_FLIGHT_MODE = "set_flight_mode"
    ARM = "arm"
    TAKEOFF = "takeoff"
    LAND = "land"
    CONDITION_YAW = "condition_yaw"
    CHANGE_SPEED = "change_speed"
    LOCAL_POSITION_TARGET = "local_position_target"
    GLOBAL_POSITION_TARGET = "global_position_target"
    BODY_VELOCITY_TARGET = "body_velocity_target"
    SET_SERVO = "set_servo"
    SET_VISION_TARGET = "set_vision_target"


def _finite(*values: float | None) -> None:
    if any(value is not None and not math.isfinite(value) for value in values):
        raise ValueError("effect numeric fields must be finite")


@dataclass(frozen=True, slots=True)
class SetFlightMode:
    mode: str
    kind: EffectKind = EffectKind.SET_FLIGHT_MODE

    def __post_init__(self) -> None:
        if not self.mode:
            raise ValueError("flight mode must not be empty")


@dataclass(frozen=True, slots=True)
class Arm:
    kind: EffectKind = EffectKind.ARM


@dataclass(frozen=True, slots=True)
class Takeoff:
    altitude_m: float
    kind: EffectKind = EffectKind.TAKEOFF

    def __post_init__(self) -> None:
        _finite(self.altitude_m)
        if self.altitude_m <= 0:
            raise ValueError("takeoff altitude must be positive")


@dataclass(frozen=True, slots=True)
class Land:
    kind: EffectKind = EffectKind.LAND


@dataclass(frozen=True, slots=True)
class ConditionYaw:
    yaw_deg: float
    relative: bool = False
    kind: EffectKind = EffectKind.CONDITION_YAW

    def __post_init__(self) -> None:
        _finite(self.yaw_deg)


@dataclass(frozen=True, slots=True)
class ChangeSpeed:
    speed_mps: float
    kind: EffectKind = EffectKind.CHANGE_SPEED

    def __post_init__(self) -> None:
        _finite(self.speed_mps)
        if self.speed_mps <= 0:
            raise ValueError("speed must be positive")


@dataclass(frozen=True, slots=True)
class LocalPositionTarget:
    north_m: float
    east_m: float
    down_m: float
    yaw_rad: float | None = None
    reference_version: ReferenceVersion | None = None
    kind: EffectKind = EffectKind.LOCAL_POSITION_TARGET

    def __post_init__(self) -> None:
        _finite(self.north_m, self.east_m, self.down_m, self.yaw_rad)


@dataclass(frozen=True, slots=True)
class GlobalPositionTarget:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    reference_version: ReferenceVersion | None = None
    kind: EffectKind = EffectKind.GLOBAL_POSITION_TARGET

    def __post_init__(self) -> None:
        _finite(self.latitude_deg, self.longitude_deg, self.altitude_m)
        if not -90 <= self.latitude_deg <= 90 or not -180 <= self.longitude_deg <= 180:
            raise ValueError("invalid WGS84 position")


@dataclass(frozen=True, slots=True)
class BodyVelocityTarget:
    forward_mps: float
    right_mps: float
    down_mps: float
    yaw_rate_rad_s: float | None = None
    yaw_rad: float | None = None
    kind: EffectKind = EffectKind.BODY_VELOCITY_TARGET

    def __post_init__(self) -> None:
        _finite(self.forward_mps, self.right_mps, self.down_mps, self.yaw_rate_rad_s, self.yaw_rad)
        if self.yaw_rate_rad_s is not None and self.yaw_rad is not None:
            raise ValueError("body velocity cannot set yaw and yaw-rate together")


@dataclass(frozen=True, slots=True)
class SetServo:
    channel: int
    pwm: int
    kind: EffectKind = EffectKind.SET_SERVO

    def __post_init__(self) -> None:
        if not 1 <= self.channel <= 16 or not 800 <= self.pwm <= 2200:
            raise ValueError("servo output is outside the protected envelope")


@dataclass(frozen=True, slots=True)
class SetVisionTarget:
    track_id: int | None
    kind: EffectKind = EffectKind.SET_VISION_TARGET

    def __post_init__(self) -> None:
        if self.track_id is not None and self.track_id < 0:
            raise ValueError("track_id must be non-negative")


Effect: TypeAlias = (
    SetFlightMode | Arm | Takeoff | Land | ConditionYaw | ChangeSpeed |
    LocalPositionTarget | GlobalPositionTarget | BodyVelocityTarget |
    SetServo | SetVisionTarget
)
