from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

try:
    from missions.common.control.types import MissionStageInput
except ModuleNotFoundError:
    MissionStageInput = Any


@dataclass(slots=True)
class HealthMonitorConfig:
    max_vision_age_s: float = 0.3
    max_drone_age_s: float = 0.3
    max_gimbal_age_s: float = 0.3


@dataclass(slots=True)
class HealthStatus:
    vision_fresh: bool
    drone_fresh: bool
    gimbal_fresh: bool
    fusion_ready: bool
    control_ready: bool
    target_ready: bool
    hold_reason: str


class HealthMonitor:
    def __init__(self, config: HealthMonitorConfig | None = None) -> None:
        self.config = config or HealthMonitorConfig()

    def update(self, inputs: MissionStageInput) -> HealthStatus:
        vision_fresh = inputs.vision_valid and self._age_fresh(
            inputs.vision_age_s,
            self.config.max_vision_age_s,
        )
        drone_fresh = inputs.drone_valid and self._age_fresh(
            inputs.drone_age_s,
            self.config.max_drone_age_s,
        )
        gimbal_fresh = inputs.gimbal_valid and self._age_fresh(
            inputs.gimbal_age_s,
            self.config.max_gimbal_age_s,
        )
        fusion_ready = bool(inputs.fused_valid and vision_fresh and drone_fresh)
        target_ready = bool(inputs.target_valid and inputs.target_locked)
        control_ready = bool(inputs.control_allowed and fusion_ready and target_ready)
        return HealthStatus(
            vision_fresh=vision_fresh,
            drone_fresh=drone_fresh,
            gimbal_fresh=gimbal_fresh,
            fusion_ready=fusion_ready,
            control_ready=control_ready,
            target_ready=target_ready,
            hold_reason=self._hold_reason(
                inputs,
                vision_fresh,
                drone_fresh,
                gimbal_fresh,
                fusion_ready,
                target_ready,
                control_ready,
            ),
        )

    def _hold_reason(
        self,
        inputs: MissionStageInput,
        vision_fresh: bool,
        drone_fresh: bool,
        gimbal_fresh: bool,
        fusion_ready: bool,
        target_ready: bool,
        control_ready: bool,
    ) -> str:
        if control_ready:
            return ""
        if not inputs.control_allowed:
            return "control_not_allowed"
        if not inputs.fused_valid:
            return "fusion_invalid"
        if not inputs.vision_valid:
            return "vision_invalid"
        if not vision_fresh:
            return "vision_stale"
        if not inputs.drone_valid:
            return "drone_invalid"
        if not drone_fresh:
            return "drone_stale"
        if not fusion_ready:
            return "fusion_not_ready"
        if not inputs.target_valid:
            return "no_target"
        if not inputs.target_locked:
            return "target_not_locked"
        if not target_ready:
            return "target_not_ready"
        if inputs.gimbal_valid and not gimbal_fresh:
            return "gimbal_stale"
        return "not_ready"

    @staticmethod
    def _age_fresh(age_s: float, max_age_s: float) -> bool:
        age_s = float(age_s)
        max_age_s = float(max_age_s)
        if not math.isfinite(age_s) or not math.isfinite(max_age_s):
            return False
        if max_age_s < 0.0:
            return False
        return age_s <= max_age_s
