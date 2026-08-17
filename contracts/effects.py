from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping, TypeAlias


@dataclass(frozen=True, slots=True)
class VehicleEffect:
    params: Mapping[str, Any] = field(default_factory=dict)
    key: str = ""
    priority: int = 5
    once: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    action_type: ClassVar[str] = ""

    def to_request(self) -> dict[str, Any]:
        return {"action_type": self.action_type, "params": copy.deepcopy(dict(self.params)),
                "key": self.key, "priority": self.priority, "once": self.once,
                **copy.deepcopy(dict(self.metadata))}


@dataclass(frozen=True, slots=True)
class SetMode(VehicleEffect): action_type: ClassVar[str] = "set_mode"
@dataclass(frozen=True, slots=True)
class Arm(VehicleEffect): action_type: ClassVar[str] = "arm"
@dataclass(frozen=True, slots=True)
class Takeoff(VehicleEffect): action_type: ClassVar[str] = "takeoff"
@dataclass(frozen=True, slots=True)
class Land(VehicleEffect): action_type: ClassVar[str] = "land"
@dataclass(frozen=True, slots=True)
class ConditionYaw(VehicleEffect): action_type: ClassVar[str] = "condition_yaw"
@dataclass(frozen=True, slots=True)
class ChangeSpeed(VehicleEffect): action_type: ClassVar[str] = "change_speed"
@dataclass(frozen=True, slots=True)
class LocalGoto(VehicleEffect): action_type: ClassVar[str] = "local_position"
@dataclass(frozen=True, slots=True)
class GlobalGoto(VehicleEffect): action_type: ClassVar[str] = "global_goto"
@dataclass(frozen=True, slots=True)
class BodyVelocity(VehicleEffect): action_type: ClassVar[str] = "body_velocity"
@dataclass(frozen=True, slots=True)
class FlightCommand(VehicleEffect): action_type: ClassVar[str] = "flight_command"
@dataclass(frozen=True, slots=True)
class SetServo(VehicleEffect): action_type: ClassVar[str] = "set_servo"
@dataclass(frozen=True, slots=True)
class ClearMotion(VehicleEffect): action_type: ClassVar[str] = "clear_continuous_commands"
@dataclass(frozen=True, slots=True)
class VisionTargetCommand(VehicleEffect): action_type: ClassVar[str] = "yolo_lock_target"


Effect: TypeAlias = SetMode | Arm | Takeoff | Land | ConditionYaw | ChangeSpeed | LocalGoto | GlobalGoto | BodyVelocity | FlightCommand | SetServo | ClearMotion | VisionTargetCommand

_EFFECT_TYPES = {effect.action_type: effect for effect in (
    SetMode, Arm, Takeoff, Land, ConditionYaw, ChangeSpeed, LocalGoto, GlobalGoto,
    BodyVelocity, FlightCommand, SetServo, ClearMotion, VisionTargetCommand,
)}


def effect_from_request(request: Mapping[str, Any]) -> Effect:
    action_type = str(request.get("action_type") or "")
    effect_type = _EFFECT_TYPES.get(action_type)
    if effect_type is None:
        raise ValueError(f"unsupported effect type: {action_type}")
    known = {"action_type", "params", "key", "priority", "once"}
    return effect_type(
        params=copy.deepcopy(dict(request.get("params") or {})),
        key=str(request.get("key") or ""),
        priority=int(request.get("priority", 5)),
        once=bool(request.get("once", False)),
        metadata=copy.deepcopy({key: value for key, value in request.items() if key not in known}),
    )
