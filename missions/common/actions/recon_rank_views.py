"""Atomic aggregation of Mission-captured reconnaissance views."""
from __future__ import annotations

from typing import Any
from guidance.recon_ranking import rank_recon_views
from .base import ActionModule
from .result import ActionResult


class ReconRankViewsAction(ActionModule):
    def __init__(self) -> None: self.reset()
    def start(self, params: dict[str, Any] | None = None) -> None:
        views = (params or {}).get("views", [])
        if not isinstance(views, list): raise ValueError("views must be a list")
        self.views, self.started, self.stopped = views, True, False
    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started: return ActionResult(failed=True, reason="action_not_started")
        if self.stopped: return ActionResult(done=True, reason="stopped")
        ranking = rank_recon_views(self.views)
        frame_count = sum(int(view.get("frame_count", 0)) for view in self.views if isinstance(view, dict))
        return ActionResult(done=True, reason="recon_views_ranked",
            detail={"ranking_mode": True, "ranking": ranking,
                    "scan_summary": {"scored_unique_frame_count": frame_count,
                                     "observed_unique_frame_count": frame_count}})
    def stop(self) -> None: self.stopped = True
    def reset(self) -> None: self.views, self.started, self.stopped = [], False, False
