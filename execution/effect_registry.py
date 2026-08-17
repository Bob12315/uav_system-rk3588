from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from contracts.core.effects import EffectKind


class EffectRoute(str, Enum):
    VEHICLE = "vehicle"
    VISION = "vision"


@dataclass(frozen=True, slots=True)
class EffectRule:
    kind: EffectKind
    capability: str
    route: EffectRoute
    safety_profile: str
    translator_id: str
    protected: bool = False


_RULES = (
    EffectRule(EffectKind.SET_FLIGHT_MODE, "flight.mode", EffectRoute.VEHICLE, "flight", "set_mode"),
    EffectRule(EffectKind.ARM, "flight.arm", EffectRoute.VEHICLE, "flight", "arm"),
    EffectRule(EffectKind.TAKEOFF, "flight.takeoff", EffectRoute.VEHICLE, "flight", "takeoff"),
    EffectRule(EffectKind.LAND, "flight.land", EffectRoute.VEHICLE, "flight", "land"),
    EffectRule(EffectKind.CONDITION_YAW, "flight.yaw", EffectRoute.VEHICLE, "flight", "condition_yaw"),
    EffectRule(EffectKind.CHANGE_SPEED, "flight.speed", EffectRoute.VEHICLE, "flight", "change_speed"),
    EffectRule(EffectKind.LOCAL_POSITION_TARGET, "flight.position.local", EffectRoute.VEHICLE, "navigation", "local"),
    EffectRule(EffectKind.GLOBAL_POSITION_TARGET, "flight.position.global", EffectRoute.VEHICLE, "navigation", "global"),
    EffectRule(EffectKind.BODY_VELOCITY_TARGET, "flight.velocity.body", EffectRoute.VEHICLE, "continuous", "body_velocity"),
    EffectRule(EffectKind.SET_SERVO, "payload.release", EffectRoute.VEHICLE, "payload_release_v1", "servo", True),
    EffectRule(EffectKind.SET_VISION_TARGET, "vision.target", EffectRoute.VISION, "vision", "vision_target"),
)

EFFECT_REGISTRY = {rule.kind: rule for rule in _RULES}
if set(EFFECT_REGISTRY) != set(EffectKind):
    raise RuntimeError("Effect union and registry are not one-to-one")
