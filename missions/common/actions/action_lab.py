"""The single Action definition catalog used by runtime, Web and validators."""
from __future__ import annotations

from missions.definitions import ActionDefinition

from .align_descend import AlignDescendAction
from .build_recon_report import BuildReconReportAction
from .change_speed import ChangeSpeedAction
from .fixed_view_localize import FixedViewLocalizeAction
from .goto_waypoint import GotoWaypointAction
from .gps_capture_view import GpsCaptureViewAction
from .gps_fuse_views import GpsFuseViewsAction
from .gps_target_lock import GpsTargetLockAction
from .land import LandAction
from .manual_step import ManualStepAction
from .payload_release import PayloadReleaseAction
from .recon_rank_views import ReconRankViewsAction
from .recon_score_view import ReconScoreViewAction
from .registry import ActionRegistry
from .resolve_gps_targets import ResolveGpsTargetsAction
from .select_drop_targets import SelectDropTargetsAction
from .select_recon_targets import SelectReconTargetsAction
from .single_view_localize import SingleViewLocalizeAction
from .takeoff import TakeoffAction
from .target_lock import TargetLockAction
from .validate_target import ValidateTargetAction
from .yaw_align import YawAlignAction


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
    _definition("manual_step", ManualStepAction, "Authorized one-shot body-relative step.", {"direction": "forward", "step_m": 0.5, "priority": 2}),
    _definition("takeoff", TakeoffAction, "Arm and take off through the execution safety gates.", {"mode": "GUIDED", "altitude_m": 5.0, "require_armed": True}),
    _definition("land", LandAction, "Land through the execution safety gates."),
    _definition("yaw_align", YawAlignAction, "Align yaw to a configured heading."),
    _definition("change_speed", ChangeSpeedAction, "Set the flight-controller speed target.", {"speed_mps": 1.0, "speed_type": "ground"}),
    _definition("goto_waypoint", GotoWaypointAction, "Go to a global target or schema-v3 FIELD target.", {"x": 0.0, "y": 5.5, "altitude_m": 3.5, "waypoint_mode": "field", "target_frame": "global"}),
    _definition("single_view_localize", SingleViewLocalizeAction, "Localize detections from one captured view."),
    _definition("target_lock", TargetLockAction, "Select and lock a visual target."),
    _definition("align_descend", AlignDescendAction, "Align over a target and descend with deadman safety."),
    _definition("payload_release", PayloadReleaseAction, "Release a whitelisted payload servo through execution."),
    _definition("select_drop_targets", SelectDropTargetsAction, "Select ranked drop targets."),
    _definition("select_recon_targets", SelectReconTargetsAction, "Select ranked reconnaissance targets."),
    _definition("build_recon_report", BuildReconReportAction, "Build the reconnaissance result report."),
    _definition("fixed_view_localize", FixedViewLocalizeAction, "Localize from a fixed view."),
    _definition("resolve_gps_targets", ResolveGpsTargetsAction, "Resolve targets to global GPS."),
    _definition("validate_target", ValidateTargetAction, "Validate a selected target."),
    _definition("gps_capture_view", GpsCaptureViewAction, "Project current-view detections to GPS without moving."),
    _definition("gps_fuse_views", GpsFuseViewsAction, "Fuse Mission-captured GPS views."),
    _definition("gps_target_lock", GpsTargetLockAction, "Lock a target using captured GPS pose."),
    _definition("recon_score_view", ReconScoreViewAction, "Score danger signs from a stationary view."),
    _definition("recon_rank_views", ReconRankViewsAction, "Aggregate Mission-captured reconnaissance views."),
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
