"""GPS-first drop sequence action.

Feature 3.4 — GLOBAL goto → GPS lock → align-descend → release → climb
for up to 2 targets / 2 payloads.
"""

from __future__ import annotations

from typing import Any

from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .gps_target_lock import GpsTargetLockAction
from .align_descend import AlignDescendAction
from .payload_release import PayloadReleaseAction
from .result import ActionResult


class GpsDropSequenceAction(ActionModule):
    """GPS-first dual-target drop sequence.

    State machine: goto → lock → align_descend → release → climb → next.
    All movement uses GLOBAL lat/lon/alt.
    """

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        # Targets with lat/lon
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list):
            raise ValueError("targets must be a list")
        self.targets: list[dict[str, Any]] = []
        for t in raw_targets[:2]:
            if not isinstance(t, dict): continue
            if not t.get("valid", False): continue
            try:
                lat = float(t["lat"]); lon = float(t["lon"])
                import math
                if not math.isfinite(lat) or not math.isfinite(lon): continue
                if lat < -90 or lat > 90 or lon < -180 or lon > 180: continue
            except (KeyError, TypeError, ValueError): continue
            self.targets.append({"lat": lat, "lon": lon, "class_name": str(t.get("class_name", "")),
                                 "target_id": str(t.get("target_id", t.get("id", "")))})
        if len(self.targets) < 1:
            raise ValueError("at least 1 valid GPS target required")

        # Payloads
        raw_payloads = data.get("payloads", [])
        if not isinstance(raw_payloads, list):
            raise ValueError("payloads must be a list")
        self.payloads: list[dict[str, Any]] = [dict(p) for p in raw_payloads[:2] if isinstance(p, dict)]
        if not self.payloads:
            raise ValueError("at least 1 payload required")

        # Altitudes
        self.approach_altitude_m = float(data.get("approach_altitude_m", 3.0))
        self.finish_altitude_m = float(data.get("finish_altitude_m", 1.3))
        self.climb_after_drop_m = float(data.get("climb_after_drop_m", 5.0))

        # Limits
        self.goto_max_updates = int(data.get("goto_max_updates", 160))
        self.target_lock_max_updates = int(data.get("target_lock_max_updates", 40))
        self.align_descend_max_updates = int(data.get("align_descend_max_updates", 250))
        self.climb_max_updates = int(data.get("climb_max_updates", 120))
        self.release_wait_updates = int(data.get("release_wait_updates", 5))

        # Sub-action configs
        self.goto_cfg = dict(data.get("goto") or {})
        self.lock_cfg = dict(data.get("target_lock") or {})
        self.align_cfg = dict(data.get("align_descend") or {})
        self.align_cfg.setdefault("finish_policy", "require_alignment_or_timeout")

        # State
        self.phase = "goto"
        self.target_index = 0
        self.payload_index = 0
        self.released_count = 0
        self.update_count_at_phase = 0
        self.release_wait_count = 0
        self.sub_action: Any = None
        self._zero_sent = False
        self._last_locked_track_id = None

        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started: return ActionResult(failed=True, reason="action_not_started")
        if self.stopped: return ActionResult(done=True, reason="stopped")
        if self.phase == "done":
            return ActionResult(done=True, reason="gps_drop_sequence_done",
                                detail=self._detail(done=True))

        data = context or {}
        self.update_count_at_phase += 1

        if self.phase == "goto":
            return self._update_goto(data)
        if self.phase == "lock":
            return self._update_lock(data)
        if self.phase == "align":
            return self._update_align(data)
        if self.phase == "zero":
            return self._update_zero(data)
        if self.phase == "release":
            return self._update_release(data)
        if self.phase == "climb":
            return self._update_climb(data)
        return ActionResult(failed=True, reason="invalid_phase")

    def stop(self) -> None:
        self.stopped = True
        if self.sub_action is not None:
            try: self.sub_action.stop()
            except: pass

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
                "yaw_mode": "hold",
                "frame": GLOBAL_RELATIVE_ALT_INT,
                "tolerance_xy_m": self.goto_cfg.get("tolerance_xy_m", 0.35),
                "tolerance_z_m": self.goto_cfg.get("tolerance_z_m", 0.35),
                "min_hold_updates": self.goto_cfg.get("min_hold_updates", 1),
                "key": f"gps_drop_goto_{self.target_index}",
            })
            self.sub_action = ga
            self.update_count_at_phase = 0

        if self.update_count_at_phase > self.goto_max_updates:
            self.phase = "done"
            return ActionResult(failed=True, reason="goto_timeout", detail=self._detail())

        result = self.sub_action.update(context)
        if result.failed:
            return ActionResult(failed=True, reason="goto_failed", detail=self._detail(extra={"goto": result.detail}))
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
            # Don't descend, don't release, try next target or fail
            self.sub_action = None
            if self.target_index + 1 < len(self.targets):
                self.target_index += 1
                self.phase = "goto"
                self.update_count_at_phase = 0
                return ActionResult(reason="gps_drop_lock_failed_next_target", detail=self._detail())
            return ActionResult(failed=True, reason="no_lockable_drop_targets",
                                detail=self._detail(extra={"released_count": self.released_count}))

        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_drop_lock_searching",
                                detail=self._detail(extra={"lock": result.detail}))

        self._last_locked_track_id = result.detail.get("locked_track_id")
        self.phase = "align"
        self.sub_action = None
        self.update_count_at_phase = 0
        return ActionResult(reason="gps_drop_align_start", detail=self._detail())

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
            # Align timeout → zero velocity → release
            self._zero_sent = False
            self.phase = "zero"
            self.sub_action = None
            self.update_count_at_phase = 0
            self._release_reason = "align_timeout_release"
            return ActionResult(reason="gps_drop_align_timeout", detail=self._detail())

        result = self.sub_action.update(context)
        if result.failed:
            reason = result.reason
            if reason in ("align_descend_timeout",):
                self._zero_sent = False
                self.phase = "zero"
                self.sub_action = None
                self.update_count_at_phase = 0
                self._release_reason = "align_timeout_release"
                return ActionResult(reason="gps_drop_align_timeout_release", detail=self._detail())
            # Other failures: zero but don't release
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command()],
                failed=True, reason=reason or "align_failed",
                detail=self._detail(extra={"align": result.detail}),
            )

        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_drop_align", detail=self._detail(extra={"align": result.detail}))

        # Align done normally → zero → release
        self._zero_sent = False
        self.phase = "zero"
        self.sub_action = None
        self.update_count_at_phase = 0
        self._release_reason = "aligned_release"
        return ActionResult(reason="gps_drop_align_done", detail=self._detail())

    def _update_zero(self, context: dict[str, Any]) -> ActionResult:
        """Send zero velocity + clear continuous before allowing release."""
        if not self._zero_sent:
            self._zero_sent = True
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command()],
                reason="gps_drop_zero_before_release", detail=self._detail(),
            )

        # Next tick: enter release
        self.phase = "release"
        self.sub_action = None
        self.update_count_at_phase = 0
        self.release_wait_count = 0
        return ActionResult(
            actions=[_zero_velocity_command()],
            reason="gps_drop_release_start", detail=self._detail(),
        )

    def _update_release(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            payload = self.payloads[self.payload_index % len(self.payloads)]
            pa = PayloadReleaseAction()
            pa.start(dict(payload))
            self.sub_action = pa
            self.update_count_at_phase = 0

        result = self.sub_action.update(context)
        if result.failed:
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command()],
                failed=True, reason="payload_release_failed",
                detail=self._detail(extra={"release": result.detail}),
            )

        if not result.done:
            return ActionResult(
                actions=result.actions + [_zero_velocity_command()],
                reason="gps_drop_releasing", detail=self._detail(),
            )

        # Release done
        self.released_count += 1
        self.payload_index += 1
        self.sub_action = None
        self.update_count_at_phase = 0

        # Hold servo
        hold = result.actions or []

        if self.target_index + 1 < len(self.targets) and self.payload_index < len(self.payloads):
            self.target_index += 1
            self.phase = "climb"
            return ActionResult(
                actions=hold + [_zero_velocity_command()],
                reason="gps_drop_climb_start", detail=self._detail(),
            )
        self.phase = "done"
        return ActionResult(
            actions=hold + [_zero_velocity_command(), _clear_continuous_command()],
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
                "yaw_mode": "hold",
                "frame": GLOBAL_RELATIVE_ALT_INT,
                "tolerance_xy_m": 0.5, "tolerance_z_m": 0.5,
                "min_hold_updates": 1, "key": f"gps_drop_climb_{self.target_index}",
            })
            self.sub_action = ga
            self.update_count_at_phase = 0

        result = self.sub_action.update(context)
        if not result.done:
            return ActionResult(actions=result.actions, reason="gps_drop_climb", detail=self._detail())
        # Climb timeout doesn't fail — move to next target
        self.phase = "goto"
        self.sub_action = None
        self.update_count_at_phase = 0
        return ActionResult(reason="gps_drop_next", detail=self._detail())

    def _detail(self, *, done: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "phase": self.phase, "target_index": self.target_index,
            "payload_index": self.payload_index, "released_count": self.released_count,
            "target_count": len(self.targets), "payload_count": len(self.payloads),
        }
        if hasattr(self, '_release_reason'):
            d["release_reason"] = self._release_reason
        if done:
            d["done"] = True
        if extra: d.update(extra)
        return d


def _zero_velocity_command() -> dict[str, Any]:
    return {"action_type": "flight_command",
            "params": {"vx": 0.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0}}


def _clear_continuous_command() -> dict[str, Any]:
    return {"action_type": "clear_continuous",
            "params": {"send_stop_first": True}}
