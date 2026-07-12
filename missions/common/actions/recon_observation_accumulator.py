"""Pure per-target recon observation statistics; never emits flight actions."""
from __future__ import annotations

import math
from typing import Any

from .recon_descend_observe import DEFAULT_SIGN_CLASS_NAMES


class ReconObservationAccumulator:
    """Collect descend-window detections and finalize one immutable result."""

    def __init__(self) -> None:
        self.reset()

    def start_target(self, target: dict[str, Any], target_index: int, params: dict[str, Any] | None = None) -> None:
        self.reset()
        p = params or {}
        self.target = dict(target)
        self.target_index = target_index
        self.record_start_altitude_m = float(p.get("record_start_altitude_m", 2.0))
        self.finish_altitude_m = float(p.get("finish_altitude_m", 1.2))
        self.sign_class_names = {str(v) for v in p.get("sign_class_names", DEFAULT_SIGN_CLASS_NAMES)}
        self.min_sign_confidence = float(p.get("min_sign_confidence", 0.35))
        self.min_seen_frames = int(p.get("min_seen_frames", 3))
        self.min_confidence_max = float(p.get("min_confidence_max", 0.55))
        self.min_confidence_mean = float(p.get("min_confidence_mean", 0.40))
        self.min_score = float(p.get("min_score", 1.2))
        self.min_margin_ratio = float(p.get("min_margin_ratio", 1.4))
        self.detection_source = str(p.get("detection_source", "scene"))

    def sample(self, height_m: float | None, context: dict[str, Any]) -> None:
        if height_m is None or not (self.finish_altitude_m <= height_m <= self.record_start_altitude_m):
            return
        self.record_frame_count += 1
        source = context.get("scene", {}) if self.detection_source == "scene" else context.get("perception", {})
        detections = source.get("detections", []) if isinstance(source, dict) and self.detection_source == "scene" else [source]
        best: dict[str, float] = {}
        for item in detections if isinstance(detections, list) else []:
            if not isinstance(item, dict): continue
            label = str(item.get("class_name") or item.get("label") or "")
            if not label or label not in self.sign_class_names: continue
            try: confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError): continue
            if not math.isfinite(confidence) or confidence < self.min_sign_confidence: continue
            best[label] = max(best.get(label, -1.0), confidence)
        if best: self.valid_sign_frame_count += 1
        for label, confidence in best.items():
            stats = self.class_stats.setdefault(label, {"seen_frames": 0, "conf_sum": 0.0, "conf_max": 0.0})
            stats["seen_frames"] += 1; stats["conf_sum"] += confidence; stats["conf_max"] = max(stats["conf_max"], confidence)

    def finalize(self, align_reason: str, align_detail: dict[str, Any] | None = None) -> dict[str, Any]:
        ranked = sorted(((v["conf_sum"], name, v) for name, v in self.class_stats.items()), reverse=True)
        best_score, label, stats = ranked[0] if ranked else (0.0, "", {"seen_frames": 0, "conf_sum": 0.0, "conf_max": 0.0})
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        mean = stats["conf_sum"] / stats["seen_frames"] if stats["seen_frames"] else 0.0
        margin = float("inf") if second_score == 0 and best_score else best_score / second_score if second_score else 0.0
        confirmed = bool(label and stats["seen_frames"] >= self.min_seen_frames and stats["conf_max"] >= self.min_confidence_max and mean >= self.min_confidence_mean and best_score >= self.min_score and margin >= self.min_margin_ratio)
        return {**self.target, "target_id": str(self.target.get("target_id") or self.target.get("id") or ""), "target_index": self.target_index, "hazard_label": label if confirmed else "", "confidence_max": stats["conf_max"], "confidence_mean": mean, "seen_frames": stats["seen_frames"], "observation_count": stats["seen_frames"], "record_frame_count": self.record_frame_count, "valid_sign_frame_count": self.valid_sign_frame_count, "best_score": best_score, "second_score": second_score, "margin_ratio": margin, "class_stats": self.class_stats, "status": "confirmed" if confirmed else "blank", "reason": "confirmed" if confirmed else "no_reliable_hazard", "align_reason": align_reason, "align_detail": dict(align_detail or {})}

    def reset(self) -> None:
        self.target = {}; self.target_index = 0; self.class_stats: dict[str, dict[str, float]] = {}; self.record_frame_count = 0; self.valid_sign_frame_count = 0
