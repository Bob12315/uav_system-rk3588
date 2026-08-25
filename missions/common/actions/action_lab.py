"""The single Action definition catalog used by runtime, Web and validators."""
from __future__ import annotations

from missions.definitions import ActionDefinition

from .align_descend import AlignDescendAction
from .change_speed import ChangeSpeedAction
from .fixed_view_localize import FixedViewLocalizeAction
from .goto_waypoint import GotoWaypointAction
from .gps_capture_view import GpsCaptureViewAction
from .gps_fuse_views import GpsFuseViewsAction
from .gps_target_lock import GpsTargetLockAction
from .land import LandAction
from .payload_release import PayloadReleaseAction
from .registry import ActionRegistry
from .resolve_gps_targets import ResolveGpsTargetsAction
from .select_drop_targets import SelectDropTargetsAction
from .single_view_localize import SingleViewLocalizeAction
from .takeoff import TakeoffAction
from .target_lock import TargetLockAction
from .validate_target import ValidateTargetAction


def _definition(
    name: str,
    factory,
    description: str,
    defaults: dict | None = None,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        factory=factory,
        label=name.replace("_", " ").title(),
        description=description,
        default_params=dict(defaults or {}),
        parameter_schema={"type": "object", "additionalProperties": True},
    )


_DEFINITIONS = (
    _definition("takeoff", TakeoffAction, "Arm and take off through the execution safety gates.", {"mode": "GUIDED", "altitude_m": 5.0, "require_armed": True}),
    _definition("land", LandAction, "Land through the execution safety gates."),
    _definition("change_speed", ChangeSpeedAction, "Set the flight-controller speed target.", {"speed_mps": 1.0, "speed_type": "ground"}),
    _definition("goto_waypoint", GotoWaypointAction, "Convert a FIELD target to GPS and fly with fixed FIELD-relative yaw.", {"field_x_m": 0.0, "field_y_m": 5.5, "altitude_m": 3.5, "field_yaw_deg": 0.0}),
    _definition("single_view_localize", SingleViewLocalizeAction, "Localize detections from one captured view."),
    _definition("target_lock", TargetLockAction, "Select and lock a visual target."),
    _definition(
        "align_descend",
        AlignDescendAction,
        "Centre one locked YOLO target with BODY_NED velocity and a fixed yaw, then descend.",
        {"target_altitude_m": 1.2, "field_yaw_deg": 0.0, "max_duration_s": 30.0},
    ),
    _definition("payload_release", PayloadReleaseAction, "Release a whitelisted payload servo through execution."),
    _definition("select_drop_targets", SelectDropTargetsAction, "Select ranked drop targets."),
    _definition("fixed_view_localize", FixedViewLocalizeAction, "Localize from a fixed view."),
    _definition("resolve_gps_targets", ResolveGpsTargetsAction, "Resolve targets to global GPS."),
    _definition("validate_target", ValidateTargetAction, "Validate a selected target."),
    _definition("gps_capture_view", GpsCaptureViewAction, "Project current-view detections to GPS without moving."),
    _definition("gps_fuse_views", GpsFuseViewsAction, "Fuse Mission-captured GPS views."),
    _definition("gps_target_lock", GpsTargetLockAction, "Lock a target using captured GPS pose."),
)


def action_definitions() -> tuple[ActionDefinition, ...]:
    return _DEFINITIONS


def create_action_lab_registry() -> ActionRegistry:
    registry = ActionRegistry()
    for definition in _DEFINITIONS:
        registry.register(definition.name, definition.factory)
    return registry


def action_lab_specs() -> list[dict]:
    return [definition.web_spec() for definition in _DEFINITIONS]
