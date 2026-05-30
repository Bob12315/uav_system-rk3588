from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from missions.common.recce import RecceResultItem


def write_recce_results(
    output_dir: str | Path,
    mission: str,
    timestamp: float,
    items: list[RecceResultItem],
    write_json: bool = True,
    write_csv: bool = True,
) -> list[Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(float(timestamp)))
    written: list[Path] = []
    if write_json:
        path = directory / f"recce_{stamp}.json"
        payload = {
            "mission": mission,
            "timestamp": float(timestamp),
            "items": [item.to_dict() for item in items],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    if write_csv:
        path = directory / f"recce_{stamp}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "cylinder_key",
                    "cylinder_track_id",
                    "hazard_class",
                    "vote_count",
                    "confidence_sum",
                    "max_confidence",
                    "status",
                ],
            )
            writer.writeheader()
            for item in items:
                writer.writerow(item.to_dict())
        written.append(path)
    return written
