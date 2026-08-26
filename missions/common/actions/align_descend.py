"""Visual BODY_NED alignment and descent Action.

This Action deliberately owns both its small PID loop and lifecycle.  It does
not select a target and it does not release payload; it only reaches a stable,
locked visual alignment at the requested height.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from contracts.effects import FlightCommand

from .base import ActionModule
from .result import ActionResult


@dataclass(slots=True)
class _Pid:
    kp: float
    ki: float
    kd: float
    limit: float
    integral: float = 0.0
    previous_error: float | None = None

    def step(self, error: float, dt_s: float) -> float:
        derivative = 0.0 if self.previous_error is None or dt_s <= 0.0 else (error - self.previous_error) / dt_s
        candidate_integral = self.integral + error * dt_s
        raw = self.kp * error + self.ki * candidate_integral + self.kd * derivative
        output = max(-self.limit, min(self.limit, raw))
        # Integrate only when it will not push further into saturation.
        if self.ki == 0.0 or output == raw or (output > 0.0 and error < 0.0) or (output < 0.0 and error > 0.0):
            self.integral = candidate_integral
        self.previous_error = error
        return output

    def reset(self) -> None:
        self.integral = 0.0
        self.previous_error = None


class AlignDescendAction(ActionModule):
    """Keep one locked YOLO target centred while descending in BODY_NED.

    ``field_yaw_deg`` is clockwise from FIELD +Y.  Every emitted velocity
    command contains the resulting north-referenced yaw; no yaw-rate command
    is generated.  Completion is possible only at ``target_altitude_m`` and
    within ``release_deadband_*``.  Timeout or loss of the selected lock fails
    with an explicit zero-velocity command.
    """

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        legacy = data.get("config") if isinstance(data.get("config"), dict) else {}
        self.target_track_id = self._optional_int(data.get("track_id"))
        self.target_altitude_m = self._positive(data.get("target_altitude_m", data.get("finish_altitude_m", legacy.get("min_altitude_m", 1.2))), "target_altitude_m")
        self.max_duration_s = self._positive(data.get("max_duration_s", 30.0), "max_duration_s")
        self.descend_speed_mps = self._non_negative(data.get("descend_speed_mps", legacy.get("descend_speed_mps", 0.2)), "descend_speed_mps")
        self.descent_deadband_ex = self._positive(data.get("descent_deadband_ex", legacy.get("max_ex_cam", 0.15)), "descent_deadband_ex")
        self.descent_deadband_ey = self._positive(data.get("descent_deadband_ey", legacy.get("max_ey_cam", 0.15)), "descent_deadband_ey")
        self.release_deadband_ex = self._positive(
            data.get("release_deadband_ex", data.get("finish_alignment_max_ex_cam", self.descent_deadband_ex)),
            "release_deadband_ex",
        )
        self.release_deadband_ey = self._positive(
            data.get("release_deadband_ey", data.get("finish_alignment_max_ey_cam", self.descent_deadband_ey)),
            "release_deadband_ey",
        )
        self.alignment_hold_s = self._non_negative(data.get("alignment_hold_s", 0.0), "alignment_hold_s")
        self.max_target_age_s = self._positive(data.get("max_target_age_s", 0.5), "max_target_age_s")
        self.priority = int(data.get("priority", 5))
        self.key = str(data.get("key") or "align_descend").strip() or "align_descend"

        max_vx = self._positive(data.get("max_vx_mps", legacy.get("max_vx_mps", 0.25)), "max_vx_mps")
        max_vy = self._positive(data.get("max_vy_mps", legacy.get("max_vy_mps", 0.25)), "max_vy_mps")
        # Camera y controls forward velocity; camera x controls right velocity.
        self.pid_forward = _Pid(
            self._non_negative(data.get("kp_forward", legacy.get("kp_vx", 0.3)), "kp_forward"),
            self._non_negative(data.get("ki_forward", 0.0), "ki_forward"),
            self._non_negative(data.get("kd_forward", 0.0), "kd_forward"), max_vx,
        )
        self.pid_right = _Pid(
            self._non_negative(data.get("kp_right", legacy.get("kp_vy", 0.3)), "kp_right"),
            self._non_negative(data.get("ki_right", 0.0), "ki_right"),
            self._non_negative(data.get("kd_right", 0.0), "kd_right"), max_vy,
        )
        self.vx_sign = self._signed(data.get("vx_sign", legacy.get("vx_sign", -1.0)), "vx_sign")
        self.vy_sign = self._signed(data.get("vy_sign", legacy.get("vy_sign", 1.0)), "vy_sign")
        self.field_yaw_deg = self._finite(data.get("field_yaw_deg", 0.0), "field_yaw_deg")
        self.desired_yaw_deg = self._optional_finite(data.get("desired_yaw_deg"))
        self.started_at = time.monotonic()
        self.last_update_at: float | None = None
        self.aligned_since: float | None = None
        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        data = context or {}
        yaw = self._desired_yaw_rad(data)
        if yaw is None:
            return self._terminal(False, "missing_fixed_yaw", yaw_rad=0.0)
        if self.stopped:
            return self._terminal(True, "stopped", yaw_rad=yaw)
        now = time.monotonic()
        if now - self.started_at >= self.max_duration_s:
            return self._terminal(False, "align_descend_timeout", yaw_rad=yaw)

        target, reason = self._locked_target(data, now)
        if target is None:
            return self._terminal(False, reason, yaw_rad=yaw)
        altitude = self._altitude(data)
        if altitude is None:
            return self._terminal(False, "altitude_unavailable", yaw_rad=yaw)
        if not self._control_allowed(data):
            return self._terminal(False, "control_not_allowed", yaw_rad=yaw)

        dt_s = 0.0 if self.last_update_at is None else min(0.25, max(0.0, now - self.last_update_at))
        self.last_update_at = now
        ex, ey = target["ex"], target["ey"]
        vx = self.vx_sign * self.pid_forward.step(ey, dt_s)
        vy = self.vy_sign * self.pid_right.step(ex, dt_s)
        within_descent = abs(ex) <= self.descent_deadband_ex and abs(ey) <= self.descent_deadband_ey
        within_release = abs(ex) <= self.release_deadband_ex and abs(ey) <= self.release_deadband_ey

        if altitude <= self.target_altitude_m:
            if within_release:
                self.aligned_since = now if self.aligned_since is None else self.aligned_since
                if now - self.aligned_since >= self.alignment_hold_s:
                    return self._terminal(True, "ready_to_release", yaw_rad=yaw, altitude_m=altitude, target=target)
            else:
                self.aligned_since = None
            vz = 0.0
            reason = "final_align"
        else:
            self.aligned_since = None
            vz = self.descend_speed_mps if within_descent else 0.0
            reason = "align_descending" if within_descent else "aligning"

        effect = self._command(vx, vy, vz, yaw)
        detail = self._detail(reason, target, altitude, yaw, vx, vy, vz, within_descent, within_release)
        return ActionResult(effects=(effect,), reason=reason, detail=detail)

    def stop(self) -> None:
        self.stopped = True
        self.pid_forward.reset()
        self.pid_right.reset()

    def reset(self) -> None:
        self.started = self.stopped = False
        self.target_track_id = None
        self.target_altitude_m = 1.2
        self.max_duration_s = 30.0
        self.descend_speed_mps = 0.2
        self.descent_deadband_ex = self.descent_deadband_ey = 0.15
        self.release_deadband_ex = self.release_deadband_ey = 0.10
        self.alignment_hold_s = 0.0
        self.max_target_age_s = 0.5
        self.priority, self.key = 5, "align_descend"
        self.field_yaw_deg, self.desired_yaw_deg = 0.0, None
        self.pid_forward = _Pid(0.3, 0.0, 0.0, 0.25)
        self.pid_right = _Pid(0.3, 0.0, 0.0, 0.25)
        self.vx_sign = self.vy_sign = 1.0
        self.started_at = 0.0
        self.last_update_at = self.aligned_since = None

    def _locked_target(self, data: dict[str, Any], now: float) -> tuple[dict[str, float] | None, str]:
        source = data.get("perception")
        source = source if isinstance(source, dict) else data
        if not bool(source.get("target_valid", False)):
            return None, "target_not_valid"
        if str(source.get("tracking_state", "")).lower() != "locked":
            return None, "target_not_locked"
        track_id = self._optional_int(source.get("track_id"))
        if track_id is None:
            return None, "target_track_id_missing"
        if self.target_track_id is not None and track_id != self.target_track_id:
            return None, "target_track_id_mismatch"
        # Only compare values explicitly declared monotonic with ``now``.
        # Detector ``timestamp`` is commonly wall-clock time (or device time),
        # so comparing it with monotonic time would reject every good target.
        timestamp = self._optional_finite(
            source.get("received_at_monotonic", source.get("published_at_monotonic"))
        )
        age_s = self._optional_finite(source.get("target_age_s"))
        if age_s is not None and age_s > self.max_target_age_s:
            return None, "target_stale"
        if timestamp is not None and now - timestamp > self.max_target_age_s:
            return None, "target_stale"
        ex, ey = self._optional_finite(source.get("ex")), self._optional_finite(source.get("ey"))
        if ex is None or ey is None:
            return None, "target_error_unavailable"
        return {"track_id": float(track_id), "ex": ex, "ey": ey}, "ok"

    def _desired_yaw_rad(self, data: dict[str, Any]) -> float | None:
        if self.desired_yaw_deg is not None:
            return self._normalize(math.radians(self.desired_yaw_deg))
        heading = self._optional_finite(data.get("field_heading_yaw_rad"))
        if heading is None:
            return None
        return self._normalize(heading + math.radians(self.field_yaw_deg))

    @staticmethod
    def _altitude(data: dict[str, Any]) -> float | None:
        drone = data.get("drone")
        source = drone if isinstance(drone, dict) else data
        for name in ("relative_altitude", "relative_altitude_m", "altitude_m"):
            value = AlignDescendAction._optional_finite(source.get(name))
            if value is not None and value >= 0.0:
                return value
        z = AlignDescendAction._optional_finite(source.get("local_z"))
        return -z if z is not None and z <= 0.0 else None

    @staticmethod
    def _control_allowed(data: dict[str, Any]) -> bool:
        drone = data.get("drone")
        source = drone if isinstance(drone, dict) else data
        return bool(source.get("connected", True)) and not bool(source.get("stale", False)) and bool(source.get("control_allowed", False))

    def _command(self, vx: float, vy: float, vz: float, yaw: float) -> FlightCommand:
        return FlightCommand(
            params={"valid": True, "active": True, "vx_cmd": vx, "vy_cmd": vy, "vz_cmd": vz,
                    "yaw_hold_rad": yaw},
            key=f"{self.key}_body", priority=self.priority, once=False,
        )

    def _terminal(self, done: bool, reason: str, *, yaw_rad: float, altitude_m: float | None = None, target: dict[str, float] | None = None) -> ActionResult:
        self.pid_forward.reset()
        self.pid_right.reset()
        detail = self._detail(reason, target, altitude_m, yaw_rad, 0.0, 0.0, 0.0, False, False)
        return ActionResult(effects=(self._command(0.0, 0.0, 0.0, yaw_rad),), done=done, failed=not done, reason=reason, detail=detail)

    def _detail(self, reason, target, altitude, yaw, vx, vy, vz, descent_ok, release_ok) -> dict[str, Any]:
        return {"state": reason, "target_track_id": None if target is None else int(target["track_id"]),
                "ex": None if target is None else target["ex"], "ey": None if target is None else target["ey"],
                "altitude_m": altitude, "target_altitude_m": self.target_altitude_m,
                "yaw_rad": yaw, "yaw_deg": math.degrees(yaw) % 360.0,
                "vx_forward_mps": vx, "vy_right_mps": vy, "vz_down_mps": vz,
                "within_descent_deadband": descent_ok, "within_release_deadband": release_ok}

    @staticmethod
    def _normalize(value: float) -> float:
        return math.atan2(math.sin(value), math.cos(value))

    @staticmethod
    def _optional_finite(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @classmethod
    def _finite(cls, value: Any, name: str) -> float:
        result = cls._optional_finite(value)
        if result is None:
            raise ValueError(f"{name} must be finite")
        return result

    @classmethod
    def _positive(cls, value: Any, name: str) -> float:
        result = cls._finite(value, name)
        if result <= 0.0:
            raise ValueError(f"{name} must be > 0")
        return result

    @classmethod
    def _non_negative(cls, value: Any, name: str) -> float:
        result = cls._finite(value, name)
        if result < 0.0:
            raise ValueError(f"{name} must be >= 0")
        return result

    @classmethod
    def _signed(cls, value: Any, name: str) -> float:
        result = cls._finite(value, name)
        if result == 0.0:
            raise ValueError(f"{name} must not be 0")
        return result

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None
