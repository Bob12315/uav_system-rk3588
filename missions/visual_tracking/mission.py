from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.health_monitor import HealthStatus
from missions.common.control.types import MissionStageInput
from missions.base import MissionContext, MissionOutput


@dataclass(slots=True)
class VisualTrackingMissionConfig:
    initial_mode: str = "APPROACH_TRACK"
    overhead_entry_target_size_thresh: float = 0.30
    overhead_entry_pitch_rad: float = -1.5707963267948966
    overhead_entry_pitch_tol_rad: float = 0.20
    overhead_entry_yaw_tol_rad: float = 0.15
    overhead_entry_hold_s: float = 0.5
    overhead_exit_target_size_drop: float = 0.06
    auto_switch_enabled: bool = True


@dataclass(slots=True)
class VisualTrackingMission:
    config: VisualTrackingMissionConfig = field(default_factory=VisualTrackingMissionConfig)

    name: str = "visual_tracking"
    _active_mode: str = field(init=False)
    _overhead_entry_since: float | None = field(init=False, default=None)
    _overhead_entry_size: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._active_mode = self._mode_value(self.config.initial_mode)

    def reset(self) -> None:
        self._active_mode = self._mode_value(self.config.initial_mode)
        self._overhead_entry_since = None
        self._overhead_entry_size = None

    def set_stage(self, stage: str) -> None:
        normalized = self._mode_value(stage).strip().upper()
        if normalized not in {"APPROACH_TRACK", "OVERHEAD_HOLD", "CORRIDOR_FOLLOW", "IDLE"}:
            raise ValueError("visual_tracking stage must be APPROACH_TRACK, OVERHEAD_HOLD, CORRIDOR_FOLLOW, or IDLE")
        self._active_mode = normalized
        self._overhead_entry_since = None
        self._overhead_entry_size = None

    def update(self, context: MissionContext) -> MissionOutput:
        inputs = context.inputs
        health = context.health
        previous = self._active_mode
        hold_reason = ""

        if not health.fusion_ready:
            self._active_mode = "IDLE"
            self._overhead_entry_since = None
            hold_reason = health.hold_reason
        elif self._active_mode == "IDLE":
            if health.control_ready:
                self._active_mode = "APPROACH_TRACK"
        elif self.config.auto_switch_enabled:
            if self._active_mode == "OVERHEAD_HOLD":
                if self._should_exit_overhead(inputs, health):
                    self._active_mode = "APPROACH_TRACK"
                    self._overhead_entry_since = None
                    self._overhead_entry_size = None
                    hold_reason = "exit_overhead"
            elif self._active_mode == "APPROACH_TRACK":
                if self._entry_conditions_met(inputs, health):
                    if self._overhead_entry_since is None:
                        self._overhead_entry_since = float(inputs.timestamp)
                    entry_elapsed = float(inputs.timestamp) - self._overhead_entry_since
                    if entry_elapsed >= self.config.overhead_entry_hold_s:
                        self._active_mode = "OVERHEAD_HOLD"
                        self._overhead_entry_size = float(inputs.target_size)
                        self._overhead_entry_since = None
                else:
                    self._overhead_entry_since = None

        return MissionOutput(
            active_mode=str(self._active_mode),
            stage=str(self._active_mode),
            previous_stage=str(previous) if previous != self._active_mode else None,
            hold_reason=hold_reason,
            detail={
                "overhead_entry_since": self._overhead_entry_since,
                "overhead_entry_size": self._overhead_entry_size,
            },
        )

    def _entry_conditions_met(self, inputs: MissionStageInput, health: HealthStatus) -> bool:
        if not health.control_ready:
            return False
        if not inputs.target_stable or not inputs.target_locked:
            return False
        if inputs.track_switched:
            return False
        if not health.vision_fresh or not health.drone_fresh or not health.gimbal_fresh:
            return False
        if (
            not inputs.target_size_valid
            or float(inputs.target_size) <= self.config.overhead_entry_target_size_thresh
        ):
            return False
        if not self._pitch_near_downward(inputs):
            return False
        if not self._yaw_aligned_for_overhead(inputs):
            return False
        return True

    def _should_exit_overhead(self, inputs: MissionStageInput, health: HealthStatus) -> bool:
        if not health.fusion_ready:
            return True
        if not inputs.target_valid or not inputs.target_locked:
            return True
        if inputs.track_switched:
            return True
        if not health.vision_fresh or not health.gimbal_fresh:
            return True
        if not inputs.target_size_valid:
            return True
        entry_size = self._overhead_entry_size
        if entry_size is not None:
            if float(inputs.target_size) < (entry_size - self.config.overhead_exit_target_size_drop):
                return True
        return False

    def _pitch_near_downward(self, inputs: MissionStageInput) -> bool:
        pitch = float(inputs.gimbal_pitch)
        if not math.isfinite(pitch):
            return False
        return abs(pitch - self.config.overhead_entry_pitch_rad) <= self.config.overhead_entry_pitch_tol_rad

    def _yaw_aligned_for_overhead(self, inputs: MissionStageInput) -> bool:
        yaw = float(inputs.gimbal_yaw)
        if not math.isfinite(yaw):
            return False
        return abs(yaw) <= self.config.overhead_entry_yaw_tol_rad

    @staticmethod
    def _mode_value(mode: str) -> str:
        return str(mode)
