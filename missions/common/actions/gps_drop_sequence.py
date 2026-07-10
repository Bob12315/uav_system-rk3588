"""GPS-first drop sequence action (revised safety control).

Feature 3.4 — GLOBAL goto → GPS lock → align-descend → release → climb.
Requires exactly 2 targets and 2 payloads.
"""

from __future__ import annotations

import math
from typing import Any

from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .gps_target_lock import GpsTargetLockAction
from .align_descend import AlignDescendAction
from .payload_release import PayloadReleaseAction
from .result import ActionResult


class GpsDropSequenceAction(ActionModule):
    """GPS-first dual-target drop sequence with strict safety rules."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        # ── targets (exactly 2 valid GPS targets) ──
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list):
            raise ValueError("targets must be a list")
        self.targets: list[dict[str, Any]] = []
        seen_ids = set()
        for t in raw_targets:
            if not isinstance(t, dict): continue
            if not t.get("valid", False): continue
            try:
                lat = float(t["lat"]); lon = float(t["lon"])
                if not math.isfinite(lat) or not math.isfinite(lon): continue
                if lat < -90 or lat > 90 or lon < -180 or lon > 180: continue
            except (KeyError, TypeError, ValueError): continue
            tid = str(t.get("target_id", t.get("id", "")))
            if tid in seen_ids: continue  # dedup
            seen_ids.add(tid)
            self.targets.append({
                "lat": lat, "lon": lon,
                "class_name": str(t.get("class_name", "")),
                "target_id": tid,
            })
            if len(self.targets) >= 2:
                break
        if len(self.targets) < 2:
            raise ValueError("exactly 2 valid GPS targets required, got " + str(len(self.targets)))

        # ── payloads (exactly 2) ──
        raw_payloads = data.get("payloads", [])
        if not isinstance(raw_payloads, list):
            raise ValueError("payloads must be a list")
        self.payloads: list[dict[str, Any]] = []
        for p in raw_payloads:
            if not isinstance(p, dict): continue
            self.payloads.append(dict(p))
            if len(self.payloads) >= 2:
                break
        if len(self.payloads) < 2:
            raise ValueError("exactly 2 payloads required, got " + str(len(self.payloads)))

        # ── altitudes ──
        self.approach_altitude_m = float(data.get("approach_altitude_m", 3.0))
        self.finish_altitude_m = float(data.get("finish_altitude_m", 1.3))
        self.climb_after_drop_m = float(data.get("climb_after_drop_m", 5.0))
        for name, val in (("approach_altitude_m", self.approach_altitude_m),
                          ("finish_altitude_m", self.finish_altitude_m),
                          ("climb_after_drop_m", self.climb_after_drop_m)):
            if not math.isfinite(val) or val <= 0.0:
                raise ValueError(f"{name} must be finite and > 0, got {val}")

        # ── limits ──
        self.goto_max_updates = int(data.get("goto_max_updates", 160))
        self.target_lock_max_updates = int(data.get("target_lock_max_updates", 40))
        self.align_descend_max_updates = int(data.get("align_descend_max_updates", 250))
        self.climb_max_updates = int(data.get("climb_max_updates", 120))
        self.release_wait_updates = int(data.get("release_wait_updates", 5))
        for name, val in (("goto_max_updates", self.goto_max_updates),
                          ("target_lock_max_updates", self.target_lock_max_updates),
                          ("align_descend_max_updates", self.align_descend_max_updates),
                          ("climb_max_updates", self.climb_max_updates),
                          ("release_wait_updates", self.release_wait_updates)):
            if val < 1:
                raise ValueError(f"{name} must be >= 1")

        self.goto_cfg = dict(data.get("goto") or {})
        self.lock_cfg = dict(data.get("target_lock") or {})
        self.align_cfg = dict(data.get("align_descend") or {})
        self.align_cfg.setdefault("finish_policy", "require_alignment_or_timeout")
        if "min_altitude_m" not in self.align_cfg:
            self.align_cfg["min_altitude_m"] = self.finish_altitude_m

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
        if self.phase == "lock":
            return self._update_lock(data)
        if self.phase == "align":
            return self._update_align(data)
        if self.phase == "release":
            return self._update_release(data)
        if self.phase == "climb":
            return self._update_climb(data)
        return ActionResult(failed=True, reason="invalid_phase")

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.targets = []; self.payloads = []
        self.phase = "idle"; self.target_index = 0; self.payload_index = 0
        self.released_count = 0; self.sub_action = None
        self.started = False; self.stopped = False

    # ── phases ───────────────────────────────────────────────────────

    def _update_goto(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            t = self.targets[self.target_index]
            ga = GotoWaypointAction()
            ga.start({
                "lat": t["lat"], "lon": t["lon"],
                "altitude_m": self.approach_altitude_m,
                "target_frame": "global", "waypoint_mode": "absolute",
                "yaw_mode": "hold", "frame": GLOBAL_RELATIVE_ALT_INT,
                "tolerance_xy_m": self.goto_cfg.get("tolerance_xy_m", 0.35),
                "tolerance_z_m": self.goto_cfg.get("tolerance_z_m", 0.35),
                "min_hold_updates": self.goto_cfg.get("min_hold_updates", 1),
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

        self.phase = "lock"
        self.sub_action = None
        self.update_count_at_phase = 0
        return ActionResult(reason="gps_drop_lock_start", detail=self._detail())

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
            aa = AlignDescendAction()
            aa.start({
                "finish_altitude_m": self.finish_altitude_m,
                **self.align_cfg,
            })
            self.sub_action = aa
            self.update_count_at_phase = 0

        if self.update_count_at_phase > self.align_descend_max_updates:
            self.phase = "release"
            self.sub_action = None
            self.update_count_at_phase = 0
            self._release_reason = "align_timeout_release"
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command("timeout")],
                reason="gps_drop_align_timeout_release", detail=self._detail(),
            )

        result = self.sub_action.update(context)
        command = result.detail.get("command") if result.detail else None

        # Active BODY_NED command forwarding
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
            reason = result.reason
            if reason in ("align_descend_timeout",):
                self.phase = "release"
                self.sub_action = None
                self.update_count_at_phase = 0
                self._release_reason = "align_timeout_release"
                return ActionResult(
                    actions=[_zero_velocity_command(), _clear_continuous_command("child_timeout")],
                    reason="gps_drop_align_timeout_release", detail=self._detail(),
                )
            # Other failures: zero + clear, no release
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command("2")],
                failed=True, reason=reason or "align_failed",
                detail=self._detail(),
            )

        if not result.done:
            return ActionResult(reason="gps_drop_align", detail=self._detail())

        # Align done — only "aligned_at_finish_altitude" allows release
        if result.reason != "aligned_at_finish_altitude":
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command("3")],
                failed=True, reason="align_unexpected_done",
                detail=self._detail(),
            )

        self.phase = "zero"
        self.update_count_at_phase = 0
        self._release_reason = "aligned_release"
        return ActionResult(reason="gps_drop_align_done", detail=self._detail())

    def _update_release(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            payload = self.payloads[self.payload_index]
            t = self.targets[self.target_index]
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

        self.released_count += 1
        self.payload_index += 1
        self.sub_action = None
        self.update_count_at_phase = 0

        hold = result.actions or []

        if self.payload_index < 2 and self.target_index + 1 < 2:
            self.phase = "climb"
            return ActionResult(
                actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")],
                reason="gps_drop_climb_start", detail=self._detail(),
            )
        self.phase = "done"
        return ActionResult(
            actions=hold + [_zero_velocity_command(), _clear_continuous_command("5")],
            done=True, reason="gps_drop_sequence_done",
            detail=self._detail(done=True),
        )

    def _update_climb(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            t = self.targets[self.target_index]
            ga = GotoWaypointAction()
            ga.start({
                "lat": t["lat"], "lon": t["lon"],
                "altitude_m": self.climb_after_drop_m,
                "target_frame": "global", "waypoint_mode": "absolute",
                "yaw_mode": "hold", "frame": GLOBAL_RELATIVE_ALT_INT,
                "tolerance_xy_m": 0.5, "tolerance_z_m": 0.5,
                "min_hold_updates": 1, "key": f"gps_drop_climb_{self.target_index}",
            })
            self.sub_action = ga
            self.update_count_at_phase = 0

        if self.update_count_at_phase > self.climb_max_updates:
            return self._fail("climb_timeout",
                              actions=[_zero_velocity_command(), _clear_continuous_command("climb_timeout")])
        result = self.sub_action.update(context)
        if result.failed:
            return self._fail("climb_failed",
                              actions=[_zero_velocity_command(), _clear_continuous_command("climb_fail")])
        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_drop_climb", detail=self._detail())
        self.target_index += 1
        self.phase = "goto"
        self.sub_action = None
        self.update_count_at_phase = 0
        return ActionResult(reason="gps_drop_next", detail=self._detail())

    # ── helpers ─────────────────────────────────────────────────────

    def _fail(self, reason: str) -> ActionResult:
        self.phase = "failed"
        self._failed_reason = reason
        return ActionResult(
            actions=[_zero_velocity_command(), _clear_continuous_command("6")],
            failed=True, reason=reason,
            detail=self._detail(),
        )

    def _detail(self, *, done: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "phase": self.phase, "target_index": self.target_index,
            "payload_index": self.payload_index, "released_count": self.released_count,
            "target_count": len(self.targets), "payload_count": len(self.payloads),
            "release_reason": self._release_reason,
        }
        if done: d["done"] = True
        if extra: d.update(extra)
        return d


def _zero_velocity_command() -> dict[str, Any]:
    return {"action_type": "flight_command",
            "params": {"type": "flight_command", "valid": True, "active": True,
                       "enable_body": True,
                       "vx_cmd": 0.0, "vy_cmd": 0.0, "vz_cmd": 0.0, "yaw_rate_cmd": 0.0,
                       "priority": 3},
            "once": False}


def _clear_continuous_command(key_suffix: str = "") -> dict[str, Any]:
    return {"action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": False, "send_stop_first": True},
            "once": True,
            "key": f"gps_drop_clear_{key_suffix}"}
