from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

PERCEPTION_SCHEMA_VERSION = 1
COMMAND_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PerceptionEnvelope:
    schema_version: int
    sequence: int
    captured_at_monotonic: float
    published_at_monotonic: float
    target: Mapping[str, Any]
    scene: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "sequence": self.sequence,
                "captured_at_monotonic": self.captured_at_monotonic,
                "published_at_monotonic": self.published_at_monotonic,
                "target": dict(self.target), "scene": dict(self.scene)}


def make_perception_envelope(*, sequence: int, target: Mapping[str, Any],
                             scene: Mapping[str, Any] | None = None,
                             captured_at_monotonic: float | None = None) -> PerceptionEnvelope:
    now = time.monotonic()
    return PerceptionEnvelope(PERCEPTION_SCHEMA_VERSION, int(sequence),
                              now if captured_at_monotonic is None else float(captured_at_monotonic),
                              now, dict(target), dict(scene or {}))


@dataclass(frozen=True, slots=True)
class VisionCommand:
    action: str
    sequence: int
    sent_at_monotonic: float
    track_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"schema_version": COMMAND_SCHEMA_VERSION,
                                "sequence": self.sequence,
                                "sent_at_monotonic": self.sent_at_monotonic,
                                "action": self.action}
        if self.track_id is not None: data["track_id"] = self.track_id
        return data
