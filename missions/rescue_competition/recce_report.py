from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class RecceResult:
    target_id: int
    x: float
    y: float
    hazard_class: str | None = None
    vote_count: int = 0
    confidence_sum: float = 0.0
    status: str = "blank"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def write_recce_report(
    *,
    output_dir: str,
    timestamp: float,
    results: list[RecceResult],
) -> str:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
    path = directory / f"recce_{stamp}.json"
    payload = {
        "timestamp": float(timestamp),
        "items": [item.to_dict() for item in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
