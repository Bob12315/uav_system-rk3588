from __future__ import annotations

from typing import Any

from .align_descend import AlignDescendAction
from .build_recon_report import BuildReconReportAction
from .gps_multi_view_localize import GpsMultiViewLocalizeAction
from .gps_target_lock import GpsTargetLockAction
from .gps_drop_sequence import GpsDropSequenceAction
from .gps_recon_sequence import GpsReconSequenceAction
from .goto_waypoint import GotoWaypointAction
from .land import LandAction
from .multi_view_localize import MultiViewLocalizeAction
from .payload_release import PayloadReleaseAction
from .recon_descend_observe import ReconDescendObserveAction
from .recon_scan import ReconScanAction
from .recon_inspect_target import ReconInspectTargetAction
from .registry import ActionRegistry
from .select_drop_targets import SelectDropTargetsAction
from .select_recon_targets import SelectReconTargetsAction
from .drop_sequence import DropSequenceAction
from .recon_sequence import ReconSequenceAction
from .fixed_view_localize import FixedViewLocalizeAction
from .resolve_gps_targets import ResolveGpsTargetsAction
from .single_view_localize import SingleViewLocalizeAction
from .survey_area import SurveyAreaAction
from .takeoff import TakeoffAction
from .target_lock import TargetLockAction
from .validate_target import ValidateTargetAction
from .yaw_align import YawAlignAction


def create_action_lab_registry() -> ActionRegistry:
    registry = ActionRegistry()
    registry.register("takeoff", TakeoffAction)
    registry.register("yaw_align", YawAlignAction)
    registry.register("land", LandAction)
    registry.register("goto_waypoint", GotoWaypointAction)
    registry.register("survey_area", SurveyAreaAction)
    registry.register("single_view_localize", SingleViewLocalizeAction)
    registry.register("multi_view_localize", MultiViewLocalizeAction)
    registry.register("target_lock", TargetLockAction)
    registry.register("align_descend", AlignDescendAction)
    registry.register("payload_release", PayloadReleaseAction)
    registry.register("select_drop_targets", SelectDropTargetsAction)
    registry.register("select_recon_targets", SelectReconTargetsAction)
    registry.register("recon_inspect_target", ReconInspectTargetAction)
    registry.register("recon_scan", ReconScanAction)
    registry.register("recon_descend_observe", ReconDescendObserveAction)
    registry.register("build_recon_report", BuildReconReportAction)
    registry.register("fixed_view_localize", FixedViewLocalizeAction)
    registry.register("resolve_gps_targets", ResolveGpsTargetsAction)
    registry.register("validate_target", ValidateTargetAction)
    registry.register("drop_sequence", DropSequenceAction)
    registry.register("recon_sequence", ReconSequenceAction)
    registry.register("gps_multi_view_localize", GpsMultiViewLocalizeAction)
    registry.register("gps_target_lock", GpsTargetLockAction)
    registry.register("gps_drop_sequence", GpsDropSequenceAction)
    registry.register("gps_recon_sequence", GpsReconSequenceAction)
    return registry


