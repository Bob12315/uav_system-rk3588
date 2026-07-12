"""Single internal GPS target flight state machine.

The public wrappers provide validation, operation and presentation hooks; this
module owns the goto → lock → align → operation → climb flight lifecycle.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT
from .align_descend import AlignDescendAction
from .goto_waypoint import GotoWaypointAction
from .gps_target_lock import GpsTargetLockAction
from .payload_release import PayloadReleaseAction
from .result import ActionResult
from .recon_observation_accumulator import ReconObservationAccumulator


class GpsTargetSequenceCore:
    """Internal owner of all GPS target flight phases."""

    @staticmethod
    def zero_velocity_command() -> dict[str, Any]:
        return {"action_type": "flight_command", "params": {"type": "flight_command", "valid": True, "active": True, "enable_body": True, "vx_cmd": 0.0, "vy_cmd": 0.0, "vz_cmd": 0.0, "yaw_rate_cmd": 0.0, "yaw_rate_rad_s": 0.0, "priority": 3}, "once": False}

    @staticmethod
    def clear_continuous_command(key_suffix: str = "") -> dict[str, Any]:
        return {"action_type": "clear_continuous_commands", "params": {"clear_pending_local_position": False, "send_stop_first": True}, "once": True, "key": f"gps_drop_clear_{key_suffix}"}

    def _recon_goto(self, altitude: float, key: str) -> GotoWaypointAction:
        target = self.targets[self.target_index]
        action = GotoWaypointAction()
        action.start({"lat": target["lat"], "lon": target["lon"], "altitude_m": altitude, "target_frame": "global", "waypoint_mode": "absolute", "yaw_mode": "field_heading", "frame": GLOBAL_RELATIVE_ALT_INT, "tolerance_xy_m": self.goto_cfg.get("tolerance_xy_m", .25), "tolerance_z_m": self.goto_cfg.get("tolerance_z_m", .3), "min_hold_updates": self.goto_cfg.get("min_hold_updates", 3), "require_velocity_valid": self.goto_cfg.get("require_velocity_valid", True), "max_horizontal_speed_mps": self.goto_cfg.get("max_horizontal_speed_mps", .15), "max_vertical_speed_mps": self.goto_cfg.get("max_vertical_speed_mps", .1), "key": key})
        return action

    def _recon_transition(self, phase: str, reason: str, actions: list[dict[str, Any]] | None = None) -> ActionResult:
        self.phase = phase; self.sub_action = None; self.phase_updates = 0
        return ActionResult(actions=actions or [], reason=reason, detail=self._detail())
    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if getattr(self, "sequence_kind", "drop") == "recon":
            return self._update_recon(context or {})
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
        if self.phase == "operation":
            return self._update_operation(data)
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
        self.dual_release_servo_outputs: list[dict[str, int]] = []
        self._climb_target_lat = None
        self._climb_target_lon = None

    # ── phases ───────────────────────────────────────────────────────

    def _update_goto(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            t = self.targets[self.target_index]
            # Save GPS position for later climb
            self._climb_target_lat = t["lat"]
            self._climb_target_lon = t["lon"]
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

        # Goto done → lock directly (yaw is field_heading from goto itself)
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

        self.phase = "operation"
        self.sub_action = None
        self.update_count_at_phase = 0
        self._release_reason = "align_done_release"
        return ActionResult(
            actions=[_zero_velocity_command(), _clear_continuous_command("aligned")],
            reason="gps_drop_release_start", detail=self._detail(),
        )

    def _update_operation(self, context: dict[str, Any]) -> ActionResult:
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
            self.phase = "climb"
            return ActionResult(
                actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")],
                reason="gps_drop_climb_start", detail=self._detail(done=False),
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
            self.phase = "climb"
            return ActionResult(
                actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")],
                reason="gps_drop_climb_start", detail=self._detail(done=False),
            )
        # First target done: climb before next target
        self.phase = "climb"
        self.target_index += 1  # advance for climb goto to use next target's position? No: climb uses current target GPS
        # Actually, we need to climb at current target, then goto next. Let's revert target_index advance.
        self.target_index -= 1  # stay on current target for climb
        return ActionResult(
            actions=[_zero_velocity_command()] + (hold or []) + [_clear_continuous_command("release_done")],
            reason="gps_drop_climb_start", detail=self._detail(),
        )

    def _update_climb(self, context: dict[str, Any]) -> ActionResult:
        if self.sub_action is None:
            # Send GLOBAL goto to same GPS position with climb altitude
            lat = self._climb_target_lat
            lon = self._climb_target_lon
            if lat is None or lon is None:
                return self._fail("climb_no_target_position",
                                  actions=[_zero_velocity_command(), _clear_continuous_command("climb_fail")])
            ga = GotoWaypointAction()
            ga.start({
                "lat": lat, "lon": lon,
                "altitude_m": self.climb_after_drop_m,
                "target_frame": "global", "waypoint_mode": "absolute",
                "yaw_mode": "field_heading", "frame": GLOBAL_RELATIVE_ALT_INT,
                "tolerance_xy_m": 99.0,  # effectively ignore horizontal
                "tolerance_z_m": self.climb_tolerance_z_m,
                "min_hold_updates": 1,
                "require_velocity_valid": False,
                "key": f"gps_drop_climb_{self.target_index}",
            })
            self.sub_action = ga
            self.update_count_at_phase = 0

        # Check altitude first — already at height? complete immediately
        current_alt = self._current_altitude_m(context)
        if (
            current_alt is not None
            and current_alt >= self.climb_after_drop_m - self.climb_tolerance_z_m
        ):
            self.sub_action = None
            self.update_count_at_phase = 0
            if self.execution_mode == "single_target_dual_release":
                self.phase = "done"
                return ActionResult(
                    actions=[_zero_velocity_command(), _clear_continuous_command("climb_done")],
                    done=True, reason="gps_drop_sequence_done", detail=self._detail(done=True),
                )
            if self.target_index == 0 and self.released_count == 1:
                self.target_index = 1
                self.payload_index = 1
                self.phase = "goto"
                return ActionResult(
                    actions=[_zero_velocity_command(), _clear_continuous_command("climb_done")],
                    reason="gps_drop_next", detail=self._detail(),
                )
            self.phase = "done"
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command("climb_done")],
                done=True, reason="gps_drop_sequence_done", detail=self._detail(done=True),
            )

        # A valid altitude sample wins the timeout boundary above.  Only fail a
        # climb that is still below the one-way altitude gate.
        if self.update_count_at_phase > self.climb_max_updates:
            return self._fail("climb_timeout",
                              actions=[_zero_velocity_command(), _clear_continuous_command("climb_timeout")])

        # Forward the goto command but use our own altitude-only completion check
        result = self.sub_action.update(context)

        if result.failed:
            return self._fail("climb_goto_failed",
                              actions=[_zero_velocity_command(), _clear_continuous_command("climb_fail")])

        # Check altitude again after goto update
        current_alt = self._current_altitude_m(context)
        climb_done = (
            current_alt is not None
            and current_alt >= self.climb_after_drop_m - self.climb_tolerance_z_m
        )

        if climb_done:
            self.sub_action = None
            self.update_count_at_phase = 0
            # Determine next step
            if self.execution_mode == "single_target_dual_release":
                self.phase = "done"
                return ActionResult(
                    actions=[_zero_velocity_command(), _clear_continuous_command("climb_done")],
                    done=True, reason="gps_drop_sequence_done", detail=self._detail(done=True),
                )
            # dual_target_sequential
            if self.target_index == 0 and self.released_count == 1:
                # First target climb done → goto second target
                self.target_index = 1
                self.payload_index = 1
                self.phase = "goto"
                return ActionResult(
                    actions=[_zero_velocity_command(), _clear_continuous_command("climb_done")],
                    reason="gps_drop_next", detail=self._detail(),
                )
            # Second target climb done → sequence done
            self.phase = "done"
            return ActionResult(
                actions=[_zero_velocity_command(), _clear_continuous_command("climb_done")],
                done=True, reason="gps_drop_sequence_done", detail=self._detail(done=True),
            )

        # Still climbing: forward goto actions
        return ActionResult(
            actions=result.actions,
            reason="gps_drop_climb", detail=self._detail(extra={"altitude_m": current_alt}),
        )

    def _current_altitude_m(self, context: dict[str, Any]) -> float | None:
        """Extract current altitude from context (compatible with AlignDescend)."""
        drone = context.get("drone", {})
        if isinstance(drone, dict):
            for name in ("relative_altitude", "relative_altitude_m"):
                try:
                    value = float(drone[name])
                    if math.isfinite(value) and value >= 0.0:
                        return value
                except (KeyError, TypeError, ValueError):
                    continue
        for name in ("relative_altitude", "relative_altitude_m", "altitude_m"):
            try:
                value = float(context[name])
                if math.isfinite(value) and value >= 0.0:
                    return value
            except (KeyError, TypeError, ValueError):
                continue
        return None

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


def _zero_velocity_command() -> dict[str, Any]:
    return GpsTargetSequenceCore.zero_velocity_command()


def _clear_continuous_command(key_suffix: str = "") -> dict[str, Any]:
    # Preserve the externally asserted drop command key while sharing payload.
    action = GpsTargetSequenceCore.clear_continuous_command(key_suffix)
    action["key"] = f"gps_drop_clear_{key_suffix}"
    return action

    def _update_recon(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started: return ActionResult(failed=True,reason="action_not_started")
        if self.stopped: return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("stopped")],done=True,reason="stopped",detail=self._detail())
        if self.phase == "done": return ActionResult(done=True,reason="gps_recon_sequence_done",detail=self._detail(done=True))
        if self.phase == "failed": return ActionResult(failed=True,reason=self.failure_reason,detail=self._detail())
        self.phase_updates += 1; ctx=context or {}
        return getattr(self, f"_recon_update_{self.phase}")(ctx)

    def _goto(self, altitude: float, key: str) -> GotoWaypointAction:
        t=self.targets[self.target_index]; a=GotoWaypointAction(); a.start({"lat":t["lat"],"lon":t["lon"],"altitude_m":altitude,"target_frame":"global","waypoint_mode":"absolute","yaw_mode":"field_heading","frame":GLOBAL_RELATIVE_ALT_INT,"tolerance_xy_m":self.goto_cfg.get("tolerance_xy_m",.25),"tolerance_z_m":self.goto_cfg.get("tolerance_z_m",.3),"min_hold_updates":self.goto_cfg.get("min_hold_updates",3),"require_velocity_valid":self.goto_cfg.get("require_velocity_valid",True),"max_horizontal_speed_mps":self.goto_cfg.get("max_horizontal_speed_mps",.15),"max_vertical_speed_mps":self.goto_cfg.get("max_vertical_speed_mps",.1),"key":key}); return a
    def _transition(self, phase: str, reason: str, actions=None) -> ActionResult:
        self.phase=phase; self.sub_action=None; self.phase_updates=0; return ActionResult(actions=actions or [],reason=reason,detail=self._detail())
    def _fail(self, reason: str) -> ActionResult:
        self.phase="failed"; self.failure_reason=reason; self.sub_action=None; return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("failed")],failed=True,reason=reason,detail=self._detail())
    def _recon_update_goto(self, ctx):
        if self.sub_action is None: self.sub_action=self._recon_goto(self.approach_altitude_m,f"gps_recon_goto_{self.target_index}"); self.phase_updates=0
        if self.phase_updates > self.goto_max_updates: return self._fail("goto_timeout")
        r=self.sub_action.update(ctx)
        if r.failed: return self._fail("goto_failed")
        return self._recon_transition("lock","gps_recon_lock_start",r.actions) if r.done else ActionResult(actions=r.actions,reason="gps_recon_goto",detail=self._detail())
    def _recon_update_lock(self, ctx):
        if self.sub_action is None:
            t=self.targets[self.target_index]; self.sub_action=GpsTargetLockAction(); self.sub_action.start({"target":{"id":t["target_id"],"lat":t["lat"],"lon":t["lon"],"class_name":str(t.get("class_name", ""))},"max_match_distance_m":self.lock_cfg.get("max_match_distance_m",1.2),"max_updates":self.target_lock_max_updates,"min_confidence":self.lock_cfg.get("min_confidence",.35),"class_names":self.lock_cfg.get("class_names"),"camera":self.lock_cfg.get("camera",{}),"detection_source":self.lock_cfg.get("detection_source","scene")}); self.phase_updates=0
        r=self.sub_action.update(ctx)
        if r.failed: return self._fail("no_lockable_recon_targets")
        return self._recon_transition("align","gps_recon_align_start",r.actions) if r.done else ActionResult(actions=r.actions,reason="gps_recon_lock_searching",detail=self._detail())
    def _recon_update_align(self, ctx):
        if self.sub_action is None:
            p=copy.deepcopy(self.align_cfg); cfg=dict(p.get("config") or {}); cfg["payload_offset_enabled"]=False; cfg["payload_forward_m"]=0.; cfg["payload_right_m"]=0.; p["config"]=cfg; p["finish_altitude_m"]=self.finish_altitude_m; self.sub_action=AlignDescendAction(); self.sub_action.start(p); self.observer=ReconObservationAccumulator(); self.observer.start_target(self.targets[self.target_index], self.target_index, self.observation_cfg); self.phase_updates=0
        if self.phase_updates > self.align_descend_max_updates: return self._fail("align_descend_timeout")
        r=self.sub_action.update(ctx); command=(r.detail or {}).get("command")
        if r.failed: return self._fail(r.reason or "align_failed")
        self.observer.sample((r.detail or {}).get("height_m"), ctx)
        if r.done:
            self._last_observation=self.observer.finalize(r.reason, r.detail)
            return self._recon_transition("climb","gps_recon_climb_start",[self.zero_velocity_command(),self.clear_continuous_command("observed")])
        if isinstance(command,dict) and command.get("valid") and command.get("active"): return ActionResult(actions=[{"action_type":"flight_command","params":dict(command),"once":False,"key":"gps_recon_align","priority":5}],reason="gps_recon_align",detail=self._detail())
        return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("align_inactive")],reason="gps_recon_align_inactive",detail=self._detail())
    def _recon_update_climb(self, ctx):
        if self.sub_action is None: self.sub_action=self._recon_goto(self.climb_after_observe_m,f"gps_recon_climb_{self.target_index}"); self.phase_updates=0
        altitude=self.current_altitude_m(ctx)
        if altitude is not None and altitude >= self.climb_after_observe_m-self.climb_tolerance_z_m:
            self.observations.append({**self.targets[self.target_index],**getattr(self,"_last_observation",{})}); delattr(self,"_last_observation") if hasattr(self,"_last_observation") else None
            if self.target_index+1 == len(self.targets): self.phase="done"; return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("climb_done")],done=True,reason="gps_recon_sequence_done",detail=self._detail(done=True))
            self.target_index+=1; return self._recon_transition("goto","gps_recon_next",[self.zero_velocity_command(),self.clear_continuous_command("climb_done")])
        if self.phase_updates > self.climb_max_updates: return self._fail("climb_timeout")
        r=self.sub_action.update(ctx)
        return self._fail("climb_goto_failed") if r.failed else ActionResult(actions=r.actions,reason="gps_recon_climb",detail=self._detail())
