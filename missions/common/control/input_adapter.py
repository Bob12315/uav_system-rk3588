from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable

from missions.common.control.types import MissionStageInput
from fusion.models import FusedState


@dataclass(slots=True)
class InputAdapterConfig:
    dt_default: float = 0.02
    dt_min: float = 0.001
    dt_max: float = 0.5
    stable_hold_s: float = 0.3
    age_invalid_value: float = float("inf")
    ex_cam_tau_s: float = 0.08
    ey_cam_tau_s: float = 0.08
    ex_body_tau_s: float = 0.08
    ey_body_tau_s: float = 0.08
    gimbal_yaw_tau_s: float = 0.10
    gimbal_pitch_tau_s: float = 0.10
    target_size_tau_s: float = 0.12


@dataclass(slots=True)
class _FirstOrderLowPass:
    tau_s: float
    value: float = 0.0
    initialized: bool = False

    def reset(self) -> None:
        self.value = 0.0
        self.initialized = False

    def update(self, sample: float, dt: float) -> float:
        if not math.isfinite(sample):
            return self.value
        if not self.initialized:
            self.value = sample
            self.initialized = True
            return self.value
        if self.tau_s <= 0.0:
            self.value = sample
            return self.value
        alpha = dt / (self.tau_s + dt)
        alpha = min(1.0, max(0.0, alpha))
        self.value += alpha * (sample - self.value)
        return self.value


