from __future__ import annotations

from typing import Any

from .base import ActionModule
from .result import ActionResult


class BuildReconReportAction(ActionModule):
    """Aggregate individual recon observe results into a single report.

    Pure data action — no flight commands, no detection logic.
    """

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        items = data.get("items", [])
        if not isinstance(items, list):
            raise ValueError("items must be a list")
        self.items = list(items)
        self.started = True
        self.stopped = False
        self._done = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped")
        if self._done:
            return ActionResult(done=True, reason="report_built", detail=self._detail())

        barrels: list[dict[str, Any]] = []
        detected_count = 0
        blank_count = 0
        skipped_count = 0
        failed_count = 0

        for item in self.items:
            if not isinstance(item, dict):
                skipped_count += 1
                barrels.append({"status": "skipped_missing_target", "content": "blank", "confidence": 0.0})
                continue
            status = str(item.get("status", ""))
            barrel = {**item,
                "id": str(item.get("target_id") or item.get("id") or ""),
                "local_x": item.get("local_x"),
                "local_y": item.get("local_y"),
                "content": str(item.get("content", "blank")),
                "confidence": float(item.get("confidence", 0.0)),
                "status": status,
            }
            if status in {"detected", "confirmed"}:
                detected_count += 1
            elif status == "failed":
                failed_count += 1
            elif status == "skipped_missing_target":
                skipped_count += 1
            else:
                blank_count += 1
            barrels.append(barrel)

        self._report = {
            "recon_report": {"barrels": barrels, "targets": barrels,
                "selected_count": len(self.items), "attempted_count": len(barrels),
                "confirmed_count": detected_count, "blank_count": blank_count,
                "failed_count": failed_count, "completed": failed_count == 0,
                "completion_reason": "report_built"},
            "barrel_count": len(barrels),
            "detected_count": detected_count,
            "blank_count": blank_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        }
        self._done = True
        return ActionResult(done=True, reason="report_built", detail=self._detail())

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.items: list[Any] = []
        self._report: dict[str, Any] = {}
        self.started = False
        self.stopped = False
        self._done = False

    def _detail(self) -> dict[str, Any]:
        return dict(self._report)
