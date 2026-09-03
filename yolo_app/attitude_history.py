from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttitudeSample:
    publisher_session_id: str
    link_session_id: str
    source: str
    sequence: int
    received_at_monotonic_ns: int
    roll_rad: float
    pitch_rad: float
    yaw_rad: float
    roll_rate_rad_s: float
    pitch_rate_rad_s: float
    yaw_rate_rad_s: float

    @property
    def session_key(self) -> tuple[str, str, str]:
        return self.publisher_session_id, self.link_session_id, self.source


@dataclass(frozen=True, slots=True)
class AttitudeMatch:
    valid: bool
    reason: str
    session_key: tuple[str, str, str] | None = None
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    yaw_rad: float = 0.0
    quaternion_wxyz: tuple[float, float, float, float] | None = None
    before_sequence: int | None = None
    after_sequence: int | None = None
    attitude_match_ms: float | None = None
    observed_rate_hz: float | None = None


class AttitudeHistory:
    """Thread-safe, session-scoped and time-bounded attitude ring."""

    def __init__(self, *, max_samples: int = 128, history_ms: float = 1500.0) -> None:
        if max_samples < 2 or history_ms <= 0.0:
            raise ValueError("attitude history bounds are invalid")
        self.max_samples = int(max_samples)
        self.history_ns = int(history_ms * 1_000_000.0)
        self._samples: deque[AttitudeSample] = deque(maxlen=self.max_samples)
        self._session_key: tuple[str, str, str] | None = None
        self._condition = threading.Condition()

    @property
    def session_key(self) -> tuple[str, str, str] | None:
        with self._condition:
            return self._session_key

    def __len__(self) -> int:
        with self._condition:
            return len(self._samples)

    def clear(self) -> None:
        with self._condition:
            self._samples.clear()
            self._session_key = None
            self._condition.notify_all()

    def append(self, sample: AttitudeSample) -> bool:
        values = (
            sample.roll_rad,
            sample.pitch_rad,
            sample.yaw_rad,
            sample.roll_rate_rad_s,
            sample.pitch_rate_rad_s,
            sample.yaw_rate_rad_s,
        )
        if (
            sample.sequence < 0
            or sample.received_at_monotonic_ns < 0
            or not all(math.isfinite(value) for value in values)
        ):
            return False
        with self._condition:
            if sample.session_key != self._session_key:
                self._samples.clear()
                self._session_key = sample.session_key
            if self._samples and (
                sample.sequence <= self._samples[-1].sequence
                or sample.received_at_monotonic_ns <= self._samples[-1].received_at_monotonic_ns
            ):
                return False
            self._samples.append(sample)
            newest_ns = sample.received_at_monotonic_ns
            while self._samples and newest_ns - self._samples[0].received_at_monotonic_ns > self.history_ns:
                self._samples.popleft()
            self._condition.notify_all()
            return True

    def lookup(
        self,
        frame_monotonic_ns: int,
        *,
        max_sample_distance_ms: float,
        max_bracket_span_ms: float,
        future_wait_ms: float = 0.0,
        min_rate_hz: float = 0.0,
        rate_window_ms: float = 1000.0,
        min_rate_samples: int = 2,
    ) -> AttitudeMatch:
        if frame_monotonic_ns <= 0:
            return AttitudeMatch(False, "invalid_frame_timestamp")
        max_distance_ns = int(max_sample_distance_ms * 1_000_000.0)
        max_span_ns = int(max_bracket_span_ms * 1_000_000.0)
        deadline_ns = time.monotonic_ns() + max(0, int(future_wait_ms * 1_000_000.0))
        with self._condition:
            while True:
                match, may_wait = self._lookup_locked(
                    frame_monotonic_ns,
                    max_distance_ns=max_distance_ns,
                    max_span_ns=max_span_ns,
                    min_rate_hz=min_rate_hz,
                    rate_window_ns=int(rate_window_ms * 1_000_000.0),
                    min_rate_samples=min_rate_samples,
                )
                if match.valid or not may_wait:
                    return match
                remaining_ns = deadline_ns - time.monotonic_ns()
                if remaining_ns <= 0:
                    return match
                self._condition.wait(remaining_ns / 1_000_000_000.0)

    def _lookup_locked(
        self,
        frame_ns: int,
        *,
        max_distance_ns: int,
        max_span_ns: int,
        min_rate_hz: float,
        rate_window_ns: int,
        min_rate_samples: int,
    ) -> tuple[AttitudeMatch, bool]:
        if not self._samples:
            return AttitudeMatch(False, "attitude_history_empty", self._session_key), True
        if frame_ns < self._samples[0].received_at_monotonic_ns:
            return AttitudeMatch(False, "frame_before_attitude_history", self._session_key), False
        before: AttitudeSample | None = None
        after: AttitudeSample | None = None
        for sample in self._samples:
            if sample.received_at_monotonic_ns <= frame_ns:
                before = sample
            if sample.received_at_monotonic_ns >= frame_ns:
                after = sample
                break
        if before is None:
            return AttitudeMatch(False, "missing_attitude_before", self._session_key), False
        if after is None:
            return AttitudeMatch(False, "missing_attitude_after", self._session_key), True
        before_distance = frame_ns - before.received_at_monotonic_ns
        after_distance = after.received_at_monotonic_ns - frame_ns
        span = after.received_at_monotonic_ns - before.received_at_monotonic_ns
        if before_distance > max_distance_ns or after_distance > max_distance_ns:
            return AttitudeMatch(False, "attitude_sample_too_far", self._session_key), False
        if span > max_span_ns:
            return AttitudeMatch(False, "attitude_bracket_too_wide", self._session_key), False

        rate_samples = [
            sample
            for sample in self._samples
            if sample.received_at_monotonic_ns <= after.received_at_monotonic_ns
            and after.received_at_monotonic_ns - sample.received_at_monotonic_ns <= rate_window_ns
        ]
        observed_rate_hz: float | None = None
        if len(rate_samples) >= 2:
            rate_span_ns = (
                rate_samples[-1].received_at_monotonic_ns
                - rate_samples[0].received_at_monotonic_ns
            )
            if rate_span_ns > 0:
                observed_rate_hz = (len(rate_samples) - 1) * 1_000_000_000.0 / rate_span_ns
        if min_rate_hz > 0.0:
            if len(rate_samples) < min_rate_samples or observed_rate_hz is None:
                return AttitudeMatch(
                    False, "attitude_rate_warming_up", self._session_key,
                    observed_rate_hz=observed_rate_hz,
                ), True
            if observed_rate_hz < min_rate_hz:
                return AttitudeMatch(
                    False, "attitude_rate_insufficient", self._session_key,
                    observed_rate_hz=observed_rate_hz,
                ), False

        q0 = quaternion_from_euler_zyx(before.roll_rad, before.pitch_rad, before.yaw_rad)
        if before is after or span == 0:
            q = q0
        else:
            q1 = quaternion_from_euler_zyx(after.roll_rad, after.pitch_rad, after.yaw_rad)
            q = quaternion_slerp(q0, q1, before_distance / span)
        roll, pitch, yaw = euler_zyx_from_quaternion(q)
        return AttitudeMatch(
            True,
            "ok",
            self._session_key,
            roll,
            pitch,
            yaw,
            q,
            before.sequence,
            after.sequence,
            max(before_distance, after_distance) / 1_000_000.0,
            observed_rate_hz,
        ), False


