from __future__ import annotations

from typing import TYPE_CHECKING

from missions.base import Mission
from missions.rescue_competition import (
    RescueCompetitionMission,
    build_rescue_config,
)
from missions.visual_tracking import VisualTrackingMission, VisualTrackingMissionConfig

if TYPE_CHECKING:
    from app.app_config import AppConfig
    from app.mission_manager import MissionManagerConfig


AVAILABLE_MISSIONS = ("visual_tracking", "rescue_competition")


def available_mission_names() -> tuple[str, ...]:
    return AVAILABLE_MISSIONS


def build_mission(name: str, config: AppConfig) -> Mission:
    return build_mission_from_settings(
        name,
        config.mission_settings,
        visual_config=config.mission,
    )


def build_mission_from_settings(
    name: str,
    settings: dict[str, object] | None = None,
    *,
    visual_config: MissionManagerConfig | None = None,
) -> Mission:
    normalized = str(name).strip().lower()
    if normalized in {"", "visual_tracking"}:
        return VisualTrackingMission(_visual_tracking_config(settings or {}, visual_config))
    if normalized == "rescue_competition":
        return RescueCompetitionMission(build_rescue_config(dict(settings or {})))
    raise KeyError(f"unknown mission: {name}")


def _visual_tracking_config(
    settings: dict[str, object],
    fallback: MissionManagerConfig | None,
) -> VisualTrackingMissionConfig:
    freshness = _section(settings, "freshness")
    transitions = _section(settings, "transitions")
    enter = _section(transitions, "approach_track_to_overhead_hold")
    exit_ = _section(transitions, "overhead_hold_to_approach_track")

    def value(key: str, default: object) -> object:
        return settings.get(key, default)

    return VisualTrackingMissionConfig(
        initial_mode=str(
            value(
                "initial_mode",
                fallback.initial_mode if fallback is not None else "APPROACH_TRACK",
            )
        ),
        overhead_entry_target_size_thresh=float(
            value(
                "overhead_entry_target_size_thresh",
                enter.get(
                    "target_size_thresh",
                    fallback.overhead_entry_target_size_thresh
                    if fallback is not None
                    else 0.30,
                ),
            )
        ),
        overhead_entry_pitch_rad=float(
            value(
                "overhead_entry_pitch_rad",
                enter.get(
                    "gimbal_pitch_rad",
                    fallback.overhead_entry_pitch_rad
                    if fallback is not None
                    else -1.5707963267948966,
                ),
            )
        ),
        overhead_entry_pitch_tol_rad=float(
            value(
                "overhead_entry_pitch_tol_rad",
                enter.get(
                    "gimbal_pitch_tol_rad",
                    fallback.overhead_entry_pitch_tol_rad if fallback is not None else 0.20,
                ),
            )
        ),
        overhead_entry_yaw_tol_rad=float(
            value(
                "overhead_entry_yaw_tol_rad",
                enter.get(
                    "gimbal_yaw_tol_rad",
                    fallback.overhead_entry_yaw_tol_rad if fallback is not None else 0.15,
                ),
            )
        ),
        overhead_entry_hold_s=float(
            value(
                "overhead_entry_hold_s",
                enter.get(
                    "hold_s",
                    fallback.overhead_entry_hold_s if fallback is not None else 0.5,
                ),
            )
        ),
        overhead_exit_target_size_drop=float(
            value(
                "overhead_exit_target_size_drop",
                exit_.get(
                    "target_size_drop",
                    fallback.overhead_exit_target_size_drop if fallback is not None else 0.06,
                ),
            )
        ),
        auto_switch_enabled=_bool(
            value(
                "auto_switch_enabled",
                fallback.auto_switch_enabled if fallback is not None else True,
            )
        ),
    )


def _section(data: dict[str, object], key: str) -> dict[str, object]:
    section = data.get(key, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        return {}
    return section


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}
    return bool(value)
