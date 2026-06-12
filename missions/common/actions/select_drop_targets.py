from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .base import ActionModule
from .result import ActionResult


DEFAULT_SCORE_TABLE = {
    "bucket_1": 500,
    "bucket_2": 300,
    "bucket_3": 100,
    "bucket": 50,
}
DEFAULT_CLASS_ORDER = ["bucket_1", "bucket_2", "bucket_3", "bucket"]


@dataclass(slots=True)
class _Candidate:
    original: dict[str, Any]
    index: int
    id: str
    target_id: str | None
    class_name: str
    local_x: float
    local_y: float
    score: float
    seen_count: int
    raw_count: int
    weight: float
    order_index: int
    zone_distance_m: float | None


class SelectDropTargetsAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        objects = data.get("objects", [])
        if not isinstance(objects, list):
            raise ValueError("objects must be a list")
        target_count = int(data.get("target_count", 2))
        min_seen_count = int(data.get("min_seen_count", 2))
        min_raw_count = int(data.get("min_raw_count", 0))
        min_weight = float(data.get("min_weight", 0.0))
        deduplicate_radius_m = float(data.get("deduplicate_radius_m", 0.35))
        if target_count < 1:
            raise ValueError("target_count must be at least 1")
        if min_seen_count < 0:
            raise ValueError("min_seen_count must be non-negative")
        if min_raw_count < 0:
            raise ValueError("min_raw_count must be non-negative")
        if min_weight < 0.0:
            raise ValueError("min_weight must be non-negative")
        if deduplicate_radius_m < 0.0:
            raise ValueError("deduplicate_radius_m must be non-negative")

        score_table = data.get("score_table", DEFAULT_SCORE_TABLE)
        if not isinstance(score_table, dict):
            raise ValueError("score_table must be a dict")
        prefer_class_order = data.get("prefer_class_order", DEFAULT_CLASS_ORDER)
        if not isinstance(prefer_class_order, (list, tuple)):
            raise ValueError("prefer_class_order must be a list or tuple")

        self.objects = list(objects)
        self.target_count = target_count
        self.score_table = {str(key): float(value) for key, value in score_table.items()}
        self.min_seen_count = min_seen_count
        self.min_raw_count = min_raw_count
        self.min_weight = min_weight
        self.require_local_xy = self._bool_param(data.get("require_local_xy", True), "require_local_xy")
        self.deduplicate_radius_m = deduplicate_radius_m
        self.prefer_class_order = [str(value) for value in prefer_class_order]
        self.key = str(data.get("key") or "").strip() or "select_drop_targets"
        self.zone_center = self._zone_center(data.get("zone_center"))
        self.started = True
        self.stopped = False
        self.done = False
        self.failed = False
        self.last_result = None

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._base_detail([], []))
        if self.done or self.failed:
            return self._clone_result(self.last_result)

        result = self._select()
        self.done = result.done
        self.failed = result.failed
        self.last_result = result
        return result

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.objects: list[Any] = []
        self.target_count = 2
        self.score_table = dict(DEFAULT_SCORE_TABLE)
        self.min_seen_count = 2
        self.min_raw_count = 0
        self.min_weight = 0.0
        self.require_local_xy = True
        self.deduplicate_radius_m = 0.35
        self.prefer_class_order = list(DEFAULT_CLASS_ORDER)
        self.zone_center: tuple[float, float] | None = None
        self.key = "select_drop_targets"
        self.started = False
        self.stopped = False
        self.done = False
        self.failed = False
        self.last_result: ActionResult | None = None

    def _select(self) -> ActionResult:
        if not self.objects:
            detail = self._base_detail([], [])
            return ActionResult(failed=True, reason="no_drop_objects", detail=detail)

        candidates: list[_Candidate] = []
        rejected: list[dict[str, Any]] = []
        for index, item in enumerate(self.objects):
            if not isinstance(item, dict):
                rejected.append({"id": f"target_{index}", "class_name": "bucket", "reason": "invalid_object"})
                continue
            candidate, rejection = self._candidate(item, index)
            if rejection is not None:
                rejected.append(rejection)
            elif candidate is not None:
                candidates.append(candidate)

        if not candidates:
            detail = self._base_detail([], rejected)
            return ActionResult(failed=True, reason="no_valid_drop_targets", detail=detail)

        ordered = sorted(candidates, key=self._sort_key)
        selected: list[_Candidate] = []
        for candidate in ordered:
            duplicate_distance = self._duplicate_distance(candidate, selected)
            if duplicate_distance is not None:
                rejected.append(
                    {
                        "id": candidate.id,
                        "class_name": candidate.class_name,
                        "reason": "duplicate_near_selected",
                        "distance_m": duplicate_distance,
                    }
                )
                continue
            selected.append(candidate)
            if len(selected) >= self.target_count:
                break

        if len(selected) < self.target_count:
            detail = self._base_detail(selected, rejected, candidate_count=len(candidates))
            return ActionResult(failed=True, reason="not_enough_drop_targets", detail=detail)

        detail = self._base_detail(selected, rejected, candidate_count=len(candidates))
        return ActionResult(done=True, reason="drop_targets_selected", detail=detail)

    def _candidate(
        self,
        obj: dict[str, Any],
        index: int,
    ) -> tuple[_Candidate | None, dict[str, Any] | None]:
        target_id = None if obj.get("target_id") is None else str(obj.get("target_id"))
        object_id = str(obj.get("id") or target_id or f"target_{index}")
        class_name = str(obj.get("class_name") or obj.get("label") or "bucket")
        base_rejection = {"id": object_id, "class_name": class_name}

        xy = self._xy(obj)
        if xy is None:
            return None, {**base_rejection, "reason": "missing_xy"}
        local_x, local_y = xy
        if not math.isfinite(local_x) or not math.isfinite(local_y):
            return None, {**base_rejection, "reason": "invalid_xy"}

        seen_count = self._int_value(
            obj.get("seen_count", obj.get("count", obj.get("raw_count", 0))),
            default=0,
        )
        raw_count = self._int_value(obj.get("raw_count", seen_count), default=seen_count)
        weight = self._float_value(obj.get("weight", 0.0), default=0.0)
        if seen_count < self.min_seen_count:
            return None, {**base_rejection, "reason": "low_seen_count"}
        if raw_count < self.min_raw_count:
            return None, {**base_rejection, "reason": "low_raw_count"}
        if weight < self.min_weight:
            return None, {**base_rejection, "reason": "low_weight"}
        if class_name not in self.score_table:
            return None, {**base_rejection, "reason": "unknown_class"}

        order_index = self.prefer_class_order.index(class_name) if class_name in self.prefer_class_order else len(self.prefer_class_order)
        zone_distance_m = self._zone_distance(local_x, local_y)
        return (
            _Candidate(
                original=obj,
                index=index,
                id=object_id,
                target_id=target_id,
                class_name=class_name,
                local_x=local_x,
                local_y=local_y,
                score=self.score_table[class_name],
                seen_count=seen_count,
                raw_count=raw_count,
                weight=weight,
                order_index=order_index,
                zone_distance_m=zone_distance_m,
            ),
            None,
        )

    def _base_detail(
        self,
        selected: list[_Candidate],
        rejected: list[dict[str, Any]],
        *,
        candidate_count: int | None = None,
    ) -> dict[str, Any]:
        selected_targets = [self._selected_dict(candidate, rank) for rank, candidate in enumerate(selected, start=1)]
        return {
            "selected_targets": selected_targets,
            "candidate_count": len(selected) if candidate_count is None else candidate_count,
            "selected_count": len(selected_targets),
            "rejected_count": len(rejected),
            "rejected_objects": rejected,
            "score_table": dict(self.score_table),
            "target_count": self.target_count,
            "key": self.key,
        }

    def _selected_dict(self, candidate: _Candidate, rank: int) -> dict[str, Any]:
        data = {
            "id": candidate.id,
            "target_id": candidate.target_id,
            "class_name": candidate.class_name,
            "local_x": candidate.local_x,
            "local_y": candidate.local_y,
            "x": candidate.local_x,
            "y": candidate.local_y,
            "score": candidate.score,
            "seen_count": candidate.seen_count,
            "count": candidate.seen_count,
            "raw_count": candidate.raw_count,
            "weight": candidate.weight,
            "track_ids": list(candidate.original.get("track_ids") or []),
            "rank": rank,
        }
        if "local_z" in candidate.original:
            data["local_z"] = candidate.original["local_z"]
        elif "z" in candidate.original:
            data["local_z"] = candidate.original["z"]
        return data

    def _sort_key(self, candidate: _Candidate) -> tuple[float, int, int, int, float, float, int]:
        zone_distance = candidate.zone_distance_m if candidate.zone_distance_m is not None else 0.0
        return (
            -candidate.score,
            candidate.order_index,
            -candidate.seen_count,
            -candidate.raw_count,
            -candidate.weight,
            zone_distance,
            candidate.index,
        )

    def _duplicate_distance(self, candidate: _Candidate, selected: list[_Candidate]) -> float | None:
        if self.deduplicate_radius_m == 0.0:
            return None
        for item in selected:
            distance = math.hypot(candidate.local_x - item.local_x, candidate.local_y - item.local_y)
            if distance < self.deduplicate_radius_m:
                return distance
        return None

    def _xy(self, obj: dict[str, Any]) -> tuple[float, float] | None:
        x_value = obj.get("local_x")
        y_value = obj.get("local_y")
        if x_value is None or y_value is None:
            if self.require_local_xy:
                x_value = obj.get("x")
                y_value = obj.get("y")
            else:
                x_value = obj.get("x", x_value)
                y_value = obj.get("y", y_value)
        if x_value is None or y_value is None:
            return None
        try:
            return float(x_value), float(y_value)
        except (TypeError, ValueError):
            return float("nan"), float("nan")

    def _zone_center(self, value: Any) -> tuple[float, float] | None:
        if not isinstance(value, dict):
            return None
        try:
            x = float(value["x"])
            y = float(value["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        return x, y

    def _zone_distance(self, x: float, y: float) -> float | None:
        if self.zone_center is None:
            return None
        return math.hypot(x - self.zone_center[0], y - self.zone_center[1])

    def _clone_result(self, result: ActionResult | None) -> ActionResult:
        if result is None:
            return ActionResult(failed=True, reason="missing_cached_result")
        return ActionResult(
            actions=list(result.actions),
            done=result.done,
            failed=result.failed,
            reason=result.reason,
            detail=dict(result.detail),
        )

    def _bool_param(self, value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"{name} must be a bool")

    def _int_value(self, value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _float_value(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
