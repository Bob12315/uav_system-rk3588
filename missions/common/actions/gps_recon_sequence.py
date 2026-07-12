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
from .recon_observation_accumulator import ReconObservationAccumulator


class GpsReconSequenceAction(GpsTargetSequenceCore, ActionModule):
    """GLOBAL goto → lock → align/observe → GLOBAL climb for each GPS target."""

    def __init__(self) -> None: self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        self._goto_action_factory=GotoWaypointAction; self._lock_action_factory=GpsTargetLockAction; self._align_action_factory=AlignDescendAction
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
        self.climb_after_drop_m=float(data.get("climb_after_drop_m", data.get("climb_after_observe_m",2.5))); self.climb_tolerance_z_m=float(data.get("climb_tolerance_z_m",.1))
        self.goto_max_updates=int(data.get("goto_max_updates",200)); self.target_lock_max_updates=int(data.get("target_lock_max_updates",60)); self.align_descend_max_updates=int(data.get("align_descend_max_updates",160)); self.climb_max_updates=int(data.get("climb_max_updates",100))
        self.goto_cfg=dict(data.get("goto") or {}); self.lock_cfg=dict(data.get("target_lock") or {}); self.align_cfg=dict(data.get("align_descend") or {}); self.observation_cfg=dict(data.get("observation") or {})
        self.phase="goto"; self.target_index=0; self.sub_action=None; self.update_count_at_phase=0; self.observations=[]; self._failed_reason=""; self.started=True; self.stopped=False; self.phase_history=["goto"]

    def _sequence_reason(self,event): return {'goto':'gps_recon_goto','lock':'gps_recon_lock_searching','lock_start':'gps_recon_lock_start','align_start':'gps_recon_align_start','align':'gps_recon_align','align_inactive':'gps_recon_align_inactive','operation_start':'gps_recon_operation_start','climb_start':'gps_recon_climb_start','climb':'gps_recon_climb','next':'gps_recon_next','done':'gps_recon_sequence_done','lock_failed':'no_lockable_recon_targets','align_timeout':'align_descend_timeout','climb_failed':'climb_goto_failed'}.get(event,event)
    def _sequence_namespace(self): return 'gps_recon'
    def _sequence_detail(self,done=False,extra=None):
        d={'phase':self.phase,'target_index':self.target_index,'target_count':len(self.targets),'observations':list(self.observations)}; d.update(extra or {});
        if done:d['done']=True
        return d
    def _action_key(self,phase): return f'gps_recon_{phase}_{self.target_index}' if phase!='align' else 'gps_recon_align'
    def _build_align_params(self,target):
        self.observer=ReconObservationAccumulator(); self.observer.start_target(target,self.target_index,self.observation_cfg)
        p=copy.deepcopy(self.align_cfg); c=dict(p.get('config') or {}); c.update(payload_offset_enabled=False,payload_forward_m=0.,payload_right_m=0.); p['config']=c; p['finish_altitude_m']=self.finish_altitude_m; return p
    def _on_align_sample(self,target,ctx,result): self.observer.sample((result.detail or {}).get('height_m'),ctx) if hasattr(self,'observer') else None
    def _start_operation(self,target): pass
    def _update_operation_hook(self,ctx):
        item=self.observer.finalize(self._last_align_reason,self._last_align_detail); self.observations.append(item); return ActionResult(done=True,reason='gps_recon_operation_done',detail=self._sequence_detail())
    def _operation_complete(self,target): pass
