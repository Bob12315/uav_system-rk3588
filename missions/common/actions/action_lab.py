from __future__ import annotations

from typing import Any

from .align_descend import AlignDescendAction
from .goto_waypoint import GotoWaypointAction
from .multi_view_localize import MultiViewLocalizeAction
from .payload_release import PayloadReleaseAction
from .registry import ActionRegistry
from .single_view_localize import SingleViewLocalizeAction
from .survey_area import SurveyAreaAction
from .target_lock import TargetLockAction


def create_action_lab_registry() -> ActionRegistry:
    registry = ActionRegistry()
    registry.register("goto_waypoint", GotoWaypointAction)
    registry.register("survey_area", SurveyAreaAction)
    registry.register("single_view_localize", SingleViewLocalizeAction)
    registry.register("multi_view_localize", MultiViewLocalizeAction)
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
                "y": 0.0,
                "altitude_m": 1.5,
                "yaw_mode": "arm_heading",
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
                "yaw_mode": "arm_heading",
                "capture_updates_per_waypoint": 3,
                "max_updates_per_waypoint": 200,
                "detection_source": "scene",
                "class_names": ["cylinder"],
            },
        },
        {
            "name": "single_view_localize",
            "label": "Single View Localize",
            "description": "Single-frame YOLO detection to local NED coordinate debug action.",
            "default_params": {
                "detection_source": "scene",
                "class_names": ["bucket"],
                "min_confidence": 0.35,
                "camera": {
                    "horizontal_fov_deg": 70.0,
                    "vertical_fov_deg": 43.0,
                    "image_x_sign": 1,
                    "image_y_sign": 1,
                    "model": "pinhole",
                },
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
                "max_updates": 60,
                "finish_altitude_m": 3.0,
                "config": {
                    "kp_x": 0.8,
                    "kp_y": 0.8,
                    "max_vx_mps": 0.4,
                    "max_vy_mps": 0.4,
                    "descend_speed_mps": 0.05,
                    "max_ex_cam": 0.06,
                    "max_ey_cam": 0.06,
                    "min_altitude_m": 2.5,
                },
            },
        },
        {
            "name": "payload_release",
            "label": "Payload Release",
            "description": (
                "Dispatch MAV_CMD_DO_SET_SERVO to flight-controller SERVO outputs. "
                "servo_outputs are per-SERVO output channel/PWM settings, not RC input channels."
            ),
            "default_params": {
                "servo_outputs": [
                    {"channel": 8, "release_pwm": 1200, "hold_pwm": 1700},
                    {"channel": 9, "release_pwm": 1700, "hold_pwm": 1200},
                ],
                "payload_id": "payload_pair",
                "target_id": "target_a",
                "release_wait_updates": 5,
                "priority": 3,
            },
        },
        {
            "name": "multi_view_localize",
            "label": "Multi-View Localize",
            "description": (
                "Fly to four observation points, collect YOLO detections, fuse into "
                "localized object coordinates. Outputs localized_objects only — "
                "no best_target selection, no auto-lock, no payload release."
            ),
            "default_params": {
                "waypoint_mode": "relative_to_start",
                "radius_m": 0.8,
                "altitude_m": 3.0,
                "yaw_mode": "arm_heading",
                "waypoints": None,
                "capture_updates_per_waypoint": 3,
                "settle_updates_per_waypoint": 3,
                "max_updates_per_waypoint": 100,
                "tolerance_xy_m": 0.3,
                "tolerance_z_m": 0.3,
                "min_hold_updates": 1,
                "detection_source": "scene",
                "class_names": ["bucket"],
                "min_confidence": 0.25,
                "camera": {
                    "fov_x_deg": 75.0,
                    "fov_y_deg": 75.0,
                    "image_x_sign": 1.0,
                    "image_y_sign": 1.0,
                },
                "fusion": {
                    "cluster_radius_m": 0.8,
                    "outlier_radius_m": 0.8,
                    "min_cluster_size": 2,
                    "center_weight_power": 1.0,
                },
                "save_result": True,
                "priority": 5,
            },
        },
    ]
