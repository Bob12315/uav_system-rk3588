"""GPS-first drop sequence action (revised safety control).

Feature 3.4 — GLOBAL goto → yaw align → GPS lock → align-descend → release.
Requires 1-2 targets and 2 payloads.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .gps_target_lock import GpsTargetLockAction
from .align_descend import AlignDescendAction
from .payload_release import PayloadReleaseAction
from .yaw_align import YawAlignAction
from .result import ActionResult


class GpsDropSequenceAction(ActionModule):
    """GPS-first dual-target drop sequence with strict safety rules."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        # ── targets (exactly 2 valid GPS targets) ──
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list) or len(raw_targets) not in (1, 2):
            raise ValueError("targets must contain 1 or 2 entries")
        self.targets: list[dict[str, Any]] = []
        seen_ids = set()
        for t in raw_targets:
            if not isinstance(t, dict):
                continue
            if not t.get("valid", False):
                continue
            try:
                lat = float(t["lat"]); lon = float(t["lon"])
                if not math.isfinite(lat) or not math.isfinite(lon): continue
                if lat < -90 or lat > 90 or lon < -180 or lon > 180: continue
            except (KeyError, TypeError, ValueError): continue
            raw_target_id = t.get("target_id")
            target_id = str(raw_target_id).strip() if raw_target_id is not None else ""
            if target_id.lower() in {"", "none", "null"}:
                target_id = ""
            fallback_id = str(t.get("id") or "").strip()
            if fallback_id.lower() in {"none", "null"}:
                fallback_id = ""
            tid = target_id or fallback_id
            if not tid:
                continue
            if tid in seen_ids: continue  # dedup
            seen_ids.add(tid)
            self.targets.append({
                "lat": lat, "lon": lon,
                "class_name": str(t.get("class_name", "")),
                "target_id": tid,
            })
        if len(self.targets) == 0:
            raise ValueError("at least 1 valid GPS target required, got 0")
        if len(self.targets) > 2:
            raise ValueError("at most 2 valid GPS targets allowed, got " + str(len(self.targets)))
        if len(self.targets) == 2 and _same_gps_position(self.targets[0], self.targets[1]):
            raise ValueError("GPS targets must have distinct positions")

        # ── payloads (exactly 2) ──
        raw_payloads = data.get("payloads", [])
        if not isinstance(raw_payloads, list) or len(raw_payloads) != 2:
            raise ValueError("payloads must contain exactly 2 entries")
        self.payloads: list[dict[str, Any]] = []
        for p in raw_payloads:
            self.payloads.append(_validated_payload(p))

        # ── execution mode ──
        self.execution_mode = (
            "single_target_dual_release" if len(self.targets) == 1
            else "dual_target_sequential"
        )

        # ── pre-validate merged servo outputs for dual release ──
        if self.execution_mode == "single_target_dual_release":
            self.dual_release_servo_outputs = _merge_servo_outputs(
                self.payloads[0], self.payloads[1]
            )
        else:
            self.dual_release_servo_outputs = []

        # ── altitudes ──
        self.approach_altitude_m = float(data.get("approach_altitude_m", 3.0))
        self.finish_altitude_m = float(data.get("finish_altitude_m", 1.3))
        for name, val in (("approach_altitude_m", self.approach_altitude_m),
                          ("finish_altitude_m", self.finish_altitude_m)):
            if not math.isfinite(val) or val <= 0.0:
                raise ValueError(f"{name} must be finite and > 0, got {val}")

        # ── limits ──
        self.goto_max_updates = int(data.get("goto_max_updates", 160))
        self.target_lock_max_updates = int(data.get("target_lock_max_updates", 40))
        self.align_descend_max_updates = int(data.get("align_descend_max_updates", 250))
        self.yaw_align_max_updates = int(data.get("yaw_align_max_updates", 80))
        self.release_wait_updates = int(data.get("release_wait_updates", 5))
        for name, val in (("goto_max_updates", self.goto_max_updates),
                          ("target_lock_max_updates", self.target_lock_max_updates),
                          ("align_descend_max_updates", self.align_descend_max_updates),
                          ("yaw_align_max_updates", self.yaw_align_max_updates),
                          ("release_wait_updates", self.release_wait_updates)):
            if val < 1:
                raise ValueError(f"{name} must be >= 1")

        self.goto_cfg = dict(data.get("goto") or {})
        self.yaw_align_cfg = dict(data.get("yaw_align") or {})
        self.lock_cfg = dict(data.get("target_lock") or {})
        self.align_cfg = dict(data.get("align_descend") or {})
        # finish_policy: allow default (legacy), consistent with v1
        align_config = dict(self.align_cfg.get("config") or {})
        align_config.setdefault("min_altitude_m", self.finish_altitude_m)
        min_altitude_m = float(align_config["min_altitude_m"])
        if not math.isfinite(min_altitude_m) or min_altitude_m <= 0.0:
            raise ValueError("align_descend.config.min_altitude_m must be finite and > 0")
        if min_altitude_m > self.finish_altitude_m:
            raise ValueError(
                "align_descend.config.min_altitude_m must be <= finish_altitude_m"
            )
        # yaw_control_mode / altitude_source / require_target_locked: use config defaults (v1-compatible)
        align_config["min_altitude_m"] = min_altitude_m
        self.align_cfg["config"] = align_config

        # ── state ──
        self.phase = "goto"
        self.target_index = 0
        self.payload_index = 0
        self.released_count = 0
        self.update_count_at_phase = 0
        self.sub_action: Any = None
        self._release_reason = ""
        self._failed_reason = ""

        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started: return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command("1")],
                done=True, reason="stopped",
                detail=self._detail(done=True))

        if self.phase == "done":
            return ActionResult(done=True, reason="gps_drop_sequence_done",
                                detail=self._detail(done=True))
        if self.phase == "failed":
            return ActionResult(failed=True, reason=self._failed_reason,
                                detail=self._detail())

        data = context or {}
        self.update_count_at_phase += 1

        if self.phase == "goto":
            return self._update_goto(data)
        if self.phase == "yaw_align":
            return self._update_yaw_align(data)
        if self.phase == "lock":
            return self._update_lock(data)
        if self.phase == "align":
            return self._update_align(data)
        if self.phase == "release":
            return self._update_release(data)
        return ActionResult(failed=True, reason="invalid_phase")

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.targets = []; self.payloads = []
        self.phase = "idle"; self.target_index = 0; self.payload_index = 0
        self.released_count = 0; self.sub_action = None
        self.started = False; self.stopped = False
        self.dual_release_servo_outputs: list[dict[str, int]] = []

    # ── phases ───────────────────────────────────────────────────────

    def _update_goto(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            t = self.targets[self.target_index]
            ga = GotoWaypointAction()
            ga.start({
                "lat": t["lat"], "lon": t["lon"],
                "altitude_m": self.approach_altitude_m,
                "target_frame": "global", "waypoint_mode": "absolute",
                "yaw_mode": "field_heading", "frame": GLOBAL_RELATIVE_ALT_INT,
                "tolerance_xy_m": self.goto_cfg.get("tolerance_xy_m", 0.25),
                "tolerance_z_m": self.goto_cfg.get("tolerance_z_m", 0.30),
                "min_hold_updates": self.goto_cfg.get("min_hold_updates", 3),
                "require_velocity_valid": self.goto_cfg.get("require_velocity_valid", True),
                "max_horizontal_speed_mps": self.goto_cfg.get("max_horizontal_speed_mps", 0.15),
                "max_vertical_speed_mps": self.goto_cfg.get("max_vertical_speed_mps", 0.10),
                "key": f"gps_drop_goto_{self.target_index}",
            })
            self.sub_action = ga
            self.update_count_at_phase = 0

        if self.update_count_at_phase > self.goto_max_updates:
            return self._fail("goto_timeout")

        result = self.sub_action.update(context)
        if result.failed:
            return self._fail("goto_failed")
        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_drop_goto", detail=self._detail())

        self.phase = "yaw_align"
        self.sub_action = None
        self.update_count_at_phase = 0
        return ActionResult(reason="gps_drop_yaw_align_start", detail=self._detail())

    def _update_yaw_align(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            action = YawAlignAction()
            action.start({
                "yaw_mode": self.yaw_align_cfg.get("yaw_mode", "field_heading"),
                "tolerance_deg": self.yaw_align_cfg.get("tolerance_deg", 4.0),
                "yaw_speed_deg_s": self.yaw_align_cfg.get("yaw_speed_deg_s", 25.0),
                "min_hold_updates": self.yaw_align_cfg.get("min_hold_updates", 3),
                "max_updates": self.yaw_align_cfg.get("max_updates", self.yaw_align_max_updates),
                "priority": self.yaw_align_cfg.get("priority", 4),
                "key": f"gps_drop_yaw_align_{self.target_index}",
            })
            self.sub_action = action
            self.update_count_at_phase = 0
        if self.update_count_at_phase > self.yaw_align_max_updates:
            return self._fail("yaw_align_timeout")
        result = self.sub_action.update(context)
        if result.failed:
            return self._fail(result.reason or "yaw_align_failed")
        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_drop_yaw_align", detail=self._detail(extra={"yaw_align": result.detail}))
        self.phase = "lock"; self.sub_action = None; self.update_count_at_phase = 0
        return ActionResult(reason="gps_drop_lock_start", detail=self._detail(extra={"yaw_align": result.detail}))

    def _update_lock(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            t = self.targets[self.target_index]
            la = GpsTargetLockAction()
            la.start({
                "target": {"id": t["target_id"], "lat": t["lat"], "lon": t["lon"],
                           "class_name": t["class_name"]},
                "max_match_distance_m": self.lock_cfg.get("max_match_distance_m", 1.2),
                "max_updates": self.target_lock_max_updates,
                "min_confidence": self.lock_cfg.get("min_confidence", 0.35),
                "class_names": self.lock_cfg.get("class_names"),
                "camera": self.lock_cfg.get("camera", {}),
                "detection_source": self.lock_cfg.get("detection_source", "scene"),
            })
            self.sub_action = la
            self.update_count_at_phase = 0

        result = self.sub_action.update(context)
        if result.failed:
            self.sub_action = None
            return self._fail("no_lockable_drop_targets",
                              actions=[_zero_velocity_command(), _clear_continuous_command("lock_fail")])

        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_drop_lock_searching",
                                detail=self._detail(extra={"lock": result.detail}))
        # Lock success: forward yolo_lock_target action
        lock_actions = result.actions or []
        self.phase = "align"
        self.sub_action = None
        self.update_count_at_phase = 0
        return ActionResult(actions=lock_actions, reason="gps_drop_align_start",
                            detail=self._detail(extra={"lock": result.detail}))


    def _update_align(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            payload = self.payloads[self.payload_index]
            align_params = copy.deepcopy(self.align_cfg)
            align_config = dict(align_params.get("config") or {})
            align_config["payload_forward_m"] = payload["payload_forward_m"]
            align_config["payload_right_m"] = payload["payload_right_m"]
            align_params["config"] = align_config
            align_params["finish_altitude_m"] = self.finish_altitude_m
            aa = AlignDescendAction()
            aa.start(align_params)
            self.sub_action = aa
            self.update_count_at_phase = 0

        if self.update_count_at_phase > self.align_descend_max_updates:
            return self._fail(
                "align_descend_timeout",
                actions=[_zero_velocity_command(), _clear_continuous_command("timeout")],
            )

        result = self.sub_action.update(context)
        command = result.detail.get("command") if result.detail else None

        if (
            not result.done
            and not result.failed
            and isinstance(command, dict)
            and (not bool(command.get("valid", False)) or not bool(command.get("active", False)))
        ):
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command("align_inactive")],
                reason="gps_drop_align_inactive",
                detail=self._detail(extra={"align": result.detail}),
            )

        # Forward the active align-descend flight command.
        if not result.done and not result.failed and isinstance(command, dict):
            action = {
                "action_type": "flight_command",
                "params": dict(command),
                "once": False,
                "key": "gps_drop_align",
                "priority": 5,
            }
            return ActionResult(actions=[action], reason="gps_drop_align",
                                detail=self._detail(extra={"align": result.detail}))

        if result.failed:
            reason = result.reason or "align_failed"
            return self._fail(
                reason,
                actions=[_zero_velocity_command(), _clear_continuous_command("align_fail")],
            )

        if not result.done:
            return ActionResult(reason="gps_drop_align", detail=self._detail())

        # Align done — accept any done reason (v1-compatible)

        self.phase = "release"
        self.sub_action = None
        self.update_count_at_phase = 0
        self._release_reason = "align_done_release"
        return ActionResult(
            actions=[_zero_velocity_command(), _clear_continuous_command("aligned")],
            reason="gps_drop_release_start", detail=self._detail(),
        )

    def _update_release(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            t = self.targets[self.target_index]
            if self.execution_mode == "single_target_dual_release":
                pa = PayloadReleaseAction()
                pa.start({
                    "servo_outputs": self.dual_release_servo_outputs,
                    "payload_id": "payload_1_and_2",
                    "target_id": t["target_id"],
                    "release_wait_updates": self.release_wait_updates,
                    "priority": min(
                        self.payloads[0].get("priority", 5),
                        self.payloads[1].get("priority", 5),
                    ),
                })
            else:
                payload = self.payloads[self.payload_index]
                pa = PayloadReleaseAction()
                pa.start({
                    "servo_outputs": payload.get("servo_outputs", []),
                    "payload_id": str(payload.get("payload_id", f"payload_{self.payload_index}")),
                    "target_id": t["target_id"],
                    "release_wait_updates": self.release_wait_updates,
                    "priority": payload.get("priority", 5),
                })
            self.sub_action = pa
            self.update_count_at_phase = 0

        result = self.sub_action.update(context)
        if result.failed:
            return self._fail("payload_release_failed")

        if not result.done:
            return ActionResult(
                actions=[_zero_velocity_command()] + (result.actions or []),
                reason="gps_drop_releasing", detail=self._detail(),
            )

        hold = result.actions or []

        if self.execution_mode == "single_target_dual_release":
            self.released_count = 2
            self.payload_index = 2
            self.sub_action = None
            self.update_count_at_phase = 0
            self.phase = "done"
            return ActionResult(
                actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")],
                done=True, reason="gps_drop_sequence_done", detail=self._detail(done=True),
            )

        # ── dual_target_sequential ──
        self.released_count += 1
        self.payload_index += 1
        self.sub_action = None
        self.update_count_at_phase = 0

        is_terminal = self.released_count == 2 and self.payload_index == 2 and self.target_index == 1
        if not is_terminal and not (
            self.released_count == 1
            and self.payload_index == 1
            and self.target_index == 0
        ):
            return self._fail("incomplete_dual_target_drop",
                              actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")])

        if is_terminal:
            self.phase = "done"
            return ActionResult(
                actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")],
                done=True, reason="gps_drop_sequence_done", detail=self._detail(done=True),
            )
        self.target_index += 1
        self.phase = "goto"
        return ActionResult(
            actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")],
            reason="gps_drop_next", detail=self._detail(),
        )

    # ── helpers ─────────────────────────────────────────────────────

    def _fail(
        self,
        reason: str,
        *,
        actions: list[dict[str, Any]] | None = None,
    ) -> ActionResult:
        self.phase = "failed"
        self._failed_reason = reason
        self.sub_action = None
        return ActionResult(
            actions=(
                actions
                if actions is not None
                else [_zero_velocity_command(), _clear_continuous_command("failed")]
            ),
            failed=True, reason=reason,
            detail=self._detail(),
        )

    def _detail(self, *, done: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "phase": self.phase, "target_index": self.target_index,
            "payload_index": self.payload_index, "released_count": self.released_count,
            "target_count": len(self.targets), "payload_count": len(self.payloads),
            "release_reason": self._release_reason,
            "execution_mode": getattr(self, "execution_mode", "dual_target_sequential"),
            "dual_release": getattr(self, "execution_mode", "") == "single_target_dual_release",
        }
        if done: d["done"] = True
        if extra: d.update(extra)
        return d


def _merge_servo_outputs(payload_a: dict[str, Any], payload_b: dict[str, Any]) -> list[dict[str, int]]:
    """Merge servo_outputs from two payloads into one combined list.

    Validates that both payloads have valid servo_outputs, channels do not
    duplicate, and returns a new list without modifying the originals.
    """
    outputs_a = payload_a.get("servo_outputs", [])
    outputs_b = payload_b.get("servo_outputs", [])
    if not outputs_a or not outputs_b:
        raise ValueError("both payloads must have valid servo_outputs for merge")

    merged: list[dict[str, int]] = [dict(item) for item in outputs_a]
    channels_seen: set[int] = {item["channel"] for item in outputs_a}
    for item in outputs_b:
        ch = item["channel"]
        if ch in channels_seen:
            raise ValueError(f"duplicate servo channel {ch} in merged payloads")
        channels_seen.add(ch)
        merged.append(dict(item))
    return merged


def _zero_velocity_command() -> dict[str, Any]:
    return {"action_type": "flight_command",
            "params": {"type": "flight_command", "valid": True, "active": True,
                       "enable_body": True,
                       "vx_cmd": 0.0, "vy_cmd": 0.0, "vz_cmd": 0.0, "yaw_rate_cmd": 0.0,
                       "yaw_rate_rad_s": 0.0,
                       "priority": 3},
            "once": False}


def _clear_continuous_command(key_suffix: str = "") -> dict[str, Any]:
    return {"action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": False, "send_stop_first": True},
            "once": True,
            "key": f"gps_drop_clear_{key_suffix}"}


def _same_gps_position(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return math.isclose(first["lat"], second["lat"], rel_tol=0.0, abs_tol=1e-9) and math.isclose(
        first["lon"], second["lon"], rel_tol=0.0, abs_tol=1e-9
    )


def _validated_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("payload entries must be dicts")
    payload_id = str(raw.get("payload_id", "")).strip()
    if not payload_id:
        raise ValueError("payload_id is required")
    outputs = raw.get("servo_outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("payload servo_outputs must be a non-empty list")

    validated_outputs: list[dict[str, int]] = []
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("servo_outputs entries must be dicts")
        try:
            channel = int(output["channel"])
            release_pwm = int(output["release_pwm"])
            hold_pwm = int(output["hold_pwm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "servo_outputs require integer channel, release_pwm, and hold_pwm"
            ) from exc
        if channel <= 0:
            raise ValueError("servo output channel must be positive")
        if not (500 <= release_pwm <= 2500 and 500 <= hold_pwm <= 2500):
            raise ValueError("servo PWM values must be between 500 and 2500")
        validated_outputs.append(
            {"channel": channel, "release_pwm": release_pwm, "hold_pwm": hold_pwm}
        )

    payload = dict(raw)
    for name in ("payload_forward_m", "payload_right_m"):
        try:
            value = float(raw.get(name, 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite float") from exc
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite float")
        payload[name] = value
    payload["payload_id"] = payload_id
    payload["servo_outputs"] = validated_outputs
    return payload
