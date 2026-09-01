"""The single Action definition catalog used by runtime, Web and validators."""
from __future__ import annotations

from missions.definitions import ActionDefinition
from contracts.core.action import ExitBarrier

from .align_descend import AlignDescendAction
from .change_speed import ChangeSpeedAction
from .goto_waypoint import GotoWaypointAction
from .gps_capture_view import GpsCaptureViewAction
from .gps_fuse_views import GpsFuseViewsAction
from .gps_target_lock import GpsTargetLockAction
from .land import LandAction
from .payload_release import PayloadReleaseAction
from .registry import ActionRegistry
from .select_drop_targets import SelectDropTargetsAction
from .takeoff import TakeoffAction
from .target_lock import TargetLockAction


def _definition(
    name: str,
    factory,
    description: str,
    defaults: dict | None = None,
    *,
    properties: dict | None = None,
    required_inputs: tuple[str, ...] = (),
    output_properties: dict | None = None,
    parameter_aliases: dict[str, tuple[str, ...]] | None = None,
    parameter_schema_extra: dict | None = None,
    effects: tuple[str, ...] = (),
    exit_barrier: ExitBarrier = ExitBarrier.NONE,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        revision="v1",
        factory=factory,
        label=name.replace("_", " ").title(),
        description=description,
        default_params=dict(defaults or {}),
        parameter_schema={"type": "object", "properties": dict(properties or {}), "additionalProperties": False, **dict(parameter_schema_extra or {})},
        required_inputs=required_inputs,
        output_schema={"type": "object", "properties": dict(output_properties or {}), "additionalProperties": False},
        parameter_aliases=dict(parameter_aliases or {}),
        allowed_effect_types=effects,
        exit_barrier=exit_barrier,
    )


_NUMBER = {"type": "number"}
_NULLABLE_NUMBER = {"type": ["number", "null"]}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_STRING = {"type": "string"}
_STRING_ARRAY = {"type": "array", "items": _STRING}
_ID = {"type": ["string", "integer"], "minLength": 1}
_CAMERA = {"type": "object", "properties": {
    "fov_x_deg": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180},
    "fov_y_deg": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180},
    "image_x_sign": {"type": "number", "enum": [-1, 1]},
    "image_y_sign": {"type": "number", "enum": [-1, 1]},
    "min_altitude_m": {"type": "number", "exclusiveMinimum": 0},
}, "additionalProperties": False}
_TARGET = {"type": ["object", "null"], "properties": {
    "id": _ID, "target_id": _ID, "valid": _BOOLEAN,
    "x": _NULLABLE_NUMBER, "y": _NULLABLE_NUMBER,
    "local_x": _NULLABLE_NUMBER, "local_y": _NULLABLE_NUMBER,
    "lat": {"type": ["number", "null"], "minimum": -90, "maximum": 90},
    "lon": {"type": ["number", "null"], "minimum": -180, "maximum": 180},
    "class_name": _STRING, "east_m": _NULLABLE_NUMBER, "north_m": _NULLABLE_NUMBER,
    "score": _NUMBER, "seen_count": _INTEGER, "count": _INTEGER,
    "raw_count": _INTEGER, "weight": _NUMBER, "track_ids": {"type": "array", "items": _INTEGER},
    "rank": _INTEGER, "status": _STRING,
}, "additionalProperties": False}
_LOCALIZED_OBJECT = {"type": "object", "properties": {
    "id": {"type": ["string", "integer"]}, "target_id": _ID, "valid": _BOOLEAN,
    "class_name": _STRING, "lat": _NUMBER, "lon": _NUMBER, "east_m": _NUMBER, "north_m": _NUMBER,
    "local_x": _NUMBER, "local_y": _NUMBER, "x": _NUMBER, "y": _NUMBER,
    "sample_count": _INTEGER, "seen_count": _INTEGER, "raw_count": _INTEGER, "count": _INTEGER,
    "confidence": _NUMBER, "weight": _NUMBER, "score": _NUMBER, "cluster_spread_m": _NUMBER,
    "source_waypoints": _STRING_ARRAY, "source_frames": {"type": "array", "items": _INTEGER},
    "track_ids": {"type": "array", "items": _INTEGER}, "rank": _INTEGER, "status": _STRING,
}, "additionalProperties": False}
_RAW_ESTIMATE = {"type": "object", "required": ["lat", "lon", "east_offset_m", "north_offset_m", "capture_drone_lat", "capture_drone_lon", "capture_yaw_rad", "capture_relative_altitude_m", "ex", "ey", "class_name"], "properties": {
    "lat": _NUMBER, "lon": _NUMBER, "east_offset_m": _NUMBER, "north_offset_m": _NUMBER,
    "capture_drone_lat": _NUMBER, "capture_drone_lon": _NUMBER, "capture_yaw_rad": _NUMBER,
    "capture_relative_altitude_m": _NUMBER, "ex": _NUMBER, "ey": _NUMBER, "class_name": _STRING,
    "confidence": {"type": ["number", "null"]}, "track_id": {"type": ["integer", "null"]},
    "frame_id": {"type": ["integer", "null"]}, "timestamp": {"type": ["number", "null"]},
    "source_waypoint": {"type": ["string", "null"]},
}, "additionalProperties": False}
_GPS_CAPTURE_OUTPUT = {"raw_estimates": {"type": "array", "items": _RAW_ESTIMATE}, "count": _INTEGER,
                       "source_waypoint": _STRING, "rejected_by_reason": {"type": "object", "patternProperties": {".*": {"type": "integer", "minimum": 0}}, "additionalProperties": False},
                       "coordinate_frame": {"type": "string", "const": "GLOBAL"}}
