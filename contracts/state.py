from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class VehicleSnapshot:
    timestamp: float = 0.0
    connected: bool = False
    stale: bool = True
    control_allowed: bool = False
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GimbalSnapshot:
    timestamp: float = 0.0
    valid: bool = False
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PerceptionSnapshot:
    timestamp: float = 0.0
    sequence: int = 0
    target: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    timestamp: float = 0.0
    sequence: int = 0
    detections: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class FusedSnapshot:
    timestamp: float = 0.0
    valid: bool = False
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    sequence: int = 0
    updated_at: float = 0.0
    vehicle: VehicleSnapshot = field(default_factory=VehicleSnapshot)
    gimbal: GimbalSnapshot = field(default_factory=GimbalSnapshot)
    perception: PerceptionSnapshot = field(default_factory=PerceptionSnapshot)
    scene: SceneSnapshot = field(default_factory=SceneSnapshot)
    fused: FusedSnapshot = field(default_factory=FusedSnapshot)
    link: dict[str, Any] = field(default_factory=dict)
    field_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
