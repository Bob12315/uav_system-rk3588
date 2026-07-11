"""GPS-first recon target sequence using the drop-flow control primitives."""
from __future__ import annotations

import copy
import math
from typing import Any

from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT

from .align_descend import AlignDescendAction
from .base import ActionModule
from .gps_target_lock import GpsTargetLockAction
from .gps_target_sequence_core import GpsTargetSequenceCore
from .goto_waypoint import GotoWaypointAction
from .result import ActionResult


class GpsReconSequenceAction(GpsTargetSequenceCore, ActionModule):
    """GLOBAL goto → lock → align/observe → GLOBAL climb for each GPS target."""

    def __init__(self) -> None: self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}; raw = data.get("targets", [])
        if not isinstance(raw, list) or not raw: raise ValueError("targets must be a non-empty list")
        self.targets=[]
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or item.get("valid", True) is False: continue
            try: lat, lon = float(item["lat"]), float(item["lon"])
            except (KeyError, TypeError, ValueError): continue
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180): continue
            target=dict(item); target.update({"lat":lat,"lon":lon,"target_id":str(item.get("target_id") or item.get("id") or f"recon_{index}")}); self.targets.append(target)
        if not self.targets: raise ValueError("at least one valid GPS target required")
        self.approach_altitude_m=float(data.get("approach_altitude_m", 2.5)); self.finish_altitude_m=float(data.get("finish_altitude_m",1.2))
        self.climb_after_observe_m=float(data.get("climb_after_observe_m", data.get("climb_after_drop_m",2.5))); self.climb_tolerance_z_m=float(data.get("climb_tolerance_z_m",.1))
        self.goto_max_updates=int(data.get("goto_max_updates",200)); self.target_lock_max_updates=int(data.get("target_lock_max_updates",60)); self.align_descend_max_updates=int(data.get("align_descend_max_updates",160)); self.climb_max_updates=int(data.get("climb_max_updates",100))
        self.goto_cfg=dict(data.get("goto") or {}); self.lock_cfg=dict(data.get("target_lock") or {}); self.align_cfg=dict(data.get("align_descend") or {})
        self.phase="goto"; self.target_index=0; self.sub_action=None; self.phase_updates=0; self.observations=[]; self.failure_reason=""; self.started=True; self.stopped=False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started: return ActionResult(failed=True,reason="action_not_started")
        if self.stopped: return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("stopped")],done=True,reason="stopped",detail=self._detail())
        if self.phase == "done": return ActionResult(done=True,reason="gps_recon_sequence_done",detail=self._detail(done=True))
        if self.phase == "failed": return ActionResult(failed=True,reason=self.failure_reason,detail=self._detail())
        self.phase_updates += 1; ctx=context or {}
        return getattr(self, f"_update_{self.phase}")(ctx)

    def _goto(self, altitude: float, key: str) -> GotoWaypointAction:
        t=self.targets[self.target_index]; a=GotoWaypointAction(); a.start({"lat":t["lat"],"lon":t["lon"],"altitude_m":altitude,"target_frame":"global","waypoint_mode":"absolute","yaw_mode":"field_heading","frame":GLOBAL_RELATIVE_ALT_INT,"tolerance_xy_m":self.goto_cfg.get("tolerance_xy_m",.25),"tolerance_z_m":self.goto_cfg.get("tolerance_z_m",.3),"min_hold_updates":self.goto_cfg.get("min_hold_updates",3),"require_velocity_valid":self.goto_cfg.get("require_velocity_valid",True),"max_horizontal_speed_mps":self.goto_cfg.get("max_horizontal_speed_mps",.15),"max_vertical_speed_mps":self.goto_cfg.get("max_vertical_speed_mps",.1),"key":key}); return a
    def _transition(self, phase: str, reason: str, actions=None) -> ActionResult:
        self.phase=phase; self.sub_action=None; self.phase_updates=0; return ActionResult(actions=actions or [],reason=reason,detail=self._detail())
    def _fail(self, reason: str) -> ActionResult:
        self.phase="failed"; self.failure_reason=reason; self.sub_action=None; return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("failed")],failed=True,reason=reason,detail=self._detail())
    def _update_goto(self, ctx):
        if self.sub_action is None: self.sub_action=self._goto(self.approach_altitude_m,f"gps_recon_goto_{self.target_index}"); self.phase_updates=0
        if self.phase_updates > self.goto_max_updates: return self._fail("goto_timeout")
        r=self.sub_action.update(ctx)
        if r.failed: return self._fail("goto_failed")
        return self._transition("lock","gps_recon_lock_start",r.actions) if r.done else ActionResult(actions=r.actions,reason="gps_recon_goto",detail=self._detail())
    def _update_lock(self, ctx):
        if self.sub_action is None:
            t=self.targets[self.target_index]; self.sub_action=GpsTargetLockAction(); self.sub_action.start({"target":{"id":t["target_id"],"lat":t["lat"],"lon":t["lon"],"class_name":str(t.get("class_name", ""))},"max_match_distance_m":self.lock_cfg.get("max_match_distance_m",1.2),"max_updates":self.target_lock_max_updates,"min_confidence":self.lock_cfg.get("min_confidence",.35),"class_names":self.lock_cfg.get("class_names"),"camera":self.lock_cfg.get("camera",{}),"detection_source":self.lock_cfg.get("detection_source","scene")}); self.phase_updates=0
        r=self.sub_action.update(ctx)
        if r.failed: return self._fail("no_lockable_recon_targets")
        return self._transition("align","gps_recon_align_start",r.actions) if r.done else ActionResult(actions=r.actions,reason="gps_recon_lock_searching",detail=self._detail())
    def _update_align(self, ctx):
        if self.sub_action is None:
            p=copy.deepcopy(self.align_cfg); cfg=dict(p.get("config") or {}); cfg["payload_offset_enabled"]=False; cfg["payload_forward_m"]=0.; cfg["payload_right_m"]=0.; p["config"]=cfg; p["finish_altitude_m"]=self.finish_altitude_m; self.sub_action=AlignDescendAction(); self.sub_action.start(p); self.phase_updates=0
        if self.phase_updates > self.align_descend_max_updates: return self._fail("align_descend_timeout")
        r=self.sub_action.update(ctx); command=(r.detail or {}).get("command")
        if r.failed: return self._fail(r.reason or "align_failed")
        self._observe(ctx)
        if r.done: return self._transition("climb","gps_recon_climb_start",[self.zero_velocity_command(),self.clear_continuous_command("observed")])
        if isinstance(command,dict) and command.get("valid") and command.get("active"): return ActionResult(actions=[{"action_type":"flight_command","params":dict(command),"once":False,"key":"gps_recon_align","priority":5}],reason="gps_recon_align",detail=self._detail())
        return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("align_inactive")],reason="gps_recon_align_inactive",detail=self._detail())
    def _observe(self, ctx):
        dets=((ctx.get("scene") or {}).get("detections") or []) if isinstance(ctx.get("scene"),dict) else []
        best=max((d for d in dets if isinstance(d,dict)),key=lambda d:float(d.get("confidence",0) or 0),default=None)
        if best is not None: self._last_observation={"status":"confirmed","hazard_label":str(best.get("class_name") or best.get("label") or ""),"confidence_max":float(best.get("confidence",0) or 0),"confidence_mean":float(best.get("confidence",0) or 0),"observation_count":1,"reason":"observed"}
        elif not hasattr(self,"_last_observation"): self._last_observation={"status":"blank","hazard_label":"","confidence_max":0.,"confidence_mean":0.,"observation_count":0,"reason":"no_reliable_hazard"}
    def _update_climb(self, ctx):
        if self.sub_action is None: self.sub_action=self._goto(self.climb_after_observe_m,f"gps_recon_climb_{self.target_index}"); self.phase_updates=0
        altitude=self.current_altitude_m(ctx)
        if altitude is not None and altitude >= self.climb_after_observe_m-self.climb_tolerance_z_m:
            self.observations.append({**self.targets[self.target_index],**getattr(self,"_last_observation",{})}); delattr(self,"_last_observation") if hasattr(self,"_last_observation") else None
            if self.target_index+1 == len(self.targets): self.phase="done"; return ActionResult(actions=[self.zero_velocity_command(),self.clear_continuous_command("climb_done")],done=True,reason="gps_recon_sequence_done",detail=self._detail(done=True))
            self.target_index+=1; return self._transition("goto","gps_recon_next",[self.zero_velocity_command(),self.clear_continuous_command("climb_done")])
        if self.phase_updates > self.climb_max_updates: return self._fail("climb_timeout")
        r=self.sub_action.update(ctx)
        return self._fail("climb_goto_failed") if r.failed else ActionResult(actions=r.actions,reason="gps_recon_climb",detail=self._detail())
    def _detail(self,done=False): return {"phase":self.phase,"target_index":self.target_index,"target_count":len(self.targets),"observations":list(self.observations),"done":done}
    def stop(self): self.stopped=True
    def reset(self): self.targets=[]; self.observations=[]; self.phase="idle"; self.started=False; self.stopped=False