_SERVO_OUTPUT = {"type": "object", "required": ["channel", "release_pwm", "hold_pwm"], "properties": {
    "channel": {"type": "integer", "minimum": 1},
    "release_pwm": {"type": "integer", "minimum": 500, "maximum": 2500},
    "hold_pwm": {"type": "integer", "minimum": 500, "maximum": 2500},
}, "additionalProperties": False}
_ALIGN_LEGACY_CONFIG = {"type": "object", "properties": {
    "min_altitude_m": {"type": "number", "exclusiveMinimum": 0}, "descend_speed_mps": {"type": "number", "minimum": 0},
    "max_ex_cam": {"type": "number", "exclusiveMinimum": 0}, "max_ey_cam": {"type": "number", "exclusiveMinimum": 0},
    "max_vx_mps": {"type": "number", "exclusiveMinimum": 0}, "max_vy_mps": {"type": "number", "exclusiveMinimum": 0},
    "kp_vx": {"type": "number", "minimum": 0}, "kp_vy": {"type": "number", "minimum": 0},
    "vx_sign": {"type": "number", "enum": [-1, 1]}, "vy_sign": {"type": "number", "enum": [-1, 1]},
    "deadband_ex_cam": _NUMBER, "deadband_ey_cam": _NUMBER, "descent_gate_policy": _STRING,
    "height_gain_enabled": _BOOLEAN, "height_gain_mode": _STRING,
    "height_scale_points": {"type": "array", "items": {"type": "object", "required": ["altitude_m", "scale"], "properties": {"altitude_m": _NUMBER, "scale": _NUMBER}, "additionalProperties": False}},
    "integral_active_below_altitude_m": _NUMBER,
    "integral_enabled": _BOOLEAN, "integral_vx_limit_mps": _NUMBER, "integral_vy_limit_mps": _NUMBER,
    "ki_vx": _NUMBER, "ki_vy": _NUMBER,
    "min_effective_speed_active_below_altitude_m": _NUMBER, "min_effective_speed_enabled": _BOOLEAN,
    "min_effective_speed_ex_threshold": _NUMBER, "min_effective_speed_ey_threshold": _NUMBER, "min_effective_speed_mps": _NUMBER,
    "require_target_locked": _BOOLEAN, "scale_max_velocity_with_height": _BOOLEAN,
    "slow_descend_max_ex_cam": _NUMBER, "slow_descend_max_ey_cam": _NUMBER, "slow_descend_speed_mps": _NUMBER,
    "target_loss_grace_horizontal_scale": _NUMBER, "target_loss_grace_updates": _INTEGER,
    "unaligned_descend_speed_mps": _NUMBER, "altitude_source": _STRING, "target_loss_descend_speed_mps": _NUMBER,
    "target_loss_policy": _STRING,
    "descent_speed_stages": {"type": "array", "items": {"type": "object", "required": ["max_altitude_m", "max_descend_speed_mps"], "properties": {"max_altitude_m": _NUMBER, "max_descend_speed_mps": _NUMBER}, "additionalProperties": False}},
}, "additionalProperties": False}