def action_lab_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "takeoff",
            "label": "Takeoff",
            "description": "Set GUIDED mode, arm, take off, and wait until target altitude is reached.",
            "default_params": {
                "mode": "GUIDED",
                "altitude_m": 5.0,
                "altitude_tolerance_m": 0.35,
                "require_armed": True,
                "max_updates": 150,
                "priority": 2,
                "arm_priority": 1,
                "mode_priority": 2,
            },
        },
        {
            "name": "land",
            "label": "Land",
            "description": "Command vehicle landing and wait until altitude is low or vehicle is disarmed.",
            "default_params": {
                "land_altitude_threshold_m": 0.25,
                "max_updates": 250,
                "priority": 2,
                "key": "land_home",
            },
        },
        {
            "name": "yaw_align",
            "label": "Yaw Align",
            "description": "Turn vehicle yaw to the confirmed field heading and wait until aligned.",
            "default_params": {
                "yaw_mode": "field_heading",
                "tolerance_deg": 3.0,
                "yaw_speed_deg_s": 25.0,
                "min_hold_updates": 5,
                "max_updates": 120,
                "priority": 4,
                "key": "yaw_align_field",
            },
        },
        {
            "name": "goto_waypoint",
            "label": "Goto Waypoint",
            "description": "FIELD waypoint (x right, y forward), converted to LOCAL_NED or GPS before dispatch.",
            "default_params": {
                "x": 0.0,
                "y": 5.5,
                "altitude_m": 3.5,
                "waypoint_mode": "field",
                "target_frame": "local",
                "yaw_mode": "field_heading",
                "tolerance_xy_m": 0.35,
                "tolerance_z_m": 0.35,
                "min_hold_updates": 1,
                "priority": 5,
                "key": "goto_drop_target_debug",
            },
        },
        {
            "name": "survey_area",
            "label": "Survey Area",
            "description": "FIELD waypoint survey, converted to LOCAL_NED before dispatch.",
            "default_params": {
                "waypoints": [
                    {"x": 1.0, "y": 2.0, "altitude_m": 5.0},
                    {"x": 3.0, "y": 4.0, "altitude_m": 5.0},
                ],
                "waypoint_mode": "field",
                "yaw_mode": "field_heading",
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
                "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
                "min_confidence": 0.35,
                "camera": {
                    "fov_x_deg": 85.0,
                    "fov_y_deg": 69.0,
                    "image_x_sign": 1.0,
                    "image_y_sign": -1.0,
                },
            },
        },
        {
            "name": "target_lock",
            "label": "Target Lock",
            "description": "Dry-run target localization and yolo_lock_target action selection.",
            "default_params": {
                "target": {"local_x": 0.0, "local_y": 5.5},
                "max_match_distance_m": 1.2,
                "detection_source": "scene",
                "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
                "min_confidence": 0.35,
                "camera": {
                    "fov_x_deg": 85.0,
                    "fov_y_deg": 69.0,
                    "image_x_sign": 1.0,
                    "image_y_sign": -1.0,
                },
                "max_updates": 25,
                "key": "target_lock_debug",
            },
        },
        {
            "name": "align_descend",
            "label": "Align Descend",
            "description": "Dry-run visual alignment descent and expose the command dict in detail.command.",
            "default_params": {
                "expected_dt_s": 0.1,
                "lost_timeout_updates": 10,
                "hold_updates_required": 1,
                "max_retries": 1,
                "max_updates": 160,
                "finish_altitude_m": 1.3,
                "config": {
                    "kp_vx": 0.275,
                    "kp_vy": 0.275,
                    "max_vx_mps": 0.20,
                    "max_vy_mps": 0.20,
                    "height_gain_enabled": True,
                    "height_gain_mode": "points",
                    "height_scale_points": [
                        {"altitude_m": 1.1, "scale": 0.20},
                        {"altitude_m": 1.3, "scale": 0.25},
                        {"altitude_m": 2.4, "scale": 0.55},
                        {"altitude_m": 3.5, "scale": 0.55},
                        {"altitude_m": 5.0, "scale": 0.55},
                    ],
                    "scale_max_velocity_with_height": True,
                    "descend_speed_mps": 0.30,
                    "slow_descend_speed_mps": 0.18,
                    "max_ex_cam": 0.20,
                    "max_ey_cam": 0.20,
                    "slow_descend_max_ex_cam": 0.28,
                    "slow_descend_max_ey_cam": 0.28,
                    "deadband_ex_cam": 0.04,
                    "deadband_ey_cam": 0.04,
                    "min_altitude_m": 1.1,
                    "require_target_locked": False,
                    "payload_offset_enabled": True,
                    "payload_forward_m": -0.06,
                    "payload_right_m": 0.0,
                    "fov_x_deg": 85.0,
                    "fov_y_deg": 69.0,
                    "image_x_sign": 1.0,
                    "image_y_sign": -1.0,
                    "max_payload_offset_ex_cam": 0.8,
                    "max_payload_offset_ey_cam": 0.8,
                },
            },
        },
        {
            "name": "payload_release",
            "label": "Payload Release",
            "description": (
                "Dispatch MAV_CMD_DO_SET_SERVO to flight-controller SERVO outputs. "
                "servo_outputs are per-SERVO output channel/PWM settings, not RC input channels. "
                "ch8 = rear payload, SERVO8, hold_pwm=1250, release_pwm=1750. "
                "ch9 = front payload, SERVO9, hold_pwm=1185, release_pwm=1815. "
                "Action Lab default only releases ch8 for safety; use Action Mission template for dual-target release."
            ),
            "default_params": {
                "servo_outputs": [
                    {"channel": 8, "release_pwm": 1750, "hold_pwm": 1250},
                ],
                "payload_id": "payload_1",
                "target_id": "target_debug",
                "release_wait_updates": 5,
                "priority": 3,
                "key": "payload_release_ch8_debug",
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
                "waypoint_mode": "field",
                "altitude_m": 5.0,
                "yaw_mode": "field_heading",
                "waypoints": [
                    {"x": -1.0, "y": 4.8, "altitude_m": 5.0},
                    {"x": 1.0, "y": 4.8, "altitude_m": 5.0},
                    {"x": 1.0, "y": 6.2, "altitude_m": 5.0},
                    {"x": -1.0, "y": 6.2, "altitude_m": 5.0},
                ],
                "capture_updates_per_waypoint": 3,
                "settle_updates_per_waypoint": 2,
                "max_updates_per_waypoint": 100,
                "tolerance_xy_m": 0.35,
                "tolerance_z_m": 0.35,
                "goto_min_hold_updates": 1,
                "detection_source": "scene",
                "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
                "min_confidence": 0.35,
                "camera": {
                    "fov_x_deg": 85.0,
                    "fov_y_deg": 69.0,
                    "image_x_sign": 1.0,
                    "image_y_sign": -1.0,
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
        {
            "name": "select_drop_targets",
            "label": "Select Drop Targets",
            "description": "Select the best payload drop targets from localized_objects without sending vehicle commands.",
            "default_params": {
                "objects": [
                    {
                        "id": "demo_bucket_1",
                        "class_name": "bucket_1",
                        "local_x": 0.0,
                        "local_y": 5.2,
                        "seen_count": 3,
                        "raw_count": 3,
                        "weight": 3.0,
                    },
                    {
                        "id": "demo_bucket_2",
                        "class_name": "bucket_2",
                        "local_x": 0.7,
                        "local_y": 5.8,
                        "seen_count": 3,
                        "raw_count": 3,
                        "weight": 2.8,
                    },
                ],
                "target_count": 2,
                "score_table": {
                    "bucket_1": 500,
                    "bucket_2": 300,
                    "bucket_3": 100,
                    "bucket": 50,
                },
                "min_seen_count": 2,
                "min_raw_count": 0,
                "min_weight": 0.0,
                "deduplicate_radius_m": 0.6,
                "prefer_class_order": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
                "zone_center": {"x": 0.0, "y": 5.5},
            },
        },
        {
            "name": "recon_scan",
            "label": "Recon Scan",
            "description": "Scan the reconnaissance area, associate danger signs to white buckets, and generate a conservative report.",
            "default_params": {
                "waypoints": [
                    {"x": -2.5, "y": 48.0, "altitude_m": 2.2},
                    {"x": 2.5, "y": 48.0, "altitude_m": 2.2},
                    {"x": 2.5, "y": 52.0, "altitude_m": 2.2},
                    {"x": -2.5, "y": 52.0, "altitude_m": 2.2},
                    {"x": 0.0, "y": 50.0, "altitude_m": 2.0},
                ],
                "waypoint_mode": "field",
                "yaw_mode": "field_heading",
                "capture_updates_per_waypoint": 4,
                "settle_updates_per_waypoint": 2,
                "max_updates_per_waypoint": 150,
                "detection_source": "scene",
                "bucket_class_names": ["recon_bucket", "white_bucket"],
                "sign_class_names": ["danger_1", "danger_2", "danger_3"],
                "min_bucket_confidence": 0.25,
                "min_sign_confidence": 0.35,
                "min_report_confidence": 0.65,
                "associate_max_distance_norm": 0.35,
                "cluster_radius_m": 0.6,
                "blank_when_uncertain": True,
                "priority": 5,
                "camera": {
                    "fov_x_deg": 113.0,
                    "fov_y_deg": 93.0,
                    "image_x_sign": 1.0,
                    "image_y_sign": -1.0,
                },
            },
        },
        {
            "name": "select_recon_targets",
            "label": "Select Recon Targets",
            "description": "Select and deduplicate up to five localized buckets; fewer targets are allowed.",
            "default_params": {
                "objects": [], "target_count": 5, "allow_fewer": True,
                "min_seen_count": 1, "min_raw_count": 0, "min_weight": 0.0,
                "deduplicate_radius_m": 0.45,
                "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket", "recon_bucket", "white_bucket"],
                "zone_center": {"x": 0.0, "y": 5.0},
            },
        },
        {
            "name": "recon_inspect_target",
            "label": "Recon Inspect Target",
            "description": "Visit one selected bucket, align to 1.5m, and observe danger signs without payload release.",
            "default_params": {
                "targets": [], "target_index": 0, "inspect_altitude_m": 3.0,
                "align_finish_altitude_m": 1.5, "waypoint_mode": "absolute", "yaw_mode": "field_heading",
                "goto_tolerance_xy_m": 0.35, "goto_tolerance_z_m": 0.35, "goto_min_hold_updates": 1,
                "target_lock": {"max_match_distance_m": 1.2, "detection_source": "scene",
                    "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket", "recon_bucket", "white_bucket"],
                    "min_confidence": 0.25, "max_updates": 25},
                "align_descend": {"expected_dt_s": 0.1, "lost_timeout_updates": 8,
                    "hold_updates_required": 1, "max_retries": 1, "max_updates": 160,
                    "finish_altitude_m": 1.5, "config": {"min_altitude_m": 1.3, "require_target_locked": False,
                    "payload_offset_enabled": False}},
                "observe": {"detection_source": "scene", "observe_time_s": 2.0, "expected_dt_s": 0.1,
                    "min_sign_confidence": 0.35,
                    "sign_class_names": ["danger_1", "danger_2", "danger_3", "baozha", "shenghua", "yiran",
                                         "fangshe", "buran", "fushi", "youdu", "yushi", "ziran", "ciji"]},
                "continue_on_lock_failed": False, "continue_on_align_failed": False, "priority": 5,
            },
        },
        {
            "name": "recon_descend_observe",
            "label": "Recon Descend Observe",
            "description": "Descend to 1.5m above a recon target while recording danger sign statistics, then output best-class result.",
            "default_params": {
                "target": {"id": "recon_0", "local_x": 0.0, "local_y": 50.0},
                "target_index": 0,
                "record_start_altitude_m": 2.0,
                "finish_altitude_m": 1.5,
                "detection_source": "scene",
                "sign_class_names": [
                    "baozha", "shenghua", "yiran", "fangshe", "buran",
                    "fushi", "youdu", "yushi", "ziran", "ciji",
                    "danger_1", "danger_2", "danger_3",
                ],
                "min_sign_confidence": 0.35,
                "min_seen_frames": 3,
                "min_confidence_max": 0.55,
                "min_confidence_mean": 0.40,
                "min_score": 1.2,
                "min_margin_ratio": 1.4,
                "align_descend": {
                    "expected_dt_s": 0.1,
                    "lost_timeout_updates": 8,
                    "hold_updates_required": 1,
                    "max_retries": 1,
                    "max_updates": 120,
                    "finish_altitude_m": 1.5,
                    "config": {
                        "descent_gate_policy": "allow_unaligned",
                        "unaligned_descend_speed_mps": 0.06,
                        "kp_vx": 0.175,
                        "kp_vy": 0.175,
                        "max_vx_mps": 0.12,
                        "max_vy_mps": 0.12,
                        "descend_speed_mps": 0.16,
                        "slow_descend_speed_mps": 0.10,
                        "max_ex_cam": 0.18,
                        "max_ey_cam": 0.18,
                        "slow_descend_max_ex_cam": 0.45,
                        "slow_descend_max_ey_cam": 0.45,
                        "deadband_ex_cam": 0.06,
                        "deadband_ey_cam": 0.08,
                        "min_altitude_m": 1.5,
                        "require_target_locked": False,
                        "payload_offset_enabled": False,
                    },
                },
            },
        },
        {
            "name": "fixed_view_localize",
            "label": "Fixed View Localize",
            "description": "Stay at current point, collect multiple YOLO frames, and fuse localized objects.",
            "default_params": {
                "detection_source": "scene",
                "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
                "min_confidence": 0.35,
                "settle_updates": 8,
                "capture_updates": 12,
                "max_updates": 40,
                "camera": {
                    "fov_x_deg": 85.0,
                    "fov_y_deg": 69.0,
                    "image_x_sign": 1.0,
                    "image_y_sign": -1.0,
                },
                "fusion": {
                    "cluster_radius_m": 0.7,
                    "outlier_radius_m": 0.8,
                    "min_cluster_size": 2,
                    "max_cluster_radius_m": 0.9,
                    "center_weight_power": 1.0,
                    "max_objects": 5,
                },
            },
        },
        {
            "name": "drop_sequence",
            "label": "Drop Sequence",
            "description": (
                "Composite drop action: goto target → lock → align-descend → release payload → climb. "
                "Handles up to max_payloads payloads across max_target_candidates targets with "
                "fallback release and single-target release-all modes."
            ),
            "default_params": {
                "targets": [],
                "payloads": [
                    {
                        "payload_id": "payload_1",
                        "servo_outputs": [{"channel": 8, "release_pwm": 1750, "hold_pwm": 1250}],
                        "payload_forward_m": -0.06,
                        "payload_right_m": 0.0,
                    },
                ],
                "max_target_candidates": 3,
                "max_payloads": 2,
                "approach_altitude_m": 2.5,
                "finish_altitude_m": 1.5,
                "climb_after_drop_m": 3.5,
                "goto_max_updates": 120,
                "target_lock_max_updates": 50,
                "align_descend_max_updates": 250,
                "climb_max_updates": 100,
                "fallback_release_when_last_target_failed": True,
                "release_all_payloads_if_only_one_target": True,
                "continue_after_any_failure": True,
            },
        },
        {
            "name": "build_recon_report",
            "label": "Build Recon Report",
            "description": "Aggregate recon_descend_observe results into a summary report — no flight commands.",
            "default_params": {
                "items": [],
            },
        },
        {
            "name": "recon_sequence",
            "label": "Recon Sequence",
            "description": (
                "Composite recon action: goto target → lock → descend-observe → climb. "
                "Iterates over valid recon targets, recording danger sign detection results."
            ),
            "default_params": {
                "targets": [],
                "max_targets": 5,
                "approach_altitude_m": 2.5,
                "finish_altitude_m": 1.5,
                "climb_after_observe_m": 2.5,
                "goto_max_updates": 120,
                "target_lock_max_updates": 40,
                "observe_max_updates": 200,
                "climb_max_updates": 100,
                "continue_after_target_failure": True,
            },
        },
        {
            "name": "gps_multi_view_localize",
            "label": "GPS Multi-View Localize",
            "description": "Fly to 4 GLOBAL GPS scan points (field_heading) from frozen runtime reference, capture detections, GPS-project and fuse into localized objects. Goto directly settles—no independent yaw_align phase.",
            "default_params": {
                "scan_altitude_m": 4.5,
                "capture_updates_per_waypoint": 4,
                "settle_updates_per_waypoint": 1,
                "max_updates_per_waypoint": 120,
                "tolerance_xy_m": 0.8,
                "tolerance_z_m": 0.6,
                "goto_min_hold_updates": 1,
                "yaw_mode": "field_heading",
                "detection_source": "scene",
                "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
                "min_confidence": 0.35,
                "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6, "image_x_sign": 1.0, "image_y_sign": -1.0},
                "fusion": {"cluster_radius_m": 0.8, "outlier_radius_m": 0.8, "min_cluster_size": 2, "center_weight_power": 1.0}
            },
        },
        {
            "name": "gps_target_lock",
            "label": "GPS Target Lock",
            "description": "Lock onto a GPS target by correlating capture-time detection projections.",
            "default_params": {
                "target": {},
                "max_match_distance_m": 1.2,
                "max_updates": 40,
                "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6, "image_x_sign": 1.0, "image_y_sign": -1.0},
            },
        },
        {
            "name": "gps_drop_sequence",
            "label": "GPS Drop Sequence",
            "description": "GPS-first dual-target drop: GLOBAL goto (field_heading) → GPS lock → visual align-descend → stop descent at 1.2m and horizontal centre-calibrate → release → climb to 2.5m at same position.",
            "default_params": {
                "targets": [],
                "payloads": [],
                "approach_altitude_m": 2.5,
                "finish_altitude_m": 1.2,
                "climb_after_drop_m": 2.5,
                "climb_tolerance_z_m": 0.1,
                "climb_max_updates": 100,
                "goto_max_updates": 200,
                "target_lock_max_updates": 8,
                "align_descend_max_updates": 35,
                "release_wait_updates": 5,
                "goto": {
                    "tolerance_xy_m": 0.25,
                    "tolerance_z_m": 0.3,
                    "min_hold_updates": 3,
                    "require_velocity_valid": True,
                    "max_horizontal_speed_mps": 0.15,
                    "max_vertical_speed_mps": 0.1
                },
                "target_lock": {
                    "max_match_distance_m": 1.5,
                    "min_confidence": 0.35,
                    "require_track_id": False,
                    "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
                    "detection_source": "scene",
                    "camera": {
                        "fov_x_deg": 51.3,
                        "fov_y_deg": 39.6,
                        "image_x_sign": 1.0,
                        "image_y_sign": -1.0
                    }
                },
                "align_descend": {
                    "expected_dt_s": 0.1,
                    "lost_timeout_updates": 10,
                    "hold_updates_required": 1,
                    "max_retries": 1,
                    "max_updates": 35,
                    "finish_policy": "latched_center_alignment",
                    "finish_alignment_max_ex_cam": 0.35,
                    "finish_alignment_max_ey_cam": 0.35,
                    "finish_alignment_hold_updates": 1,
                    "config": {
                        "kp_vx": 0.275,
                        "kp_vy": 0.275,
                        "max_vx_mps": 0.2,
                        "max_vy_mps": 0.2,
                        "height_gain_enabled": True,
                        "height_gain_mode": "points",
                        "height_scale_points": [
                            {"altitude_m": 1.0, "scale": 0.40},
                            {"altitude_m": 1.3, "scale": 0.40},
                            {"altitude_m": 2.4, "scale": 0.55},
                            {"altitude_m": 3.5, "scale": 0.55},
                            {"altitude_m": 4.5, "scale": 0.55}
                        ],
                        "scale_max_velocity_with_height": True,
                        "descend_speed_mps": 0.3,
                        "slow_descend_speed_mps": 0.18,
                        "max_ex_cam": 0.22,
                        "max_ey_cam": 0.22,
                        "slow_descend_max_ex_cam": 0.55,
                        "slow_descend_max_ey_cam": 0.55,
                        "deadband_ex_cam": 0.06,
                        "deadband_ey_cam": 0.08,
                        "min_altitude_m": 1.2,
                        "require_target_locked": False,
                        "payload_offset_enabled": True,
                        "descent_gate_policy": "allow_unaligned",
                        "unaligned_descend_speed_mps": 0.08,
                        "fov_x_deg": 85.0,
                        "fov_y_deg": 69.0,
                        "image_x_sign": 1.0,
                        "image_y_sign": -1.0,
                        "max_payload_offset_ex_cam": 0.8,
                        "max_payload_offset_ey_cam": 0.8
                    }
                }
            },
        },
    ]
