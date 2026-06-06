from __future__ import annotations

from typing import Any

from .align_descend import AlignDescendAction
from .goto_waypoint import GotoWaypointAction
from .payload_release import PayloadReleaseAction
from .registry import ActionRegistry
from .survey_area import SurveyAreaAction
from .target_lock import TargetLockAction


def create_action_lab_registry() -> ActionRegistry:
    registry = ActionRegistry()
    registry.register("goto_waypoint", GotoWaypointAction)
    registry.register("survey_area", SurveyAreaAction)
    registry.register("target_lock", TargetLockAction)
    registry.register("align_descend", AlignDescendAction)
    registry.register("payload_release", PayloadReleaseAction)
    return registry


def action_lab_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "goto_waypoint",
            "label": "Goto Waypoint",
            "description": "Dry-run a local-position waypoint action.",
            "default_params": {
                "x": 1.0,
                "y": 2.0,
                "altitude_m": 5.0,
                "yaw_mode": "hold",
                "tolerance_xy_m": 0.3,
                "tolerance_z_m": 0.3,
                "min_hold_updates": 1,
            },
        },
        {
            "name": "survey_area",
            "label": "Survey Area",
            "description": "Dry-run waypoint survey, localization, and fusion without sending vehicle commands.",
            "default_params": {
                "waypoints": [
                    {"x": 1.0, "y": 2.0, "altitude_m": 5.0},
                    {"x": 3.0, "y": 4.0, "altitude_m": 5.0},
                ],
                "capture_updates_per_waypoint": 3,
                "max_updates_per_waypoint": 200,
                "detection_source": "scene",
                "class_names": ["cylinder"],
            },
        },
        {
            "name": "target_lock",
            "label": "Target Lock",
            "description": "Dry-run target localization and yolo_lock_target action selection.",
            "default_params": {
                "target": {"x": 1.0, "y": 2.0},
                "max_match_distance_m": 1.0,
                "detection_source": "scene",
                "class_names": ["cylinder"],
                "max_updates": 30,
            },
        },
        {
            "name": "align_descend",
            "label": "Align Descend",
            "description": "Dry-run visual alignment descent and expose the command dict in detail.command.",
            "default_params": {
                "lost_timeout_updates": 5,
                "hold_updates_required": 3,
                "max_retries": 1,
                "max_updates": 300,
                "finish_altitude_m": 1.0,
                "config": {
                    "kp_vx": 0.8,
                    "kp_vy": 0.8,
                    "max_vx_mps": 0.4,
                    "max_vy_mps": 0.4,
                    "descend_speed_mps": 0.2,
                    "max_ex_cam": 0.06,
                    "max_ey_cam": 0.06,
                },
            },
        },
        {
            "name": "payload_release",
            "label": "Payload Release",
            "description": "Dry-run RC servo payload release. RC13 is the default; use channels [13, 14] for paired release.",
            "default_params": {
                "channels": [13],
                "release_pwm": 1900,
                "hold_pwm": 1100,
                "payload_id": "payload_1",
                "target_id": "target_a",
                "release_wait_updates": 5,
                "priority": 3,
            },
        },
    ]