_DEFINITIONS = (
    _definition("takeoff", TakeoffAction, "Arm and take off through the execution safety gates.",
                {"mode": "GUIDED", "altitude_m": 3.0, "altitude_tolerance_m": 0.3, "max_updates": 120, "require_armed": True, "priority": 2, "arm_priority": 1, "mode_priority": 2},
                properties={"mode": {"type": "string", "enum": ["GUIDED"]}, "altitude_m": {"type": "number", "exclusiveMinimum": 0}, "altitude_tolerance_m": {"type": "number", "exclusiveMinimum": 0}, "max_updates": {"type": "integer", "minimum": 1}, "max_duration_s": {"type": ["number", "null"], "exclusiveMinimum": 0}, "require_armed": _BOOLEAN, "priority": _INTEGER, "arm_priority": _INTEGER, "mode_priority": _INTEGER, "key": _STRING},
                required_inputs=("drone.mode", "drone.armed", "drone.relative_altitude"), effects=("set_mode", "arm", "takeoff")),
    _definition("land", LandAction, "Land through the execution safety gates.",
                {"land_altitude_threshold_m": 0.25, "max_updates": 200, "priority": 2},
                properties={"land_altitude_threshold_m": {"type": "number", "minimum": 0}, "max_updates": {"type": "integer", "minimum": 1}, "priority": _INTEGER, "key": _STRING}, required_inputs=("drone",), effects=("land",)),
    _definition("change_speed", ChangeSpeedAction, "Set the flight-controller speed target.", {"speed_mps": 1.0, "speed_type": "ground", "priority": 4},
                properties={"speed_mps": {"type": "number", "exclusiveMinimum": 0}, "speed_type": {"type": "string", "enum": ["ground", "air", "climb", "descent"]}, "priority": _INTEGER, "key": _STRING}, effects=("change_speed",)),
    _definition("goto_waypoint", GotoWaypointAction, "Convert a FIELD target to GPS while holding yaw unless field-heading yaw is requested.",
                {"field_x_m": 0, "field_y_m": 30, "altitude_m": 3, "tolerance_xy_m": 3, "tolerance_z_m": 3, "min_hold_updates": 1, "require_velocity_valid": False, "max_horizontal_speed_mps": 0.15, "max_vertical_speed_mps": 0.10, "priority": 4, "yaw_mode": "hold"},
                properties={"field_x_m": _NUMBER, "field_y_m": _NUMBER, "x": _NUMBER, "y": _NUMBER, "lat": {"type": ["number", "null"], "minimum": -90, "maximum": 90}, "lon": {"type": ["number", "null"], "minimum": -180, "maximum": 180}, "altitude_m": {"type": "number", "exclusiveMinimum": 0}, "field_yaw_deg": _NUMBER, "yaw_deg": _NUMBER, "target": _TARGET, "target_valid": _BOOLEAN, "skip_if_invalid_target": _BOOLEAN, "tolerance_xy_m": {"type": "number", "exclusiveMinimum": 0}, "tolerance_z_m": {"type": "number", "exclusiveMinimum": 0}, "min_hold_updates": {"type": "integer", "minimum": 1}, "require_velocity_valid": _BOOLEAN, "max_horizontal_speed_mps": {"type": "number", "minimum": 0}, "max_vertical_speed_mps": {"type": "number", "minimum": 0}, "priority": _INTEGER, "key": _STRING, "waypoint_mode": {"type": "string", "enum": ["field", "absolute"]}, "target_frame": {"type": "string", "enum": ["global"]}, "yaw_mode": {"type": "string", "enum": ["field_heading", "hold"]}},
                parameter_aliases={"field_x_m": ("x",), "field_y_m": ("y",), "field_yaw_deg": ("yaw_deg",)},
                parameter_schema_extra={"required": ["altitude_m"], "anyOf": [{"required": ["lat", "lon"]}, {"required": ["field_x_m", "field_y_m"]}]},
                required_inputs=("field_reference", "drone.global_position"), effects=("global_goto",)),
    _definition("target_lock", TargetLockAction, "Select and lock a visual target.",
                {"acquire_mode": "known_target", "max_match_distance_m": 1.0, "min_confidence": 0.0, "detection_source": "scene", "max_updates": 30, "max_target_age_s": 0.5, "require_unique_track": True, "priority": 5, "lock_once": True},
                properties={"target": _TARGET, "skip_if_invalid_target": _BOOLEAN, "acquire_mode": {"type": "string", "enum": ["known_target", "class_single"]}, "max_match_distance_m": {"type": "number", "exclusiveMinimum": 0}, "min_confidence": {"type": "number", "minimum": 0}, "detection_source": {"type": "string", "enum": ["scene", "perception"]}, "max_updates": {"type": "integer", "minimum": 1}, "max_target_age_s": {"type": "number", "exclusiveMinimum": 0}, "require_unique_track": _BOOLEAN, "class_names": _STRING_ARRAY, "camera": _CAMERA, "priority": _INTEGER, "key": _STRING, "lock_once": _BOOLEAN}, output_properties={"locked_track_id": _INTEGER}, required_inputs=("scene", "drone"), effects=("yolo_lock_target",)),
    _definition(
        "align_descend",
        AlignDescendAction,
        "Centre one locked YOLO target with BODY_NED velocity and a fixed yaw, then descend.",
        {"target_altitude_m": 1.2, "max_duration_s": 30.0, "descend_speed_mps": 0.2, "descent_deadband_ex": 0.15, "descent_deadband_ey": 0.15, "alignment_hold_s": 0.0, "max_target_age_s": 0.5, "priority": 5, "max_vx_mps": 0.25, "max_vy_mps": 0.25, "kp_forward": 0.3, "ki_forward": 0.0, "kd_forward": 0.0, "kp_right": 0.3, "ki_right": 0.0, "kd_right": 0.0, "vx_sign": -1.0, "vy_sign": 1.0, "field_yaw_deg": 0.0},
        properties={"track_id": {"type": ["integer", "null"]}, "target_altitude_m": {"type": "number", "exclusiveMinimum": 0}, "finish_altitude_m": {"type": "number", "exclusiveMinimum": 0}, "max_duration_s": {"type": "number", "exclusiveMinimum": 0}, "descend_speed_mps": {"type": "number", "minimum": 0}, "descent_deadband_ex": {"type": "number", "exclusiveMinimum": 0}, "descent_deadband_ey": {"type": "number", "exclusiveMinimum": 0}, "release_deadband_ex": {"type": "number", "exclusiveMinimum": 0}, "release_deadband_ey": {"type": "number", "exclusiveMinimum": 0}, "finish_alignment_max_ex_cam": {"type": "number", "exclusiveMinimum": 0}, "finish_alignment_max_ey_cam": {"type": "number", "exclusiveMinimum": 0}, "alignment_hold_s": {"type": "number", "minimum": 0}, "max_target_age_s": {"type": "number", "exclusiveMinimum": 0}, "payload_forward_m": _NUMBER, "payload_right_m": _NUMBER, "min_correction_speed_mps": {"type": "number", "minimum": 0}, "camera": _CAMERA, "priority": _INTEGER, "key": _STRING, "max_vx_mps": {"type": "number", "exclusiveMinimum": 0}, "max_vy_mps": {"type": "number", "exclusiveMinimum": 0}, "kp_forward": {"type": "number", "minimum": 0}, "ki_forward": {"type": "number", "minimum": 0}, "kd_forward": {"type": "number", "minimum": 0}, "kp_right": {"type": "number", "minimum": 0}, "ki_right": {"type": "number", "minimum": 0}, "kd_right": {"type": "number", "minimum": 0}, "vx_sign": {"type": "number", "enum": [-1, 1]}, "vy_sign": {"type": "number", "enum": [-1, 1]}, "field_yaw_deg": _NUMBER, "desired_yaw_deg": {"type": ["number", "null"]}, "config": _ALIGN_LEGACY_CONFIG, "expected_dt_s": _NUMBER, "lost_timeout_updates": _INTEGER, "hold_updates_required": _INTEGER, "max_retries": _INTEGER, "max_updates": _INTEGER, "finish_policy": _STRING, "finish_alignment_hold_updates": _INTEGER, "finish_alignment_timeout_s": _NUMBER},
        parameter_aliases={"target_altitude_m": ("finish_altitude_m", "config.min_altitude_m"), "descend_speed_mps": ("config.descend_speed_mps",), "descent_deadband_ex": ("config.max_ex_cam",), "descent_deadband_ey": ("config.max_ey_cam",), "release_deadband_ex": ("finish_alignment_max_ex_cam",), "release_deadband_ey": ("finish_alignment_max_ey_cam",), "max_vx_mps": ("config.max_vx_mps",), "max_vy_mps": ("config.max_vy_mps",), "kp_forward": ("config.kp_vx",), "kp_right": ("config.kp_vy",), "vx_sign": ("config.vx_sign",), "vy_sign": ("config.vy_sign",)},
        required_inputs=("perception", "drone.relative_altitude", "field_heading_yaw_rad"), effects=("flight_command",), exit_barrier=ExitBarrier.MOTION_STOPPED),
    _definition("payload_release", PayloadReleaseAction, "Release a whitelisted payload servo through execution.", {"release_wait_updates": 5, "priority": 3}, properties={"payload_id": _ID, "target_id": _ID, "servo_outputs": {"type": "array", "minItems": 1, "items": _SERVO_OUTPUT}, "servo_channels": {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}}, "channels": {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}}, "channel": {"type": "integer", "minimum": 1}, "release_pwm": {"type": "integer", "minimum": 500, "maximum": 2500}, "hold_pwm": {"type": "integer", "minimum": 500, "maximum": 2500}, "release_wait_updates": {"type": "integer", "minimum": 1}, "release_wait_s": {"type": ["number", "null"], "exclusiveMinimum": 0}, "priority": _INTEGER, "key": _STRING, "release_time": {"type": ["number", "string", "null"]}}, parameter_schema_extra={"required": ["payload_id", "target_id"]}, effects=("set_servo",)),
    _definition("select_drop_targets", SelectDropTargetsAction, "Select ranked drop targets.", {"objects": [], "target_count": 2, "min_seen_count": 2, "min_raw_count": 0, "min_weight": 0.0, "deduplicate_radius_m": 0.35, "score_table": {"bucket_1": 500, "bucket_2": 300, "bucket_3": 100, "bucket": 50}, "prefer_class_order": ["bucket_1", "bucket_2", "bucket_3", "bucket"], "allow_fewer": False, "require_local_xy": True, "zone_center_mode": "local", "coordinate_mode": "local"}, properties={"objects": {"type": "array", "items": _LOCALIZED_OBJECT}, "input_key": _STRING, "target_count": {"type": "integer", "minimum": 1}, "min_seen_count": {"type": "integer", "minimum": 0}, "min_raw_count": {"type": "integer", "minimum": 0}, "min_weight": {"type": "number", "minimum": 0}, "deduplicate_radius_m": {"type": "number", "minimum": 0}, "score_table": {"type": "object", "patternProperties": {".*": {"type": "number"}}, "additionalProperties": False}, "prefer_class_order": _STRING_ARRAY, "allow_fewer": _BOOLEAN, "require_local_xy": _BOOLEAN, "single_target_servo_outputs": {"type": ["array", "null"], "items": _SERVO_OUTPUT}, "multi_target_first_servo_outputs": {"type": ["array", "null"], "items": _SERVO_OUTPUT}, "key": _STRING, "zone_center": {"type": ["array", "null"], "minItems": 2, "maxItems": 2, "items": _NUMBER}, "zone_center_mode": {"type": "string", "enum": ["local", "field"]}, "coordinate_mode": {"type": "string", "enum": ["local", "gps_enu"]}}, output_properties={"selected_targets": {"type": "array", "items": _TARGET}, "target_slots": {"type": "array", "items": _TARGET}, "selected_count": _INTEGER, "candidate_count": _INTEGER}, required_inputs=("field_reference",)),
    _definition("gps_capture_view", GpsCaptureViewAction, "Project current-view detections to GPS without moving.", {"class_names": [], "min_confidence": 0.35, "source_waypoint": "view", "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6}}, properties={"class_names": _STRING_ARRAY, "min_confidence": {"type": "number", "minimum": 0}, "source_waypoint": _STRING, "camera": _CAMERA}, output_properties=_GPS_CAPTURE_OUTPUT, required_inputs=("scene", "drone")),
    _definition("gps_fuse_views", GpsFuseViewsAction, "Fuse Mission-captured GPS views.", {"views": [], "fusion": {}, "class_names": []}, properties={"views": {"type": "array", "items": {"type": "object", "properties": _GPS_CAPTURE_OUTPUT, "additionalProperties": False}}, "fusion": {"type": "object", "properties": {"cluster_radius_m": {"type": "number", "minimum": 0}, "outlier_radius_m": {"type": "number", "minimum": 0}, "min_cluster_size": {"type": "integer", "minimum": 1}, "min_source_waypoints": {"type": "integer", "minimum": 1}, "center_weight_power": {"type": "number", "minimum": 0}, "min_confidence": {"type": "number", "minimum": 0}, "max_abs_ex": {"type": ["number", "null"]}, "max_abs_ey": {"type": ["number", "null"]}}, "additionalProperties": False}, "class_names": _STRING_ARRAY}, output_properties={"localized_objects": {"type": "array", "items": _LOCALIZED_OBJECT}, "objects": {"type": "array", "items": _LOCALIZED_OBJECT}, "raw_estimates_count": _INTEGER, "count": _INTEGER, "coordinate_frame": {"type": "string", "const": "GLOBAL"}}, required_inputs=("field_reference",)),
    _definition("gps_target_lock", GpsTargetLockAction, "Lock and confirm a visual track matching a captured GPS target.", {"max_match_distance_m": 1.2, "selection_mode": "nearest_gps", "min_match_margin_m": 0.0, "max_updates": 40, "min_confidence": 0.35, "class_names": [], "camera": {"fov_x_deg": 51.3, "fov_y_deg": 39.6}, "detection_source": "scene", "require_track_id": True, "require_class_match": True, "require_lock_confirmation": True, "max_target_age_s": 0.5}, properties={"target": _TARGET, "max_match_distance_m": {"type": "number", "exclusiveMinimum": 0}, "selection_mode": {"type": "string", "enum": ["nearest_gps", "nearest_image_center"]}, "min_match_margin_m": {"type": "number", "minimum": 0}, "max_updates": {"type": "integer", "minimum": 1}, "min_confidence": {"type": "number", "minimum": 0}, "class_names": _STRING_ARRAY, "camera": _CAMERA, "detection_source": {"type": "string", "enum": ["scene", "perception"]}, "require_track_id": _BOOLEAN, "require_class_match": _BOOLEAN, "require_lock_confirmation": _BOOLEAN, "max_target_age_s": {"type": "number", "exclusiveMinimum": 0}}, parameter_schema_extra={"required": ["target"]}, output_properties={"locked_track_id": _INTEGER}, required_inputs=("scene", "drone", "perception"), effects=("yolo_lock_target",)),
)


def action_definitions() -> tuple[ActionDefinition, ...]:
    return _DEFINITIONS


def action_definition(name: str) -> ActionDefinition:
    for definition in _DEFINITIONS:
        if definition.name == name:
            return definition
    raise KeyError(f"unknown action definition: {name}")


def create_action_lab_registry() -> ActionRegistry:
    registry = ActionRegistry()
    for definition in _DEFINITIONS:
        registry.register(definition.name, definition.factory)
    return registry


def action_lab_specs() -> list[dict]:
    return [definition.web_spec() for definition in _DEFINITIONS]
