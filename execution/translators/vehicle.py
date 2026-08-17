from __future__ import annotations

from contracts.core.effects import (
    Arm as CoreArm,
    BodyVelocityTarget,
    ChangeSpeed as CoreChangeSpeed,
    ConditionYaw as CoreConditionYaw,
    Effect,
    GlobalPositionTarget as CoreGlobal,
    Land as CoreLand,
    LocalPositionTarget as CoreLocal,
    SetFlightMode,
    SetServo as CoreServo,
    Takeoff as CoreTakeoff,
)
from contracts.platform.vehicle_commands import (
    Arm,
    BodyVelocity,
    ChangeSpeed,
    ConditionYaw,
    GlobalPositionTarget,
    Land,
    LocalPositionTarget,
    SetMode,
    SetServo,
    Takeoff,
    VehicleCommand,
)


def translate_vehicle_effect(effect: Effect) -> VehicleCommand:
    if isinstance(effect, SetFlightMode):
        return SetMode(effect.mode)
    if isinstance(effect, CoreArm):
        return Arm()
    if isinstance(effect, CoreTakeoff):
        return Takeoff(effect.altitude_m)
    if isinstance(effect, CoreLand):
        return Land()
    if isinstance(effect, CoreConditionYaw):
        return ConditionYaw(effect.yaw_deg, effect.relative)
    if isinstance(effect, CoreChangeSpeed):
        return ChangeSpeed(effect.speed_mps)
    if isinstance(effect, CoreLocal):
        return LocalPositionTarget(effect.north_m, effect.east_m, effect.down_m, effect.yaw_rad)
    if isinstance(effect, CoreGlobal):
        return GlobalPositionTarget(effect.latitude_deg, effect.longitude_deg, effect.altitude_m)
    if isinstance(effect, BodyVelocityTarget):
        return BodyVelocity(effect.forward_mps, effect.right_mps, effect.down_mps,
                            effect.yaw_rate_rad_s, effect.yaw_rad)
    if isinstance(effect, CoreServo):
        return SetServo(effect.channel, effect.pwm)
    raise TypeError(f"effect is not vehicle-routable: {effect.kind.value}")
