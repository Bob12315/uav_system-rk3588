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
        self.goto_cfg=dict(data.get("goto") or {}); self.lock_cfg=dict(data.get("target_lock") or {}); self.align_cfg=dict(data.get("align_descend") or {}); self.observation_cfg=dict(data.get("observation") or {})
        self.sequence_kind="recon"; self.phase="goto"; self.target_index=0; self.sub_action=None; self.phase_updates=0; self.observations=[]; self.failure_reason=""; self.started=True; self.stopped=False

    def _detail(self,done=False): return {"phase":self.phase,"target_index":self.target_index,"target_count":len(self.targets),"observations":list(self.observations),"done":done}
    def stop(self): self.stopped=True
    def reset(self): self.targets=[]; self.observations=[]; self.phase="idle"; self.started=False; self.stopped=False