def quaternion_from_euler_zyx(
    roll_rad: float, pitch_rad: float, yaw_rad: float
) -> tuple[float, float, float, float]:
    """Return the active Body-FRD to NED quaternion for ZYX yaw/pitch/roll."""
    cr, sr = math.cos(roll_rad / 2.0), math.sin(roll_rad / 2.0)
    cp, sp = math.cos(pitch_rad / 2.0), math.sin(pitch_rad / 2.0)
    cy, sy = math.cos(yaw_rad / 2.0), math.sin(yaw_rad / 2.0)
    return _normalize_quaternion((
        cy * cp * cr + sy * sp * sr,
        cy * cp * sr - sy * sp * cr,
        sy * cp * sr + cy * sp * cr,
        sy * cp * cr - cy * sp * sr,
    ))


def quaternion_slerp(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    fraction: float,
) -> tuple[float, float, float, float]:
    q0 = _normalize_quaternion(first)
    q1 = _normalize_quaternion(second)
    dot = sum(a * b for a, b in zip(q0, q1))
    if dot < 0.0:
        q1 = tuple(-value for value in q1)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    t = max(0.0, min(1.0, float(fraction)))
    if dot > 0.9995:
        return _normalize_quaternion(tuple(a + t * (b - a) for a, b in zip(q0, q1)))
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    a = math.sin((1.0 - t) * theta) / sin_theta
    b = math.sin(t * theta) / sin_theta
    return _normalize_quaternion(tuple(a * x + b * y for x, y in zip(q0, q1)))


def euler_zyx_from_quaternion(
    quaternion: tuple[float, float, float, float]
) -> tuple[float, float, float]:
    w, x, y, z = _normalize_quaternion(quaternion)
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    sin_pitch = 2.0 * (w * y - z * x)
    pitch = math.asin(max(-1.0, min(1.0, sin_pitch)))
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return roll, pitch, yaw


def _normalize_quaternion(
    quaternion: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    norm = math.sqrt(sum(value * value for value in quaternion))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError("quaternion norm is invalid")
    return tuple(value / norm for value in quaternion)
