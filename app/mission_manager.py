from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from app.health_monitor import HealthStatus
from missions.common.control.types import MissionStageInput


class MissionMode(str, Enum):
    IDLE = "IDLE"
    CORRIDOR_FOLLOW = "CORRIDOR_FOLLOW"
    APPROACH_TRACK = "APPROACH_TRACK"
    OVERHEAD_HOLD = "OVERHEAD_HOLD"
    RTL = "RTL"


@dataclass(slots=True)
class MissionManagerConfig:
    initial_mode: str = MissionMode.APPROACH_TRACK.value
    overhead_entry_target_size_thresh: float = 0.30
    overhead_entry_pitch_rad: float = -1.5707963267948966
    overhead_entry_pitch_tol_rad: float = 0.20
    overhead_entry_yaw_tol_rad: float = 0.15
    overhead_entry_hold_s: float = 0.5
    overhead_exit_target_size_drop: float = 0.06
    auto_switch_enabled: bool = True


@dataclass(slots=True)
class MissionState:
    active_mode: str
    previous_mode: str | None = None
    hold_reason: str = ""
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class MissionManager:
    # TODO: Keep this compatibility state machine until callers migrate fully to
    # missions.visual_tracking.VisualTrackingMission.
    config: MissionManagerConfig = field(default_factory=MissionManagerConfig)
    _active_mode: str = field(init=False)
    _overhead_entry_since: float | None = field(init=False, default=None)
    _overhead_entry_size: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._active_mode = self._mode_value(self.config.initial_mode)

    def reset(self) -> None:
        self._active_mode = self._mode_value(self.config.initial_mode)
        self._overhead_entry_since = None
        self._overhead_entry_size = None

    def update(self, inputs: MissionStageInput, health: HealthStatus) -> MissionState:
        previous = self._active_mode
        hold_reason = ""
        if not health.fusion_ready:
            self._active_mode = MissionMode.IDLE.value
            self._overhead_entry_since = None
            hold_reason = health.hold_reason
        elif self._active_mode == MissionMode.IDLE.value:
            if health.control_ready:
                self._active_mode = MissionMode.APPROACH_TRACK.value
        elif self.config.auto_switch_enabled:
            if self._active_mode == MissionMode.OVERHEAD_HOLD.value:
                if self._should_exit_overhead(inputs, health):
                    self._active_mode = MissionMode.APPROACH_TRACK.value
                    self._overhead_entry_since = None
                    self._overhead_entry_size = None
                    hold_reason = "exit_overhead"
            elif self._active_mode == MissionMode.APPROACH_TRACK.value:
                if self._entry_conditions_met(inputs, health):
                    if self._overhead_entry_since is None:
                        self._overhead_entry_since = float(inputs.timestamp)
                    entry_elapsed = float(inputs.timestamp) - self._overhead_entry_since
                    if entry_elapsed >= self.config.overhead_entry_hold_s:
                        self._active_mode = MissionMode.OVERHEAD_HOLD.value
                        self._overhead_entry_size = float(inputs.target_size)
                        self._overhead_entry_since = None
                else:
                    self._overhead_entry_since = None

        return MissionState(
            active_mode=str(self._active_mode),
            previous_mode=str(previous) if previous != self._active_mode else None,
            hold_reason=hold_reason,
            detail={
                "overhead_entry_since": self._overhead_entry_since,
                "overhead_entry_size": self._overhead_entry_size,
            },
        )

    def force_mode(self, mode_name: str) -> MissionState:
        previous = self._active_mode
        self._active_mode = self._mode_value(mode_name)
        self._overhead_entry_since = None
        return MissionState(
            active_mode=self._active_mode,
            previous_mode=str(previous) if previous != self._active_mode else None,
            hold_reason="forced",
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
    def _mode_value(mode: str | MissionMode) -> str:
        if isinstance(mode, MissionMode):
            return mode.value
        return str(mode)
