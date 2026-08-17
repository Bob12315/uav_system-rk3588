"""Pure danger-sign ranking shared by reconnaissance adapters."""
from __future__ import annotations

from typing import Any

DANGER_SIGN_CLASS_NAMES = (
    "baozha", "shenghua", "yiran", "fangshe", "buran",
    "fushi", "youdu", "yushi", "ziran", "ciji",
)


def rank_recon_views(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats = {name: {"seen_frames": 0, "confidence_sum": 0.0, "confidence_max": 0.0}
             for name in DANGER_SIGN_CLASS_NAMES}
    frame_count = 0
    for view in views:
        frames = view.get("frames", []) if isinstance(view, dict) else []
        for frame in frames if isinstance(frames, list) else []:
            if not isinstance(frame, dict):
                continue
            frame_count += 1
            for name, confidence in frame.get("best_by_class", {}).items():
                if name not in stats:
                    continue
                value = float(confidence)
                stats[name]["seen_frames"] += 1
                stats[name]["confidence_sum"] += value
                stats[name]["confidence_max"] = max(stats[name]["confidence_max"], value)
    order = {name: index for index, name in enumerate(DANGER_SIGN_CLASS_NAMES)}
    rows = []
    for name, values in stats.items():
        seen = int(values["seen_frames"])
        total = float(values["confidence_sum"])
        rows.append({"class_name": name, **values,
                     "confidence_mean": total / seen if seen else 0.0,
                     "hit_ratio": seen / frame_count if frame_count else 0.0})
    rows.sort(key=lambda item: (-item["confidence_sum"], -item["seen_frames"],
                                -item["confidence_max"], order[item["class_name"]]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows
