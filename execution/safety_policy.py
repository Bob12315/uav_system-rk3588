from __future__ import annotations

from dataclasses import dataclass

from contracts.core.common import freeze_json
from contracts.core.effects import BodyVelocityTarget, ChangeSpeed, Effect, SetServo, SetVisionTarget, Takeoff
from contracts.core.execution import SafetyContext, SafetyDecision, SafetyDisposition


@dataclass(frozen=True, slots=True)
class SafetyPolicyConfig:
    revision: str = "v1"
    max_takeoff_altitude_m: float = 20.0
    max_speed_mps: float = 5.0
    max_body_velocity_mps: float = 3.0
    payload_servo_channel: int = 9
    payload_pwm_values: frozenset[int] = frozenset({1100, 1900})


class SafetyPolicy:
    def __init__(self, config: SafetyPolicyConfig) -> None:
        self._config = config

    def evaluate(self, effect: Effect, context: SafetyContext) -> SafetyDecision:
        if not context.send_enabled and not isinstance(effect, SetVisionTarget):
            return self._reject(effect, "send_disabled")
        if isinstance(effect, Takeoff) and effect.altitude_m > self._config.max_takeoff_altitude_m:
            return self._reject(effect, "takeoff_altitude_exceeded")
        if isinstance(effect, SetServo):
            if effect.channel != self._config.payload_servo_channel or effect.pwm not in self._config.payload_pwm_values:
                return self._reject(effect, "payload_whitelist_rejected")
        if isinstance(effect, ChangeSpeed) and effect.speed_mps > self._config.max_speed_mps:
            modified = ChangeSpeed(self._config.max_speed_mps)
            return SafetyDecision(SafetyDisposition.MODIFY, effect, modified, "speed_clamped", freeze_json({}))
        if isinstance(effect, BodyVelocityTarget):
            limit = self._config.max_body_velocity_mps
            values = (effect.forward_mps, effect.right_mps, effect.down_mps)
            clamped = tuple(max(-limit, min(limit, value)) for value in values)
            if clamped != values:
                modified = BodyVelocityTarget(*clamped, effect.yaw_rate_rad_s, effect.yaw_rad)
                return SafetyDecision(SafetyDisposition.MODIFY, effect, modified, "velocity_clamped", freeze_json({}))
        return SafetyDecision(SafetyDisposition.ALLOW, effect, effect, None, freeze_json({}))

    @staticmethod
    def _reject(effect: Effect, reason: str) -> SafetyDecision:
        return SafetyDecision(SafetyDisposition.REJECT, effect, None, reason, freeze_json({}))
