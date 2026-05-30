from __future__ import annotations

from telemetry_link.models import DroneState, GimbalState

from .models import FusedState, FusionConfig
from .rules import build_fused_state, normalize_perception_target


class FusionManager:
    def __init__(self, config: FusionConfig | None = None) -> None:
        self.config = config or FusionConfig()

    def update(self, perception_target, drone_state: DroneState, gimbal_state: GimbalState) -> FusedState:
        normalized_target = normalize_perception_target(perception_target)
        return build_fused_state(
            perception_target=normalized_target,
            drone_state=drone_state,
            gimbal_state=gimbal_state,
            require_gimbal_feedback=self.config.require_gimbal_feedback,
        )