@dataclass(slots=True)
class StageInputAdapter:
    config: InputAdapterConfig = field(default_factory=InputAdapterConfig)
    _time_fn: Callable[[], float] = time.time
    _last_fused_timestamp: float | None = field(init=False, default=None)
    _last_track_id: int | None = field(init=False, default=None)
    _stable_track_id: int | None = field(init=False, default=None)
    _stable_track_since: float | None = field(init=False, default=None)
    _ex_cam_filter: _FirstOrderLowPass = field(init=False)
    _ey_cam_filter: _FirstOrderLowPass = field(init=False)
    _ex_body_filter: _FirstOrderLowPass = field(init=False)
    _ey_body_filter: _FirstOrderLowPass = field(init=False)
    _gimbal_yaw_filter: _FirstOrderLowPass = field(init=False)
    _gimbal_pitch_filter: _FirstOrderLowPass = field(init=False)
    _target_size_filter: _FirstOrderLowPass = field(init=False)

    def __post_init__(self) -> None:
        self._ex_cam_filter = _FirstOrderLowPass(self.config.ex_cam_tau_s)
        self._ey_cam_filter = _FirstOrderLowPass(self.config.ey_cam_tau_s)
        self._ex_body_filter = _FirstOrderLowPass(self.config.ex_body_tau_s)
        self._ey_body_filter = _FirstOrderLowPass(self.config.ey_body_tau_s)
        self._gimbal_yaw_filter = _FirstOrderLowPass(self.config.gimbal_yaw_tau_s)
        self._gimbal_pitch_filter = _FirstOrderLowPass(self.config.gimbal_pitch_tau_s)
        self._target_size_filter = _FirstOrderLowPass(self.config.target_size_tau_s)

    def reset(self) -> None:
        self._last_fused_timestamp = None
        self._last_track_id = None
        self._stable_track_id = None
        self._stable_track_since = None
        self._ex_cam_filter.reset()
        self._ey_cam_filter.reset()
        self._ex_body_filter.reset()
        self._ey_body_filter.reset()
        self._gimbal_yaw_filter.reset()
        self._gimbal_pitch_filter.reset()
        self._target_size_filter.reset()

    def adapt(self, fused: FusedState) -> MissionStageInput:
        now = self._time_fn()
        dt = self._compute_dt(fused.timestamp)
        track_id = self._normalize_track_id(fused.track_id)
        track_switched = self._compute_track_switched(track_id)
        target_size_raw, target_size_valid = self._extract_target_size(fused)
        target_stable = self._compute_target_stable(
            timestamp=fused.timestamp,
            track_id=track_id,
            target_valid=bool(fused.target_valid),
            target_locked=bool(fused.target_locked),
        )

        ex_cam = self._ex_cam_filter.update(float(fused.ex_cam), dt)
        ey_cam = self._ey_cam_filter.update(float(fused.ey_cam), dt)
        ex_body = self._ex_body_filter.update(float(fused.ex_body), dt)
        ey_body = self._ey_body_filter.update(float(fused.ey_body), dt)
        gimbal_yaw = self._gimbal_yaw_filter.update(float(fused.gimbal_yaw), dt)
        gimbal_pitch = self._gimbal_pitch_filter.update(float(fused.gimbal_pitch), dt)
        if target_size_valid:
            target_size = self._target_size_filter.update(target_size_raw, dt)
        else:
            target_size = 0.0

        stage_input = MissionStageInput(
            timestamp=float(fused.timestamp),
            dt=dt,
            fused_valid=bool(fused.fusion_valid),
            target_valid=bool(fused.target_valid),
            target_locked=bool(fused.target_locked),
            vision_valid=bool(fused.vision_valid),
            drone_valid=bool(fused.drone_valid),
            gimbal_valid=bool(fused.gimbal_valid),
            control_allowed=bool(fused.control_allowed),
            track_id=track_id,
            track_switched=track_switched,
            target_stable=target_stable,
            tracking_state=str(fused.tracking_state),
            ex_cam=ex_cam,
            ey_cam=ey_cam,
            ex_body=ex_body,
            ey_body=ey_body,
            gimbal_yaw=gimbal_yaw,
            gimbal_pitch=gimbal_pitch,
            yaw_rate=float(fused.yaw_rate),
            target_size=target_size,
            target_size_valid=target_size_valid,
            fusion_age_s=self._compute_age(now, fused.timestamp),
            vision_age_s=self._compute_age(now, fused.perception_timestamp),
            drone_age_s=self._compute_age(now, fused.drone_timestamp),
            gimbal_age_s=self._compute_age(now, fused.gimbal_timestamp),
        )
        self._last_track_id = track_id
        return stage_input

    def _compute_dt(self, timestamp: float) -> float:
        timestamp = float(timestamp)
        if not math.isfinite(timestamp) or timestamp <= 0.0:
            self._last_fused_timestamp = None
            return self.config.dt_default
        if self._last_fused_timestamp is None:
            self._last_fused_timestamp = timestamp
            return self.config.dt_default
        raw_dt = timestamp - self._last_fused_timestamp
        self._last_fused_timestamp = timestamp
        if not math.isfinite(raw_dt) or raw_dt <= 0.0:
            return self.config.dt_default
        return min(self.config.dt_max, max(self.config.dt_min, raw_dt))

    def _compute_age(self, now: float, source_timestamp: float) -> float:
        source_timestamp = float(source_timestamp)
        if not math.isfinite(source_timestamp) or source_timestamp <= 0.0:
            return self.config.age_invalid_value
        return max(0.0, now - source_timestamp)

    def _compute_track_switched(self, track_id: int | None) -> bool:
        if self._last_track_id is None or track_id is None:
            return False
        return self._last_track_id != track_id

    def _compute_target_stable(
        self,
        timestamp: float,
        track_id: int | None,
        target_valid: bool,
        target_locked: bool,
    ) -> bool:
        if not target_valid or not target_locked or track_id is None:
            self._stable_track_id = None
            self._stable_track_since = None
            return False
        timestamp = float(timestamp)
        if not math.isfinite(timestamp) or timestamp <= 0.0:
            timestamp = self._time_fn()
        if self._stable_track_id != track_id:
            self._stable_track_id = track_id
            self._stable_track_since = timestamp
            return False
        if self._stable_track_since is None:
            self._stable_track_since = timestamp
            return False
        return (timestamp - self._stable_track_since) > self.config.stable_hold_s

    def _extract_target_size(self, fused: FusedState) -> tuple[float, bool]:
        target_size = self._valid_positive(getattr(fused, "target_size", None))
        if target_size is not None:
            return target_size, True

        bbox_h = self._valid_positive(getattr(fused, "bbox_h", None))
        if bbox_h is not None:
            image_height = self._valid_positive(getattr(fused, "image_height", None))
            if image_height is not None:
                return bbox_h / image_height, True
            return bbox_h, True
        bbox_area = self._valid_positive(getattr(fused, "bbox_area", None))
        if bbox_area is not None:
            image_width = self._valid_positive(getattr(fused, "image_width", None))
            image_height = self._valid_positive(getattr(fused, "image_height", None))
            if image_width is not None and image_height is not None:
                return math.sqrt(bbox_area / (image_width * image_height)), True
            return math.sqrt(bbox_area), True
        return 0.0, False

    @staticmethod
    def _normalize_track_id(track_id: int | None) -> int | None:
        if track_id is None:
            return None
        try:
            value = int(track_id)
        except (TypeError, ValueError):
            return None
        if value < 0:
            return None
        return value

    @staticmethod
    def _valid_positive(value: float | None) -> float | None:
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value) or value <= 0.0:
            return None
        return value
