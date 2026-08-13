from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAFETY_CONFIG_PATH = ROOT_DIR / "config" / "safety.yaml"


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return dict(value)


def _finite_positive(value: object, name: str, *, allow_zero: bool = False) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or (number == 0.0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return number


@dataclass(frozen=True, slots=True)
class ServoOutputLimit:
    servo_output: int
    min_pwm: int
    max_pwm: int


@dataclass(frozen=True, slots=True)
class SafetyConfig:
    request_ttl_s: float
    max_forward_mps: float
    max_reverse_mps: float
    max_right_mps: float
    max_left_mps: float
    max_down_mps: float
    max_up_mps: float
    max_yaw_rate_rad_s: float
    continuous_deadman_s: float
    watchdog_poll_s: float
    slew_rate_limit_enabled: bool
    min_altitude_m: float
    max_altitude_m: float
    max_single_waypoint_distance_m: float
    min_change_speed_mps: float
    max_change_speed_mps: float
    allowed_local_frames: frozenset[int]
    allowed_global_frames: frozenset[int]
    min_takeoff_altitude_m: float
    max_takeoff_altitude_m: float
    allowed_modes: frozenset[str]
    payload_allowed_actions: frozenset[str]
    servo_outputs: tuple[ServoOutputLimit, ...]
    enabled_sources: frozenset[str]

    def servo_limit(self, output: int) -> ServoOutputLimit | None:
        return next((item for item in self.servo_outputs if item.servo_output == output), None)


def load_safety_config(path: str | Path = DEFAULT_SAFETY_CONFIG_PATH) -> SafetyConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    root = _mapping(raw, "safety")
    if root.get("version") != 1:
        raise ValueError("safety.version must be 1")
    request = _mapping(root.get("request"), "request")
    continuous = _mapping(root.get("continuous_body_ned"), "continuous_body_ned")
    navigation = _mapping(root.get("navigation"), "navigation")
    takeoff = _mapping(root.get("takeoff"), "takeoff")
    payload = _mapping(root.get("payload"), "payload")
    sources = _mapping(root.get("sources"), "sources")

    slew = continuous.get("slew_rate_limit_enabled")
    if not isinstance(slew, bool):
        raise ValueError("continuous_body_ned.slew_rate_limit_enabled must be a bool")

    raw_outputs = payload.get("outputs")
    if not isinstance(raw_outputs, list) or not raw_outputs:
        raise ValueError("payload.outputs must be a non-empty list")
    outputs: list[ServoOutputLimit] = []
    for index, value in enumerate(raw_outputs):
        item = _mapping(value, f"payload.outputs[{index}]")
        output = item.get("servo_output")
        min_pwm = item.get("min_pwm")
        max_pwm = item.get("max_pwm")
        if any(isinstance(number, bool) or not isinstance(number, int) for number in (output, min_pwm, max_pwm)):
            raise ValueError(f"payload.outputs[{index}] values must be integers")
        if output <= 0 or not 800 <= min_pwm <= max_pwm <= 2200:
            raise ValueError(f"payload.outputs[{index}] has an invalid output/PWM range")
        outputs.append(ServoOutputLimit(output, min_pwm, max_pwm))
    if len({item.servo_output for item in outputs}) != len(outputs):
        raise ValueError("payload.outputs contains duplicate servo_output values")

    enabled_sources = frozenset(
        str(name) for name, value in sources.items()
        if isinstance(value, dict) and value.get("enabled") is True
    )
    if not enabled_sources or not enabled_sources.issubset({"sitl", "real"}):
        raise ValueError("sources must explicitly enable sitl and/or real")

    config = SafetyConfig(
        request_ttl_s=_finite_positive(request.get("ttl_s"), "request.ttl_s"),
        max_forward_mps=_finite_positive(continuous.get("max_forward_mps"), "continuous_body_ned.max_forward_mps"),
        max_reverse_mps=_finite_positive(continuous.get("max_reverse_mps"), "continuous_body_ned.max_reverse_mps"),
        max_right_mps=_finite_positive(continuous.get("max_right_mps"), "continuous_body_ned.max_right_mps"),
        max_left_mps=_finite_positive(continuous.get("max_left_mps"), "continuous_body_ned.max_left_mps"),
        max_down_mps=_finite_positive(continuous.get("max_down_mps"), "continuous_body_ned.max_down_mps"),
        max_up_mps=_finite_positive(continuous.get("max_up_mps"), "continuous_body_ned.max_up_mps"),
        max_yaw_rate_rad_s=_finite_positive(continuous.get("max_yaw_rate_rad_s"), "continuous_body_ned.max_yaw_rate_rad_s"),
        continuous_deadman_s=_finite_positive(continuous.get("deadman_s"), "continuous_body_ned.deadman_s"),
        watchdog_poll_s=_finite_positive(continuous.get("watchdog_poll_s"), "continuous_body_ned.watchdog_poll_s"),
        slew_rate_limit_enabled=slew,
        min_altitude_m=_finite_positive(navigation.get("min_altitude_m"), "navigation.min_altitude_m", allow_zero=True),
        max_altitude_m=_finite_positive(navigation.get("max_altitude_m"), "navigation.max_altitude_m"),
        max_single_waypoint_distance_m=_finite_positive(navigation.get("max_single_waypoint_distance_m"), "navigation.max_single_waypoint_distance_m"),
        min_change_speed_mps=_finite_positive(navigation.get("min_change_speed_mps"), "navigation.min_change_speed_mps"),
        max_change_speed_mps=_finite_positive(navigation.get("max_change_speed_mps"), "navigation.max_change_speed_mps"),
        allowed_local_frames=frozenset(int(value) for value in navigation.get("allowed_local_frames", [])),
        allowed_global_frames=frozenset(int(value) for value in navigation.get("allowed_global_frames", [])),
        min_takeoff_altitude_m=_finite_positive(takeoff.get("min_altitude_m"), "takeoff.min_altitude_m"),
        max_takeoff_altitude_m=_finite_positive(takeoff.get("max_altitude_m"), "takeoff.max_altitude_m"),
        allowed_modes=frozenset(str(value).strip().upper() for value in takeoff.get("allowed_modes", [])),
        payload_allowed_actions=frozenset(str(value) for value in payload.get("allowed_actions", [])),
        servo_outputs=tuple(outputs),
        enabled_sources=enabled_sources,
    )
    if config.min_altitude_m >= config.max_altitude_m:
        raise ValueError("navigation altitude range is empty")
    if config.min_takeoff_altitude_m >= config.max_takeoff_altitude_m:
        raise ValueError("takeoff altitude range is empty")
    if config.min_change_speed_mps >= config.max_change_speed_mps:
        raise ValueError("change-speed range is empty")
    if not config.allowed_local_frames or not config.allowed_global_frames or not config.allowed_modes:
        raise ValueError("frame and mode allowlists must be non-empty")
    if not config.payload_allowed_actions:
        raise ValueError("payload.allowed_actions must be non-empty")
    return config
