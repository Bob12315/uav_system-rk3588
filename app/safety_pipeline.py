from __future__ import annotations

import copy
import math
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from app.run_authorization import RunAuthorization
from app.safety_config import SafetyConfig, load_safety_config


DecisionStatus = Literal["allowed", "rejected", "clamped", "stop_emitted"]


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    status: DecisionStatus
    reason_code: str
    original_request: dict[str, object]
    effective_request: dict[str, object] | None
    run_id: str | None
    action: str | None
    source: str | None
    evaluated_at_monotonic: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ContinuousCommandGuard:
    """Independent deadman for the latest accepted continuous request."""

    def __init__(
        self,
        *,
        deadman_s: float,
        poll_s: float,
        monotonic: Callable[[], float] = time.monotonic,
        on_stop: Callable[[SafetyDecision], None] | None = None,
    ) -> None:
        self.deadman_s = deadman_s
        self.poll_s = poll_s
        self._monotonic = monotonic
        self._on_stop = on_stop
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._active: dict[str, object] | None = None

    def refresh(
        self,
        *,
        link_manager: object,
        authorization: RunAuthorization,
        action_name: str,
        source: str,
        request: dict[str, object],
    ) -> None:
        with self._lock:
            self._active = {
                "link_manager": link_manager,
                "authorization": authorization,
                "action_name": action_name,
                "source": source,
                "request": copy.deepcopy(request),
                "last_refresh": self._monotonic(),
            }
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="ActionContinuousDeadman",
                    daemon=True,
                )
                self._thread.start()
        self._wake.set()

    def stop(self, reason_code: str, *, emit: bool = True) -> SafetyDecision | None:
        with self._lock:
            active = self._active
            self._active = None
        if active is None:
            return None
        decision = self._emit_stop(active, reason_code) if emit else self._decision(active, reason_code)
        if self._on_stop is not None:
            self._on_stop(decision)
        return decision

    def close(self) -> None:
        self._shutdown.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._shutdown.is_set():
            self._wake.wait(self.poll_s)
            self._wake.clear()
            with self._lock:
                active = dict(self._active) if self._active is not None else None
            if active is None:
                continue
            reason = self._invalid_reason(active)
            if reason is None:
                continue
            with self._lock:
                if self._active is None or self._active.get("last_refresh") != active.get("last_refresh"):
                    continue
                self._active = None
            decision = self._emit_stop(active, reason)
            if self._on_stop is not None:
                self._on_stop(decision)

    def _invalid_reason(self, active: dict[str, object]) -> str | None:
        if self._monotonic() - float(active["last_refresh"]) > self.deadman_s:
            return "continuous_deadman_expired"
        manager = active["link_manager"]
        get_source = getattr(manager, "get_active_source", None)
        if callable(get_source) and get_source() != active["source"]:
            return "continuous_source_changed"
        get_state = getattr(manager, "get_latest_drone_state", None)
        if callable(get_state):
            state = get_state()
            if not bool(getattr(state, "connected", False)):
                return "continuous_telemetry_disconnected"
            if bool(getattr(state, "stale", True)):
                return "continuous_telemetry_stale"
            if not bool(getattr(state, "control_allowed", False)):
                return "continuous_control_not_allowed"
        return None

    def _emit_stop(self, active: dict[str, object], reason_code: str) -> SafetyDecision:
        manager = active["link_manager"]
        stop = getattr(manager, "stop_body_velocity_and_clear", None)
        if callable(stop):
            stop()
        clear_nav = getattr(manager, "clear_pending_local_position_actions", None)
        if callable(clear_nav):
            clear_nav()
        return self._decision(active, reason_code)

    def _decision(self, active: dict[str, object], reason_code: str) -> SafetyDecision:
        authorization = active["authorization"]
        assert isinstance(authorization, RunAuthorization)
        return SafetyDecision(
            status="stop_emitted",
            reason_code=reason_code,
            original_request=copy.deepcopy(active["request"]),
            effective_request=None,
            run_id=authorization.run_id,
            action=str(active["action_name"]),
            source=str(active["source"]),
            evaluated_at_monotonic=self._monotonic(),
        )


