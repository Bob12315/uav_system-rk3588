# Archived behavior-lock source; not importable by production.
"""GPS-first drop sequence action (revised safety control).

Feature 3.4 — GLOBAL goto → GPS lock → align-descend → release → climb.
Requires 1-2 targets and 2 payloads.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from field.coordinates import field_to_gps_from_origin
from field.models import FieldReferenceError
from .frames import GLOBAL_RELATIVE_ALT_INT

from .base import ActionModule
from .goto_waypoint import GotoWaypointAction
from .gps_target_lock import GpsTargetLockAction
from .align_descend import AlignDescendAction
from .payload_release import PayloadReleaseAction
from .result import ActionResult
from .gps_target_sequence_core import GpsTargetSequenceCore


class GpsDropSequenceAction(GpsTargetSequenceCore, ActionModule):
    """GPS-first dual-target drop sequence with strict safety rules."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        self._goto_action_factory=GotoWaypointAction; self._lock_action_factory=GpsTargetLockAction; self._align_action_factory=AlignDescendAction; self._operation_action_factory=PayloadReleaseAction
        data = params or {}

        # ── targets (0-2 valid GPS targets) ──
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list) or len(raw_targets) not in (0, 1, 2):
            raise ValueError("targets must contain 0, 1, or 2 entries")
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
        self.no_target_strategy = str(data.get("no_target_strategy") or "").strip()
        self.no_target_field_center: dict[str, float] | None = None
        if len(self.targets) == 0:
            if self.no_target_strategy != "field_center_direct_dual_release":
                raise ValueError("0 targets require no_target_strategy=field_center_direct_dual_release")
            raw_center = data.get("no_target_field_center")
            if not isinstance(raw_center, dict):
                raise ValueError("no_target_field_center must be an object")
            try:
                center = {
                    "x": float(raw_center["x"]),
                    "y": float(raw_center["y"]),
                    "altitude_m": float(raw_center["altitude_m"]),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("no_target_field_center requires finite x, y, altitude_m") from exc
            if not all(math.isfinite(value) for value in center.values()) or center["altitude_m"] <= 0.0:
                raise ValueError("no_target_field_center requires finite x, y, altitude_m > 0")
            self.no_target_field_center = center
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
            "field_center_direct_dual_release" if not self.targets
            else "single_target_dual_release" if len(self.targets) == 1
            else "dual_target_sequential"
        )

        # ── pre-validate merged servo outputs for dual release ──
        if self.execution_mode in {"single_target_dual_release", "field_center_direct_dual_release"}:
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

        # ── climb params ──
        self.climb_after_drop_m = float(data.get("climb_after_drop_m", 2.5))
        self.single_target_climb_after_release_m = float(
            data.get("single_target_climb_after_release_m", self.climb_after_drop_m)
        )
        if self.execution_mode == "single_target_dual_release":
            self.climb_after_drop_m = self.single_target_climb_after_release_m
        self.climb_tolerance_z_m = float(data.get("climb_tolerance_z_m", 0.1))
        self.climb_max_updates = int(data.get("climb_max_updates", 100))
        for name, val in (("climb_after_drop_m", self.climb_after_drop_m),
                          ("climb_tolerance_z_m", self.climb_tolerance_z_m)):
            if not math.isfinite(val) or val <= 0.0:
                raise ValueError(f"{name} must be finite and > 0, got {val}")
        if self.climb_max_updates < 1:
            raise ValueError("climb_max_updates must be >= 1")

        # ── limits ──
        self.goto_max_updates = int(data.get("goto_max_updates", 160))
        self.target_lock_max_updates = int(data.get("target_lock_max_updates", 40))
        self.align_descend_max_updates = int(data.get("align_descend_max_updates", 250))
        self.release_wait_updates = int(data.get("release_wait_updates", 5))
        self.release_wait_s = self._optional_positive_seconds(data.get("release_wait_s"))
        for name, val in (("goto_max_updates", self.goto_max_updates),
                          ("target_lock_max_updates", self.target_lock_max_updates),
                          ("align_descend_max_updates", self.align_descend_max_updates),
                          ("release_wait_updates", self.release_wait_updates)):
            if val < 1:
                raise ValueError(f"{name} must be >= 1")

        self.goto_cfg = dict(data.get("goto") or {})
        self.lock_cfg = dict(data.get("target_lock") or {})
        self.align_cfg = dict(data.get("align_descend") or {})
        self.lock_fallback_max_distance_m: float | None = None
        raw_lock_fallback = self.lock_cfg.get("fallback_max_match_distance_m")
        if raw_lock_fallback is not None:
            self.lock_fallback_max_distance_m = float(raw_lock_fallback)
            primary_lock_distance_m = float(self.lock_cfg.get("max_match_distance_m", 1.2))
            if (
                not math.isfinite(self.lock_fallback_max_distance_m)
                or self.lock_fallback_max_distance_m < primary_lock_distance_m
            ):
                raise ValueError(
                    "target_lock.fallback_max_match_distance_m must be finite and >= max_match_distance_m"
                )
        self.try_next_target_on_lock_failure = bool(
            self.lock_cfg.get("try_next_target_on_failure", False)
        )
        self.direct_release_when_lock_exhausted = bool(
            self.lock_cfg.get("direct_release_when_exhausted", False)
        )
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
        align_config["min_altitude_m"] = min_altitude_m
        self.align_cfg["config"] = align_config

        # ── state ──
        self.phase = "resolve_no_target" if self.execution_mode == "field_center_direct_dual_release" else "goto"
        self.target_index = 0
        self.payload_index = 0
        self.released_count = 0
        self.update_count_at_phase = 0
        self.sub_action: Any = None
        self._release_reason = ""
        self._failed_reason = ""
        self._climb_target_lat: float | None = None
        self._climb_target_lon: float | None = None
        self._lock_stage = "primary"
        self._skipped_lock_target_indices: list[int] = []

        self.started = True
        self.stopped = False


    def _sequence_reason(self,event):
        return {'goto':'gps_drop_goto','lock':'gps_drop_lock_searching','lock_start':'gps_drop_lock_start','align_start':'gps_drop_align_start','align':'gps_drop_align','align_inactive':'gps_drop_align_inactive','operation_start':'gps_drop_release_start','climb_start':'gps_drop_climb_start','climb':'gps_drop_climb','next':'gps_drop_next','done':'gps_drop_sequence_done','goto_timeout':'goto_timeout','goto_failed':'goto_failed','lock_failed':'no_lockable_drop_targets','align_timeout':'align_descend_timeout','operation_failed':'payload_release_failed','climb_timeout':'climb_timeout','climb_failed':'climb_goto_failed'}.get(event,event)
    def _sequence_namespace(self): return 'gps_drop'
    def _sequence_detail(self,done=False,extra=None):
        d={'phase':'release' if self.phase=='operation' else self.phase,'target_index':self.target_index,'payload_index':self.payload_index,'released_count':self.released_count,'target_count':len(self.targets),'payload_count':len(self.payloads),'release_reason':getattr(self,'_release_reason',''),'execution_mode':self.execution_mode,'dual_release':self.execution_mode in {'single_target_dual_release', 'field_center_direct_dual_release'}}; d.update(extra or {});
        if done:d['done']=True
        return d
    def _action_key(self,phase): return f'gps_drop_{phase}_{self.target_index}' if phase != 'align' else 'gps_drop_align'
    def _build_align_params(self,target):
        p=copy.deepcopy(self.align_cfg); c=dict(p.get('config') or {}); payload=self.payloads[self.payload_index]; c['payload_forward_m']=payload['payload_forward_m']; c['payload_right_m']=payload['payload_right_m']; p['config']=c; p['finish_altitude_m']=self.finish_altitude_m; return p
    def _on_align_sample(self,target,ctx,result): pass
    def _on_align_failure(self,event,target,ctx,result):
        # Only override for visual alignment timeout/loss errors.
        # Structural errors (missing altitude, not started, etc.) still fail.
        FORCE_RELEASE_SUB_REASONS = {'target_lost_timeout', 'align_descend_timeout'}
        if event == 'align_timeout':
            pass  # always force release on outer timeout
        elif event == 'align_failed':
            if result is None:
                return None  # should not happen, but fail normally
            sub_reason = result.reason or ''
            if sub_reason in FORCE_RELEASE_SUB_REASONS:
                pass  # force release on target lost or inner align timeout
            else:
                return None  # structural error — fail normally
        else:
            return None  # unknown event — fail normally

        stop_actions = self._stop_actions('align_force_release')
        self._operation_started = False
        self.sub_action = None
        self.update_count_at_phase = 0
        self.phase = 'operation'
        detail = self._sequence_detail()
        detail['align_timeout_release' if event == 'align_timeout' else 'align_failed_release'] = True
        detail['failure_event'] = event
        if result is not None:
            detail['align_sub_reason'] = result.reason
        return ActionResult(effects=ActionResult.typed(stop_actions), reason=self._sequence_reason('operation_start'),
                          detail=detail)
    def _start_operation(self,target):
        self.sub_action=self._operation_action_factory();
        common = {'release_wait_updates': self.release_wait_updates, 'priority': min(self.payloads[0].get('priority',5),self.payloads[1].get('priority',5)) if self.execution_mode in {'single_target_dual_release', 'field_center_direct_dual_release'} else self.payloads[self.payload_index].get('priority',5)}
        if self.release_wait_s is not None: common['release_wait_s'] = self.release_wait_s
        if self.execution_mode in {'single_target_dual_release', 'field_center_direct_dual_release'}: self.sub_action.start({'servo_outputs':self.dual_release_servo_outputs,'payload_id':'payload_1_and_2','target_id':target['target_id'], **common})
        else:
            p=self.payloads[self.payload_index]; self.sub_action.start({'servo_outputs':p['servo_outputs'],'payload_id':p['payload_id'],'target_id':target['target_id'], **common})

    @staticmethod
    def _optional_positive_seconds(raw: Any) -> float | None:
        if raw is None: return None
        try: value = float(raw)
        except (TypeError, ValueError) as exc: raise ValueError("release_wait_s must be finite and > 0") from exc
        if not math.isfinite(value) or value <= 0: raise ValueError("release_wait_s must be finite and > 0")
        return value
    def _update_operation_hook(self,ctx):
        r=self.sub_action.update(ctx)
        if r.failed:return r
        if not r.done:return ActionResult(effects=ActionResult.typed([self._zero_velocity_command()]+(r.actions or [])),reason='gps_drop_releasing',detail=self._sequence_detail())
        self._operation_hold=r.actions or []; return ActionResult(effects=ActionResult.typed([self._zero_velocity_command()]+self._operation_hold+[self._clear_continuous_command('release_done')]),done=True,reason='gps_drop_climb_start',detail=self._sequence_detail())
    def _operation_complete(self,target):
        if self.execution_mode in {'single_target_dual_release', 'field_center_direct_dual_release'}: self.released_count=2; self.payload_index=2
        else: self.released_count+=1; self.payload_index+=1

    def _update_resolve_no_target(self, context: dict[str, Any]) -> ActionResult:
        """Resolve the configured FIELD centre through the frozen runtime binding."""
        field_reference = context.get("field_reference")
        if not isinstance(field_reference, dict):
            return self._fail("goto_failed", reason="missing_field_reference_context")
        runtime_binding = field_reference.get("runtime_binding")
        geometry = runtime_binding.get("geometry") if isinstance(runtime_binding, dict) else None
        home = geometry.get("home") if isinstance(geometry, dict) else None
        try:
            if not (
                field_reference.get("is_confirmed") is True
                and field_reference.get("is_frozen") is True
                and field_reference.get("is_ready_for_field_to_gps") is True
                and field_reference.get("synced_to_runtime") is True
                and isinstance(runtime_binding, dict)
                and runtime_binding.get("state") == "applied"
                and isinstance(home, dict)
            ):
                raise FieldReferenceError("runtime field reference is not ready for FIELD to GPS conversion")
            point = field_to_gps_from_origin(
                self.no_target_field_center["x"], self.no_target_field_center["y"],
                self.no_target_field_center["altitude_m"],
                origin_lat=float(home["lat"]), origin_lon=float(home["lon"]),
                field_heading_yaw_rad=float(field_reference["field_heading_yaw_rad"]),
            )
        except (KeyError, TypeError, ValueError, FieldReferenceError) as exc:
            return self._fail("goto_failed", reason="no_target_field_center_resolve_failed")
        self.targets = [{"lat": point.lat, "lon": point.lon, "class_name": "", "target_id": "field_center_direct"}]
        return self._transition("goto", "goto", [])

    def _transition_after_goto(self, target, ctx, actions):
        if self.execution_mode == "field_center_direct_dual_release":
            self._operation_started = False
            return self._transition("operation", "operation_start", actions)
        self._lock_stage = "primary"
        return super()._transition_after_goto(target, ctx, actions)

    def _on_lock_success(self, target, ctx, result) -> None:
        if self._skipped_lock_target_indices and self.released_count == 0:
            self._switch_to_single_target_dual_release()

    def _on_lock_exhausted(self, target, ctx, result):
        if not self.direct_release_when_lock_exhausted:
            return None
        if self.released_count == 0:
            self._switch_to_single_target_dual_release()
        self._release_reason = "lock_candidates_exhausted_at_approach_altitude"
        self._operation_started = False
        return self._transition(
            "operation", "operation_start",
            self._ensure_stop_actions(result.actions or [], "lock_exhausted_release"),
        )

    def _switch_to_single_target_dual_release(self) -> None:
        self.execution_mode = "single_target_dual_release"
        self.dual_release_servo_outputs = _merge_servo_outputs(
            self.payloads[0], self.payloads[1]
        )
        self.climb_after_drop_m = self.single_target_climb_after_release_m

    def _transition_after_operation(self, target, ctx, actions):
        if self.execution_mode == "field_center_direct_dual_release":
            self.phase = "done"
            return ActionResult(
                effects=ActionResult.typed(self._ensure_stop_actions(actions or [], "field_center_release_done")),
                done=True,
                reason=self._sequence_reason("done"),
                detail=self._sequence_detail(done=True),
            )
        return super()._transition_after_operation(target, ctx, actions)

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
    return {'action_type':'flight_command','params':{'type':'flight_command','valid':True,'active':True,'enable_body':True,'vx_cmd':0.0,'vy_cmd':0.0,'vz_cmd':0.0,'yaw_rate_cmd':0.0,'yaw_rate_rad_s':0.0,'priority':3},'once':False}


def _clear_continuous_command(key_suffix: str = "") -> dict[str, Any]:
    # Preserve the externally asserted drop command key while sharing payload.
    return {'action_type':'clear_continuous_commands','params':{'clear_pending_local_position':False,'send_stop_first':True},'once':True,'key':f'gps_drop_clear_{key_suffix}'}


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
