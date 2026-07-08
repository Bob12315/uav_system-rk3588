from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .base import ActionModule
from .result import ActionResult
from app.coordinate_transform import field_to_local_ned
from app.field_reference import FieldReference


DEFAULT_CLASSES = ["bucket_1", "bucket_2", "bucket_3", "bucket", "recon_bucket", "white_bucket"]


@dataclass(slots=True)
class _Candidate:
    original: dict[str, Any]
    index: int
    object_id: str
    class_name: str
    x: float
    y: float
    seen_count: int
    raw_count: int
    weight: float
    zone_distance_m: float


class SelectReconTargetsAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        objects = data.get("objects", [])
        if not isinstance(objects, list):
            raise ValueError("objects must be a list")
        self.target_count = int(data.get("target_count", 5))
        self.min_seen_count = int(data.get("min_seen_count", 1))
        self.min_raw_count = int(data.get("min_raw_count", 0))
        self.min_weight = float(data.get("min_weight", 0.0))
        self.deduplicate_radius_m = float(data.get("deduplicate_radius_m", 0.45))
        if self.target_count < 1:
            raise ValueError("target_count must be at least 1")
        if min(self.min_seen_count, self.min_raw_count) < 0 or self.min_weight < 0.0:
            raise ValueError("selection thresholds must be non-negative")
        if self.deduplicate_radius_m < 0.0:
            raise ValueError("deduplicate_radius_m must be non-negative")
        classes = data.get("class_names", DEFAULT_CLASSES)
        if not isinstance(classes, (list, tuple, set)):
            raise ValueError("class_names must be a list, tuple, or set")
        self.class_names = {str(value) for value in classes}
        self.allow_fewer = self._bool_value(data.get("allow_fewer", True), "allow_fewer")
        self.zone_center = self._zone_center(data.get("zone_center"))
        self.zone_center_mode = str(data.get("zone_center_mode", "local"))
        if self.zone_center_mode not in ("local", "field"):
            raise ValueError("zone_center_mode must be 'local' or 'field'")
        self.objects = list(objects)
        self.started = True
        self.stopped = False
        self.last_result = None

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._detail([], [], 0))
        if self.last_result is not None:
            return self.last_result

        zone_center = self.zone_center
        if self.zone_center_mode == "field":
            ctx = context or {}
            if not bool(ctx.get("field_heading_confirmed", False)) or not bool(
                ctx.get("field_origin_confirmed", False)
            ):
                self.last_result = ActionResult(
                    failed=True, reason="missing_field_reference_for_zone_center"
                )
                return self.last_result
            heading_yaw = self._float_context(ctx, "field_heading_yaw_rad")
            origin_x = self._float_context(ctx, "field_origin_local_x")
            origin_y = self._float_context(ctx, "field_origin_local_y")
            if heading_yaw is None or origin_x is None or origin_y is None:
                self.last_result = ActionResult(
                    failed=True, reason="missing_field_reference_for_zone_center"
                )
                return self.last_result
            ref = FieldReference()
            ref.is_confirmed = True
            ref.origin_local_n_m = origin_x
            ref.origin_local_e_m = origin_y
            ref.field_heading_yaw_rad = heading_yaw
            local = field_to_local_ned(
                self.zone_center[0], self.zone_center[1], 0.0, reference=ref,
            )
            zone_center = (local.north_m, local.east_m)
        self._effective_zone_center = zone_center

        candidates: list[_Candidate] = []
        rejected: list[dict[str, Any]] = []
        for index, item in enumerate(self.objects):
            candidate, rejection = self._candidate(item, index)
            if candidate is not None:
                candidates.append(candidate)
            elif rejection is not None:
                rejected.append(rejection)
        candidates.sort(key=lambda item: (-item.seen_count, -item.raw_count, -item.weight, item.zone_distance_m, item.index))
        selected: list[_Candidate] = []
        for candidate in candidates:
            distance = self._duplicate_distance(candidate, selected)
            if distance is not None:
                rejected.append({"id": candidate.object_id, "class_name": candidate.class_name,
                                 "reason": "duplicate_near_selected", "distance_m": distance})
                continue
            selected.append(candidate)
            if len(selected) == self.target_count:
                break

        detail = self._detail(selected, rejected, len(candidates))
        if not selected:
            if self.allow_fewer:
                self.last_result = ActionResult(done=True, reason="recon_targets_selected_zero", detail=detail)
            else:
                self.last_result = ActionResult(failed=True, reason="no_recon_targets", detail=detail)
        elif len(selected) < self.target_count and not self.allow_fewer:
            self.last_result = ActionResult(failed=True, reason="not_enough_recon_targets", detail=detail)
        else:
            self.last_result = ActionResult(done=True, reason="recon_targets_selected", detail=detail)
        return self.last_result

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.objects: list[Any] = []
        self.target_count = 5
        self.allow_fewer = True
        self.min_seen_count = 1
        self.min_raw_count = 0
        self.min_weight = 0.0
        self.deduplicate_radius_m = 0.45
        self.class_names = set(DEFAULT_CLASSES)
        self.zone_center = (0.0, 0.0)
        self.zone_center_mode = "local"
        self._effective_zone_center = (0.0, 0.0)
        self.started = False
        self.stopped = False
        self.last_result: ActionResult | None = None

    def _candidate(self, item: Any, index: int) -> tuple[_Candidate | None, dict[str, Any] | None]:
        if not isinstance(item, dict):
            return None, {"id": f"target_{index}", "reason": "invalid_object"}
        object_id = str(item.get("id") or item.get("target_id") or f"target_{index}")
        class_name = str(item.get("class_name") or item.get("label") or "")
        base = {"id": object_id, "class_name": class_name}
        if class_name not in self.class_names:
            return None, {**base, "reason": "unknown_class"}
        try:
            x = float(item["local_x"] if "local_x" in item else item["x"])
            y = float(item["local_y"] if "local_y" in item else item["y"])
        except (KeyError, TypeError, ValueError):
            return None, {**base, "reason": "missing_xy"}
        if not math.isfinite(x) or not math.isfinite(y):
            return None, {**base, "reason": "invalid_xy"}
        seen = self._int(item.get("seen_count", item.get("count", item.get("raw_count", 0))))
        raw = self._int(item.get("raw_count", seen))
        weight = self._float(item.get("weight", 0.0))
        if seen < self.min_seen_count:
            return None, {**base, "reason": "low_seen_count"}
        if raw < self.min_raw_count:
            return None, {**base, "reason": "low_raw_count"}
        if weight < self.min_weight:
            return None, {**base, "reason": "low_weight"}
        distance = math.hypot(x - self._effective_zone_center[0], y - self._effective_zone_center[1])
        return _Candidate(item, index, object_id, class_name, x, y, seen, raw, weight, distance), None

    def _detail(self, selected: list[_Candidate], rejected: list[dict[str, Any]], candidate_count: int) -> dict[str, Any]:
        targets = []
        for rank, candidate in enumerate(selected, 1):
            targets.append({
                "id": candidate.object_id, "class_name": candidate.class_name,
                "local_x": candidate.x, "local_y": candidate.y, "x": candidate.x, "y": candidate.y,
                "seen_count": candidate.seen_count, "raw_count": candidate.raw_count,
                "weight": candidate.weight, "rank": rank,
            })
        # Fixed-length slots: valid=true for selected, valid=false placeholder for missing
        target_slots = []
        for slot_index in range(self.target_count):
            if slot_index < len(selected):
                c = selected[slot_index]
                target_slots.append({
                    "valid": True,
                    "id": c.object_id,
                    "class_name": c.class_name,
                    "local_x": c.x,
                    "local_y": c.y,
                    "x": c.x,
                    "y": c.y,
                    "seen_count": c.seen_count,
                    "raw_count": c.raw_count,
                    "weight": c.weight,
                    "rank": slot_index + 1,
                })
            else:
                target_slots.append({
                    "valid": False,
                    "id": f"missing_recon_target_{slot_index}",
                    "class_name": "",
                    "local_x": None,
                    "local_y": None,
                    "x": None,
                    "y": None,
                    "seen_count": 0,
                    "raw_count": 0,
                    "weight": 0.0,
                    "rank": slot_index + 1,
                    "status": "missing",
                })
        return {"selected_targets": targets, "selected_count": len(targets),
                "target_slots": target_slots, "target_count": self.target_count,
                "candidate_count": candidate_count, "allow_fewer": self.allow_fewer,
                "rejected_objects": rejected}

    def _duplicate_distance(self, candidate: _Candidate, selected: list[_Candidate]) -> float | None:
        distances = [math.hypot(candidate.x - item.x, candidate.y - item.y) for item in selected]
        close = [distance for distance in distances if distance < self.deduplicate_radius_m]
        return min(close) if close else None

    @staticmethod
    def _zone_center(value: Any) -> tuple[float, float]:
        if value is None:
            return 0.0, 0.0
        if not isinstance(value, dict):
            raise ValueError("zone_center must be a dict")
        return float(value.get("x", 0.0)), float(value.get("y", 0.0))

    @staticmethod
    def _bool_value(value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"{name} must be a bool")

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _float(value: Any) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _float_context(context: dict[str, Any], name: str) -> float | None:
        value = context.get(name)
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None