class ActionSafetyPipeline:
    def __init__(
        self,
        config: SafetyConfig | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        on_decision: Callable[[SafetyDecision], None] | None = None,
    ) -> None:
        self.config = config or load_safety_config()
        self._monotonic = monotonic
        self._on_decision = on_decision
        self._servo_keys: set[tuple[str, str]] = set()
        self.continuous_guard = ContinuousCommandGuard(
            deadman_s=self.config.continuous_deadman_s,
            poll_s=self.config.watchdog_poll_s,
            monotonic=monotonic,
            on_stop=on_decision,
        )

    def evaluate(
        self,
        request: dict[str, object],
        *,
        action_name: str | None,
        source: str,
        authorization: RunAuthorization | None,
        link_manager: object | None,
    ) -> SafetyDecision:
        now = self._monotonic()
        original = copy.deepcopy(request)
        action_type = str(request.get("action_type") or "")
        if authorization is None:
            return self._reject("run_not_authorized", original, action_name, source, None, now)
        if not authorization.permits(action_name, source):
            reason = "run_source_mismatch" if source != authorization.target_source else "run_scope_mismatch"
            return self._reject(reason, original, action_name, source, authorization, now)
        if source not in self.config.enabled_sources and source != "test":
            return self._reject("source_not_enabled", original, action_name, source, authorization, now)
        generated = request.get("generated_at_monotonic")
        if not self._number(generated):
            return self._reject("invalid_generated_at_monotonic", original, action_name, source, authorization, now)
        if now - float(generated) > self.config.request_ttl_s:
            return self._reject("request_expired", original, action_name, source, authorization, now)
        if float(generated) > now + 0.001:
            return self._reject("request_timestamp_in_future", original, action_name, source, authorization, now)

        effective = copy.deepcopy(request)
        params = effective.get("params")
        if not isinstance(params, dict):
            return self._reject("invalid_params", original, action_name, source, authorization, now)

        reason = self._telemetry_reason(action_type, source, link_manager)
        if reason is not None:
            return self._reject(reason, original, action_name, source, authorization, now)

        validator = getattr(self, f"_validate_{action_type}", None)
        if not callable(validator):
            return self._reject("unknown_request_type", original, action_name, source, authorization, now)
        try:
            changed, reason = validator(
                effective,
                action_name=action_name,
                link_manager=link_manager,
                source=source,
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return self._reject("invalid_request_payload", original, action_name, source, authorization, now)
        if reason is not None:
            return self._reject(reason, original, action_name, source, authorization, now)

        decision = SafetyDecision(
            status="clamped" if changed else "allowed",
            reason_code="request_clamped_to_safety_envelope" if changed else "request_allowed",
            original_request=original,
            effective_request=effective,
            run_id=authorization.run_id,
            action=action_name,
            source=source,
            evaluated_at_monotonic=now,
        )
        self._record(decision)
        return decision

    def arm_continuous(
        self,
        *,
        request: dict[str, object],
        action_name: str,
        source: str,
        authorization: RunAuthorization,
        link_manager: object,
    ) -> None:
        self.continuous_guard.refresh(
            link_manager=link_manager,
            authorization=authorization,
            action_name=action_name,
            source=source,
            request=request,
        )

    def stop_continuous(self, reason_code: str, *, emit: bool = True) -> SafetyDecision | None:
        return self.continuous_guard.stop(reason_code, emit=emit)

    def reset_run(self, run_id: str | None = None) -> None:
        if run_id is None:
            self._servo_keys.clear()
        else:
            self._servo_keys = {item for item in self._servo_keys if item[0] != run_id}

    def _telemetry_reason(self, action_type: str, source: str, manager: object | None) -> str | None:
        if action_type == "yolo_lock_target":
            return None
        if manager is None:
            return "telemetry_not_connected"
        if source == "test":
            return None
        get_state = getattr(manager, "get_latest_drone_state", None)
        if not callable(get_state):
            return "telemetry_state_unavailable"
        state = get_state()
        if not bool(getattr(state, "connected", False)):
            return "telemetry_disconnected"
        if bool(getattr(state, "stale", True)):
            return "telemetry_stale"
        if action_type in {"flight_command", "body_velocity", "local_position", "global_goto", "condition_yaw", "change_speed"}:
            if not bool(getattr(state, "control_allowed", False)):
                return "control_not_allowed"
        return None

    def _validate_flight_command(self, request: dict[str, object], **_: object) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        if params.get("valid") is not True:
            return False, "continuous_command_invalid"
        names = {
            "vx_body_mps": ("vx_cmd", -self.config.max_reverse_mps, self.config.max_forward_mps),
            "vy_body_mps": ("vy_cmd", -self.config.max_left_mps, self.config.max_right_mps),
            "vz_body_mps": ("vz_cmd", -self.config.max_up_mps, self.config.max_down_mps),
        }
        changed = False
        for semantic, (compat, lower, upper) in names.items():
            key = semantic if semantic in params else compat
            value = params.get(key, 0.0)
            if not self._number(value):
                return False, f"invalid_{key}"
            clamped = max(lower, min(upper, float(value)))
            changed = changed or clamped != float(value)
            params[key] = clamped
        for key in ("yaw_rate_rad_s", "yaw_rate_cmd"):
            if key not in params or params[key] is None:
                continue
            if not self._number(params[key]):
                return False, f"invalid_{key}"
            clamped = max(-self.config.max_yaw_rate_rad_s, min(self.config.max_yaw_rate_rad_s, float(params[key])))
            changed = changed or clamped != float(params[key])
            params[key] = clamped
        if params.get("yaw_hold_rad") is not None and params.get("yaw_rate_rad_s") is not None:
            return False, "yaw_and_yaw_rate_conflict"
        return changed, None

    _validate_body_velocity = _validate_flight_command

    def _validate_local_position(
        self,
        request: dict[str, object],
        *,
        link_manager: object | None,
        source: str,
        **_: object,
    ) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        values = self._required_numbers(params, ("x", "y", "z"))
        if values is None:
            return False, "invalid_local_position"
        frame = params.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or frame not in self.config.allowed_local_frames:
            return False, "invalid_local_frame"
        x, y, z = values
        state = self._state(link_manager) if source != "test" else None
        if state is not None and not bool(getattr(state, "local_position_valid", False)):
            return False, "local_position_unavailable"
        if frame == 1:
            dx = x - float(getattr(state, "local_x", 0.0)) if state is not None else x
            dy = y - float(getattr(state, "local_y", 0.0)) if state is not None else y
            dz = z - float(getattr(state, "local_z", 0.0)) if state is not None else z
            final_altitude = -z
        else:
            dx, dy, dz = x, y, z
            final_altitude = (
                -(float(getattr(state, "local_z", 0.0)) + z)
                if state is not None else None
            )
        if math.sqrt(dx ** 2 + dy ** 2 + dz ** 2) > self.config.max_single_waypoint_distance_m:
            return False, "local_waypoint_distance_exceeded"
        if final_altitude is not None:
            if not self.config.min_altitude_m <= final_altitude <= self.config.max_altitude_m:
                return False, "waypoint_altitude_out_of_range"
        field_reason = self._field_reason(request, global_target=False)
        return False, field_reason

    def _validate_global_goto(
        self,
        request: dict[str, object],
        *,
        link_manager: object | None,
        source: str,
        **_: object,
    ) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        values = self._required_numbers(params, ("lat", "lon", "alt"))
        if values is None:
            return False, "invalid_global_position"
        lat, lon, alt = values
        if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
            return False, "global_coordinate_out_of_range"
        frame = params.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or frame not in self.config.allowed_global_frames:
            return False, "invalid_global_frame"
        if not self.config.min_altitude_m <= alt <= self.config.max_altitude_m:
            return False, "waypoint_altitude_out_of_range"
        state = self._state(link_manager) if source != "test" else None
        if state is not None:
            if not bool(getattr(state, "global_position_valid", False)):
                return False, "global_position_unavailable"
            distance_m = self._haversine_m(
                float(getattr(state, "lat", 0.0)),
                float(getattr(state, "lon", 0.0)),
                lat,
                lon,
            )
            if distance_m > self.config.max_single_waypoint_distance_m:
                return False, "global_waypoint_distance_exceeded"
        field_reason = self._field_reason(request, global_target=True)
        return False, field_reason

    def _field_reason(self, request: dict[str, object], *, global_target: bool) -> str | None:
        if str(request.get("input_frame") or "").lower() != "field":
            return None
        if request.get("field_reference_confirmed") is not True:
            return "field_reference_not_confirmed"
        if request.get("field_reference_synced") is not True:
            return "field_reference_not_synced"
        if request.get("field_reference_frozen") is not True:
            return "field_reference_not_frozen"
        ready_name = "field_gps_transform_ready" if global_target else "field_local_transform_ready"
        if request.get(ready_name) is not True:
            return "field_transform_not_ready"
        return None

    def _validate_set_mode(self, request: dict[str, object], **_: object) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        mode = params.get("mode")
        if not isinstance(mode, str) or mode.strip().upper() not in self.config.allowed_modes:
            return False, "mode_not_allowed"
        params["mode"] = mode.strip().upper()
        return False, None

    def _validate_arm(
        self,
        request: dict[str, object],
        *,
        link_manager: object | None,
        source: str,
        **_: object,
    ) -> tuple[bool, str | None]:
        state = self._state(link_manager) if source != "test" else None
        if state is not None and str(getattr(state, "mode", "")).upper() not in self.config.allowed_modes:
            return False, "arm_mode_not_allowed"
        return False, None

    def _validate_takeoff(
        self,
        request: dict[str, object],
        *,
        link_manager: object | None,
        source: str,
        **_: object,
    ) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        altitude = params.get("altitude_m")
        if not self._number(altitude):
            return False, "invalid_takeoff_altitude"
        if not self.config.min_takeoff_altitude_m <= float(altitude) <= self.config.max_takeoff_altitude_m:
            return False, "takeoff_altitude_out_of_range"
        state = self._state(link_manager) if source != "test" else None
        if state is not None:
            if str(getattr(state, "mode", "")).upper() not in self.config.allowed_modes:
                return False, "takeoff_mode_not_allowed"
            if not bool(getattr(state, "armed", False)):
                return False, "takeoff_requires_armed"
        return False, None

    def _validate_land(self, request: dict[str, object], **_: object) -> tuple[bool, str | None]:
        return False, None

    def _validate_condition_yaw(self, request: dict[str, object], **_: object) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        for key in ("yaw_deg", "yaw_speed_deg_s"):
            if not self._number(params.get(key, 20.0 if key == "yaw_speed_deg_s" else None)):
                return False, f"invalid_{key}"
        if not 0.0 < float(params.get("yaw_speed_deg_s", 20.0)) <= math.degrees(self.config.max_yaw_rate_rad_s):
            return False, "yaw_speed_out_of_range"
        if params.get("direction", 0) not in {-1, 0, 1}:
            return False, "yaw_direction_invalid"
        return False, None

    def _validate_change_speed(self, request: dict[str, object], **_: object) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        speed = params.get("speed_mps")
        if not self._number(speed):
            return False, "invalid_speed_mps"
        if not self.config.min_change_speed_mps <= float(speed) <= self.config.max_change_speed_mps:
            return False, "change_speed_out_of_range"
        if params.get("speed_type", 1) not in {0, 1, 2, 3}:
            return False, "invalid_speed_type"
        return False, None

    def _validate_set_servo(
        self,
        request: dict[str, object],
        *,
        action_name: str | None,
        **_: object,
    ) -> tuple[bool, str | None]:
        if action_name not in self.config.payload_allowed_actions:
            return False, "servo_action_not_allowed"
        params = request["params"]
        assert isinstance(params, dict)
        output = params.get("servo_output", params.get("channel"))
        pwm = params.get("pwm")
        if isinstance(output, bool) or not isinstance(output, int):
            return False, "invalid_servo_output"
        if isinstance(pwm, bool) or not isinstance(pwm, int):
            return False, "invalid_servo_pwm"
        limit = self.config.servo_limit(output)
        if limit is None:
            return False, "servo_output_not_allowed"
        if not limit.min_pwm <= pwm <= limit.max_pwm:
            return False, "servo_pwm_out_of_range"
        key = str(request.get("key") or "")
        if not key:
            return False, "servo_idempotency_key_required"
        return False, None

    def mark_servo_sent(self, run_id: str, key: str) -> bool:
        marker = (run_id, key)
        if marker in self._servo_keys:
            return False
        self._servo_keys.add(marker)
        return True

    def _validate_clear_continuous_commands(self, request: dict[str, object], **_: object) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        for key in ("send_stop_first", "clear_pending_local_position"):
            if key in params and not isinstance(params[key], bool):
                return False, f"invalid_{key}"
        return False, None

    def _validate_yolo_lock_target(self, request: dict[str, object], **_: object) -> tuple[bool, str | None]:
        params = request["params"]
        assert isinstance(params, dict)
        track_id = params.get("track_id")
        if isinstance(track_id, bool) or not isinstance(track_id, int) or track_id < 0:
            return False, "invalid_track_id"
        return False, None

    def _reject(
        self,
        reason: str,
        original: dict[str, object],
        action_name: str | None,
        source: str | None,
        authorization: RunAuthorization | None,
        now: float,
    ) -> SafetyDecision:
        decision = SafetyDecision(
            status="rejected",
            reason_code=reason,
            original_request=original,
            effective_request=None,
            run_id=authorization.run_id if authorization else None,
            action=action_name,
            source=source,
            evaluated_at_monotonic=now,
        )
        self._record(decision)
        return decision

    def _record(self, decision: SafetyDecision) -> None:
        if self._on_decision is not None:
            self._on_decision(decision)

    @staticmethod
    def _number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    @classmethod
    def _required_numbers(cls, params: dict[str, object], names: tuple[str, ...]) -> tuple[float, ...] | None:
        values: list[float] = []
        for name in names:
            value = params.get(name)
            if not cls._number(value):
                return None
            values.append(float(value))
        return tuple(values)

    @staticmethod
    def _state(link_manager: object | None) -> object | None:
        getter = getattr(link_manager, "get_latest_drone_state", None)
        return getter() if callable(getter) else None

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius_m = 6_371_000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(d_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
        )
        return 2.0 * radius_m * math.asin(min(1.0, math.sqrt(a)))
