"""Shared GPS target flight lifecycle; wrappers inject business operations."""
from __future__ import annotations
import copy, math
from typing import Any
from telemetry_link.frames import GLOBAL_RELATIVE_ALT_INT
from .result import ActionResult

class GpsTargetSequenceCore:
    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started: return ActionResult(failed=True, reason="action_not_started")
        if self.stopped: return ActionResult(actions=self._stop_actions("1"), done=True, reason="stopped", detail=self._sequence_detail(done=True))
        if self.phase == "done": return ActionResult(done=True, reason=self._sequence_reason("done"), detail=self._sequence_detail(done=True))
        if self.phase == "failed": return ActionResult(failed=True, reason=self._failed_reason, detail=self._sequence_detail())
        self.update_count_at_phase += 1
        return getattr(self, f"_update_{self.phase}")(context or {})
    def stop(self): self.stopped=True
    def reset(self):
        self.targets=[]; self.phase="idle"; self.target_index=0; self.sub_action=None; self.update_count_at_phase=0; self.started=False; self.stopped=False; self._failed_reason=""; self._climb_target_lat=None; self._climb_target_lon=None; self._last_align_reason=""; self._last_align_detail={}; self.phase_history=[]
    def _goto_params(self, target, altitude, phase):
        if phase == "climb": return {"lat":target["lat"],"lon":target["lon"],"altitude_m":altitude,"target_frame":"global","waypoint_mode":"absolute","yaw_mode":"field_heading","frame":GLOBAL_RELATIVE_ALT_INT,"tolerance_xy_m":99.0,"tolerance_z_m":self.climb_tolerance_z_m,"min_hold_updates":1,"require_velocity_valid":False,"key":self._action_key("climb")}
        return {"lat":target["lat"],"lon":target["lon"],"altitude_m":altitude,"target_frame":"global","waypoint_mode":"absolute","yaw_mode":"field_heading","frame":GLOBAL_RELATIVE_ALT_INT,"tolerance_xy_m":self.goto_cfg.get("tolerance_xy_m",.25),"tolerance_z_m":self.goto_cfg.get("tolerance_z_m",.3),"min_hold_updates":self.goto_cfg.get("min_hold_updates",3),"require_velocity_valid":self.goto_cfg.get("require_velocity_valid",True),"max_horizontal_speed_mps":self.goto_cfg.get("max_horizontal_speed_mps",.15),"max_vertical_speed_mps":self.goto_cfg.get("max_vertical_speed_mps",.1),"key":self._action_key("goto")}
    def _update_goto(self, ctx):
        t=self.targets[self.target_index]
        if self.sub_action is None:
            self._climb_target_lat,self._climb_target_lon=t['lat'],t['lon']; self.sub_action=self._goto_action_factory(); self.sub_action.start(self._goto_params(t,self.approach_altitude_m,'goto')); self.update_count_at_phase=0
        if self.update_count_at_phase > self.goto_max_updates:return self._fail('goto_timeout')
        r=self.sub_action.update(ctx)
        if r.failed:return self._fail('goto_failed')
        if not r.done:return ActionResult(actions=r.actions,reason=self._sequence_reason('goto'),detail=self._sequence_detail())
        return self._transition_after_goto(t, ctx, r.actions)
    def _update_lock(self,ctx):
        t=self.targets[self.target_index]
        if self.sub_action is None:
            self.sub_action=self._lock_action_factory(); self.sub_action.start({"target":{"id":t['target_id'],"lat":t['lat'],"lon":t['lon'],"class_name":t.get('class_name','')},"max_match_distance_m":self.lock_cfg.get('max_match_distance_m',1.2),"max_updates":self.target_lock_max_updates,"min_confidence":self.lock_cfg.get('min_confidence',.35),"class_names":self.lock_cfg.get('class_names'),"camera":self.lock_cfg.get('camera',{}),"detection_source":self.lock_cfg.get('detection_source','scene'),"require_track_id":self.lock_cfg.get("require_track_id",True)}); self.update_count_at_phase=0
        r=self.sub_action.update(ctx)
        if r.failed:return self._fail('lock_failed',self._stop_actions('lock_fail'))
        if not r.done:return ActionResult(actions=r.actions,reason=self._sequence_reason('lock'),detail=self._sequence_detail(extra={'lock':r.detail}))
        return self._transition('align','align_start',r.actions)
    def _update_align(self,ctx):
        t=self.targets[self.target_index]
        if self.sub_action is None:
            self.sub_action=self._align_action_factory(); self.sub_action.start(self._build_align_params(t)); self.update_count_at_phase=0
        if self.update_count_at_phase > self.align_descend_max_updates:
            override=self._on_align_failure('align_timeout',t,ctx,None)
            if override is not None:return override
            return self._fail('align_timeout',self._stop_actions('timeout'))
        r=self.sub_action.update(ctx); command=(r.detail or {}).get('command'); self._on_align_sample(t,ctx,r)
        if r.failed:
            override=self._on_align_failure('align_failed',t,ctx,r)
            if override is not None:return override
            return self._fail('align_failed',self._stop_actions('align_fail'),r.reason)
        if not r.done and isinstance(command,dict) and (not command.get('valid') or not command.get('active')): return ActionResult(actions=self._stop_actions('align_inactive'),reason=self._sequence_reason('align_inactive'),detail=self._sequence_detail(extra={'align':r.detail}))
        if not r.done and command is None: return ActionResult(actions=[],reason=self._sequence_reason('align'),detail=self._sequence_detail(extra={'align':r.detail}))
        if not r.done:return ActionResult(actions=[{'action_type':'flight_command','params':dict(command),'once':False,'key':self._action_key('align'),'priority':5}],reason=self._sequence_reason('align'),detail=self._sequence_detail(extra={'align':r.detail}))
        self._last_align_reason=r.reason; self._last_align_detail=copy.deepcopy(r.detail or {}); self._operation_started = False
        return self._transition('operation','operation_start',self._stop_actions('aligned'))
    def _update_operation(self,ctx):
        if not getattr(self, "_operation_started", False):
            self._start_operation(self.targets[self.target_index])
            self._operation_started = True
        r=self._update_operation_hook(ctx)
        if r.failed:return self._fail('operation_failed',self._ensure_stop_actions(r.actions or [],'failed'))
        if not r.done:return r
        self._operation_complete(self.targets[self.target_index]); return self._transition_after_operation(self.targets[self.target_index], ctx, r.actions)
    def _update_climb(self,ctx):
        t=self.targets[self.target_index]
        if self.sub_action is None:
            self.sub_action=self._goto_action_factory(); self.sub_action.start(self._goto_params(t,self.climb_after_drop_m,'climb')); self.update_count_at_phase=0
        altitude=self._current_altitude_m(ctx)
        if altitude is not None and altitude >= self.climb_after_drop_m-self.climb_tolerance_z_m:return self._complete_climb()
        if self.update_count_at_phase > self.climb_max_updates:return self._fail('climb_timeout',self._stop_actions('climb_timeout'))
        r=self.sub_action.update(ctx)
        if r.failed:return self._fail('climb_failed',self._stop_actions('climb_fail'))
        altitude=self._current_altitude_m(ctx)
        if altitude is not None and altitude >= self.climb_after_drop_m-self.climb_tolerance_z_m:return self._complete_climb()
        return ActionResult(actions=r.actions,reason=self._sequence_reason('climb'),detail=self._sequence_detail(extra={'altitude_m':altitude}))
    def _complete_climb(self):
        if self.target_index+1 < len(self.targets): self.target_index+=1; return self._transition('goto','next',self._stop_actions('climb_done'))
        self.phase='done'; return ActionResult(actions=self._stop_actions('climb_done'),done=True,reason=self._sequence_reason('done'),detail=self._sequence_detail(done=True))
    def _transition(self,phase,event,actions=None): self.phase=phase; self.phase_history.append(phase); self.sub_action=None; self.update_count_at_phase=0; return ActionResult(actions=actions or [],reason=self._sequence_reason(event),detail=self._sequence_detail())
    def _fail(self,event,actions=None,reason=None): self.phase='failed'; self._failed_reason=reason or self._sequence_reason(event); self.sub_action=None; return ActionResult(actions=actions if actions is not None else self._stop_actions('failed'),failed=True,reason=self._failed_reason,detail=self._sequence_detail())
    def _on_align_failure(self,event,target,ctx,result):
        """Hook called before _fail on align timeout/failure. Return an ActionResult to override the default _fail behaviour; return None to proceed with the normal _fail path."""
        return None
    def _transition_after_goto(self, target, ctx, actions):
        return self._transition('lock', 'lock_start', actions)
    def _transition_after_operation(self, target, ctx, actions):
        return self._transition('climb', 'climb_start', actions)
    def _current_altitude_m(self,c):
        d=c.get('drone',{});
        for src,names in ((d,('relative_altitude','relative_altitude_m')),(c,('relative_altitude','relative_altitude_m','altitude_m'))):
            if isinstance(src,dict):
                for n in names:
                    try:
                        v=float(src[n]);
                        if math.isfinite(v) and v>=0:return v
                    except (KeyError,TypeError,ValueError):pass
        return None
    def _stop_actions(self,key): return [self._zero_velocity_command(),self._clear_continuous_command(key)]
    def _ensure_stop_actions(self,actions,key):
        items=list(actions); has_zero=any(isinstance(a,dict) and a.get('action_type')=='flight_command' and all(a.get('params',{}).get(k) == v for k,v in {'valid':True,'active':True,'enable_body':True,'vx_cmd':0.0,'vy_cmd':0.0,'vz_cmd':0.0,'yaw_rate_cmd':0.0,'yaw_rate_rad_s':0.0}.items()) for a in items); has_clear=any(isinstance(a,dict) and a.get('action_type')=='clear_continuous_commands' and a.get('params',{}).get('send_stop_first') is True and str(a.get('key','')).startswith(f'{self._sequence_namespace()}_clear_') for a in items)
        if not has_zero: items.insert(0,self._zero_velocity_command())
        if not has_clear: items.append(self._clear_continuous_command(key))
        return items
    def _zero_velocity_command(self): return {'action_type':'flight_command','params':{'type':'flight_command','valid':True,'active':True,'enable_body':True,'vx_cmd':0.,'vy_cmd':0.,'vz_cmd':0.,'yaw_rate_cmd':0.,'yaw_rate_rad_s':0.,'priority':3},'once':False}
    def _clear_continuous_command(self,key): return {'action_type':'clear_continuous_commands','params':{'clear_pending_local_position':False,'send_stop_first':True},'once':True,'key':f'{self._sequence_namespace()}_clear_{key}'}
