"""Mission package exports loaded lazily to avoid app model import cycles."""

from __future__ import annotations

from typing import Any

__all__ = [
    "Mission",
    "MissionAction",
    "MissionContext",
    "MissionOutput",
    "DropAlignConfig",
    "DropTargetSelection",
    "MissionZone",
    "PayloadRelease",
    "PayloadReleaseTiming",
    "PayloadSlot",
    "RecceMissionConfig",
    "RescueCompetitionMission",
    "RescueCompetitionMissionConfig",
    "RescueStage",
    "RoutePoint",
    "VisualTrackingMission",
    "VisualTrackingMissionConfig",
]


def __getattr__(name: str) -> Any:
    if name in {"Mission", "MissionAction", "MissionContext", "MissionOutput"}:
        from missions import base

        return getattr(base, name)
    if name in {
        "DropAlignConfig",
        "DropTargetSelection",
        "MissionZone",
        "PayloadRelease",
        "PayloadReleaseTiming",
        "PayloadSlot",
        "RecceMissionConfig",
        "RescueCompetitionMission",
        "RescueCompetitionMissionConfig",
        "RescueStage",
        "RoutePoint",
    }:
        from missions import rescue_competition

        return getattr(rescue_competition, name)
    if name in {"VisualTrackingMission", "VisualTrackingMissionConfig"}:
        from missions import visual_tracking

        return getattr(visual_tracking, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
