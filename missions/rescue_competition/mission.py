from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fusion.models import SceneDetections, SceneObject
from missions.base import MissionAction, MissionContext, MissionOutput
from missions.common.navigation import (
    LocalMissionFrame,
    LocalGoal,
    hold_elapsed,
    local_goal_stable,
    mission_to_local_position,
    to_mission_position,
)
from missions.rescue_competition.geometry import (
    CameraGeometryConfig,
    detection_to_mission_xy,
)
from missions.rescue_competition.recce_report import RecceResult, write_recce_report
from missions.rescue_competition.survey import (
    EstimatedObject,
    SurveyTarget,
    cluster_estimates,
    select_targets,
)
from telemetry_link.models import DroneState


class RescueStage(str, Enum):
    PREPARE = "PREPARE"
    ARM = "ARM"
    TAKEOFF = "TAKEOFF"
    GOTO_DROP_SURVEY = "GOTO_DROP_SURVEY"
    SURVEY_DROP_POINTS = "SURVEY_DROP_POINTS"
    PLAN_DROP_TARGETS = "PLAN_DROP_TARGETS"
    GOTO_DROP_TARGET = "GOTO_DROP_TARGET"
    LOCK_DROP_TARGET = "LOCK_DROP_TARGET"
    ALIGN_DESCEND_DROP = "ALIGN_DESCEND_DROP"
    RELEASE_PAYLOAD = "RELEASE_PAYLOAD"
    ASCEND_AFTER_DROP = "ASCEND_AFTER_DROP"
    NEXT_DROP_OR_RECCE = "NEXT_DROP_OR_RECCE"
    GOTO_RECCE_SURVEY = "GOTO_RECCE_SURVEY"
    SURVEY_RECCE_POINTS = "SURVEY_RECCE_POINTS"
    PLAN_RECCE_TARGETS = "PLAN_RECCE_TARGETS"
    GOTO_RECCE_TARGET = "GOTO_RECCE_TARGET"
    LOCK_RECCE_TARGET = "LOCK_RECCE_TARGET"
    ALIGN_DESCEND_RECCE = "ALIGN_DESCEND_RECCE"
    CAPTURE_RECCE = "CAPTURE_RECCE"
    ASCEND_AFTER_RECCE = "ASCEND_AFTER_RECCE"
    NEXT_RECCE_OR_REPORT = "NEXT_RECCE_OR_REPORT"
    REPORT_RECCE = "REPORT_RECCE"
    RETURN_HOME = "RETURN_HOME"
    LAND = "LAND"
    FINISH = "FINISH"
    FAILSAFE = "FAILSAFE"


@dataclass(slots=True)
class SurveyPoint:
    name: str
    x: float
    y: float


@dataclass(slots=True)
class PayloadSlot:
    payload_id: int
    servo_channel: int
    hold_pwm: int
    release_pwm: int
    drop_center_x: float = 0.0
    drop_center_y: float = 0.0

    def to_detail(self) -> dict[str, object]:
        return {
            "payload_id": self.payload_id,
            "servo_channel": self.servo_channel,
            "hold_pwm": self.hold_pwm,
            "release_pwm": self.release_pwm,
            "drop_center_x": self.drop_center_x,
            "drop_center_y": self.drop_center_y,
        }


@dataclass(slots=True)
class RouteConfig:
    home_x: float = 0.0
    home_y: float = 0.0
    drop_area_x: float = 30.0
    drop_area_y: float = 0.0
    recce_area_x: float = 55.0
    recce_area_y: float = 0.0


@dataclass(slots=True)
class DropConfig:
    required_payload_drops: int = 2
    survey_altitude_m: float = 5.0
    transit_altitude_m: float = 3.0
    release_altitude_m: float = 1.0
    survey_hold_s: float = 1.2
    target_count: int = 2
    survey_points: list[SurveyPoint] = field(default_factory=list)


@dataclass(slots=True)
class PayloadConfig:
    release_wait_s: float = 1.0
    return_hold_pwm_after_release: bool = True


@dataclass(slots=True)
class RecceConfig:
    survey_altitude_m: float = 5.0
    transit_altitude_m: float = 3.0
    identify_altitude_m: float = 2.0
    visual_descend_altitude_m: float = 1.0
    survey_hold_s: float = 1.2
    capture_hold_s: float = 1.5
    visit_max_count: int = 5
    required_confirmed_count: int = 3
    vote_min_count: int = 3
    vote_min_confidence_sum: float = 1.2
    output_dir: str = "runtime/logs/recce"
    survey_points: list[SurveyPoint] = field(default_factory=list)


@dataclass(slots=True)
class VisionConfig:
    geometry: CameraGeometryConfig = field(default_factory=CameraGeometryConfig)
    cylinder_classes: set[str] = field(default_factory=lambda: {"cylinder"})
    hazard_classes: set[str] = field(default_factory=set)
    min_cylinder_confidence: float = 0.4
    min_hazard_confidence: float = 0.4
    cluster_radius_m: float = 0.8
    edge_margin_norm: float = 0.85
    lock_center_max_error: float = 0.65


@dataclass(slots=True)
class AlignMissionConfig:
    max_ex_cam: float = 0.06
    max_ey_cam: float = 0.06
    hold_s: float = 0.5
    lost_timeout_s: float = 1.0
    min_altitude_m: float = 0.8


@dataclass(slots=True)
class RescueCompetitionMissionConfig:
    initial_stage: RescueStage = RescueStage.PREPARE
    idle_mode: str = "IDLE"
    align_mode: str = "DOWNWARD_ALIGN_DESCEND"
    auto_start: bool = False
    takeoff_altitude_m: float = 5.0
    takeoff_altitude_tolerance_m: float = 0.5
    land_complete_altitude_m: float = 0.3
    local_position_frame: int = 1
    xy_tolerance_m: float = 0.6
    z_tolerance_m: float = 0.35
    max_goal_speed_mps: float = 0.5
    route: RouteConfig = field(default_factory=RouteConfig)
    drop: DropConfig = field(default_factory=DropConfig)
    payload: PayloadConfig = field(default_factory=PayloadConfig)
    payload_slots: list[PayloadSlot] = field(default_factory=list)
    recce: RecceConfig = field(default_factory=RecceConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    align: AlignMissionConfig = field(default_factory=AlignMissionConfig)


@dataclass(slots=True)
class RescueCompetitionMission:
    config: RescueCompetitionMissionConfig = field(default_factory=RescueCompetitionMissionConfig)

    name: str = "rescue_competition"
    _stage: RescueStage = field(init=False)
    _previous_stage: RescueStage | None = field(init=False, default=None)
    _origin: LocalMissionFrame | None = field(init=False, default=None)
    _stage_started_at: float | None = field(init=False, default=None)
    _goal_reached_since: float | None = field(init=False, default=None)
    _drop_scan_index: int = field(init=False, default=0)
    _drop_estimates: list[EstimatedObject] = field(init=False, default_factory=list)
    _drop_targets: list[SurveyTarget] = field(init=False, default_factory=list)
    _drop_target_index: int = field(init=False, default=0)
    _drop_count: int = field(init=False, default=0)
    _release_started_at: float | None = field(init=False, default=None)
    _recce_scan_index: int = field(init=False, default=0)
    _recce_estimates: list[EstimatedObject] = field(init=False, default_factory=list)
    _recce_targets: list[SurveyTarget] = field(init=False, default_factory=list)
    _recce_target_index: int = field(init=False, default=0)
    _recce_results: list[RecceResult] = field(init=False, default_factory=list)
    _recce_votes: dict[str, tuple[int, float]] = field(init=False, default_factory=dict)
    _recce_report_path: str = field(init=False, default="")
    _start_requested: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._stage = self.config.initial_stage
        self._previous_stage = None
        self._origin = None
        self._stage_started_at = None
        self._goal_reached_since = None
        self._drop_scan_index = 0
        self._drop_estimates = []
        self._drop_targets = []
        self._drop_target_index = 0
        self._drop_count = 0
        self._release_started_at = None
        self._recce_scan_index = 0
        self._recce_estimates = []
        self._recce_targets = []
        self._recce_target_index = 0
        self._recce_results = []
        self._recce_votes = {}
        self._recce_report_path = ""
        self._start_requested = False

    def start(self) -> None:
        self._start_requested = True

    def set_stage(self, stage: str) -> None:
        self._transition_to(_stage_value(stage))

    def clear_forced_stage(self) -> None:
        return None

    def update(self, context: MissionContext) -> MissionOutput:
        if self._stage_started_at is None:
            self._stage_started_at = float(context.timestamp)
        actions: list[MissionAction] = []
        active_mode = self.config.idle_mode
        hold_reason = ""
        target_error_offset: dict[str, float] | None = None

        if self._stage == RescueStage.PREPARE:
            hold_reason = self._prepare(context)
        elif self._stage == RescueStage.ARM:
            hold_reason = self._arm(context, actions)
        elif self._stage == RescueStage.TAKEOFF:
            hold_reason = self._takeoff(context, actions)
        elif self._stage == RescueStage.GOTO_DROP_SURVEY:
            hold_reason = self._goto_drop_survey(context, actions)
        elif self._stage == RescueStage.SURVEY_DROP_POINTS:
            hold_reason = self._survey_drop(context, actions)
        elif self._stage == RescueStage.PLAN_DROP_TARGETS:
            hold_reason = self._plan_drop_targets()
        elif self._stage == RescueStage.GOTO_DROP_TARGET:
            hold_reason = self._goto_current_drop_target(context, actions)
        elif self._stage == RescueStage.LOCK_DROP_TARGET:
            hold_reason = self._lock_target(context, actions, recce=False)
        elif self._stage == RescueStage.ALIGN_DESCEND_DROP:
            active_mode = self.config.align_mode
            target_error_offset = self._current_payload_offset()
            hold_reason = self._align_descend_drop(context)
        elif self._stage == RescueStage.RELEASE_PAYLOAD:
            hold_reason = self._release_payload(context, actions)
        elif self._stage == RescueStage.ASCEND_AFTER_DROP:
            hold_reason = self._ascend_after_drop(context, actions)
        elif self._stage == RescueStage.NEXT_DROP_OR_RECCE:
            hold_reason = self._next_drop_or_recce()
        elif self._stage == RescueStage.GOTO_RECCE_SURVEY:
            hold_reason = self._goto_recce_survey(context, actions)
        elif self._stage == RescueStage.SURVEY_RECCE_POINTS:
            hold_reason = self._survey_recce(context, actions)
        elif self._stage == RescueStage.PLAN_RECCE_TARGETS:
            hold_reason = self._plan_recce_targets()
        elif self._stage == RescueStage.GOTO_RECCE_TARGET:
            hold_reason = self._goto_current_recce_target(context, actions)
        elif self._stage == RescueStage.LOCK_RECCE_TARGET:
            hold_reason = self._lock_target(context, actions, recce=True)
        elif self._stage == RescueStage.ALIGN_DESCEND_RECCE:
            active_mode = self.config.align_mode
            hold_reason = self._align_descend_recce(context)
        elif self._stage == RescueStage.CAPTURE_RECCE:
            hold_reason = self._capture_recce(context)
        elif self._stage == RescueStage.ASCEND_AFTER_RECCE:
            hold_reason = self._ascend_after_recce(context, actions)
        elif self._stage == RescueStage.NEXT_RECCE_OR_REPORT:
            hold_reason = self._next_recce_or_report()
        elif self._stage == RescueStage.REPORT_RECCE:
            hold_reason = self._report_recce(context)
        elif self._stage == RescueStage.RETURN_HOME:
            hold_reason = self._return_home(context, actions)
        elif self._stage == RescueStage.LAND:
            hold_reason = self._land(context, actions)
        elif self._stage == RescueStage.FINISH:
            hold_reason = "finished"
        elif self._stage == RescueStage.FAILSAFE:
            hold_reason = "failsafe"

        detail = self._detail(context.drone)
        if target_error_offset is not None:
            detail["target_error_offset"] = target_error_offset
        return MissionOutput(
            active_mode=active_mode,
            actions=actions,
            stage=self._stage.value,
            previous_stage=self._previous_stage.value if self._previous_stage else None,
            hold_reason=hold_reason,
            done=self._stage == RescueStage.FINISH,
            aborted=self._stage == RescueStage.FAILSAFE,
            detail=detail,
        )

    def _prepare(self, context: MissionContext) -> str:
        if not (self.config.auto_start or self._start_requested):
            return "waiting_start"
        if not context.drone.local_position_valid:
            return "waiting_local_position"
        self._transition_to(RescueStage.ARM)
        return "auto_start"

    def _arm(self, context: MissionContext, actions: list[MissionAction]) -> str:
        actions.append(MissionAction("arm", key="rescue_arm", once=True))
        if context.drone.armed and context.drone.local_position_valid:
            self._origin = LocalMissionFrame(
                origin_x=float(context.drone.local_x),
                origin_y=float(context.drone.local_y),
                origin_z=float(context.drone.local_z),
                yaw_rad=float(context.drone.yaw),
            )
            self._transition_to(RescueStage.TAKEOFF)
            return "armed"
        return "waiting_armed"

    def _takeoff(self, context: MissionContext, actions: list[MissionAction]) -> str:
        actions.append(
            MissionAction(
                "takeoff",
                {"altitude_m": self.config.takeoff_altitude_m},
                key="rescue_takeoff",
                once=True,
            )
        )
        if (
            context.drone.relative_alt_valid
            and context.drone.relative_altitude
            >= self.config.takeoff_altitude_m - self.config.takeoff_altitude_tolerance_m
        ):
            self._transition_to(RescueStage.GOTO_DROP_SURVEY)
            return "takeoff_altitude_reached"
        return "taking_off"

    def _goto_drop_survey(self, context: MissionContext, actions: list[MissionAction]) -> str:
        if not self.config.drop.survey_points:
            self._transition_to(RescueStage.FAILSAFE)
            return "no_drop_survey_points"
        point = self.config.drop.survey_points[0]
        if self._goto_xy_alt(context, actions, point.x, point.y, self.config.drop.survey_altitude_m, "drop_survey_0"):
            self._transition_to(RescueStage.SURVEY_DROP_POINTS)
            return "drop_survey_start"
        return "goto_drop_survey"

    def _survey_drop(self, context: MissionContext, actions: list[MissionAction]) -> str:
        if self._drop_scan_index >= len(self.config.drop.survey_points):
            self._transition_to(RescueStage.PLAN_DROP_TARGETS)
            return "drop_survey_complete"
        point = self.config.drop.survey_points[self._drop_scan_index]
        if not self._goto_xy_alt(
            context,
            actions,
            point.x,
            point.y,
            self.config.drop.survey_altitude_m,
            f"drop_survey_{self._drop_scan_index}",
        ):
            return f"goto_{point.name}"
        self._collect_cylinders(context, self._drop_estimates, point.name)
        if self._goal_reached_since is None:
            self._goal_reached_since = float(context.timestamp)
        if hold_elapsed(context.timestamp, self._goal_reached_since, self.config.drop.survey_hold_s):
            self._drop_scan_index += 1
            self._goal_reached_since = None
        return f"survey_{point.name}"

    def _plan_drop_targets(self) -> str:
        clusters = cluster_estimates(
            self._drop_estimates,
            radius_m=self.config.vision.cluster_radius_m,
        )
        self._drop_targets = select_targets(
            clusters,
            count=self.config.drop.target_count,
            min_separation_m=self.config.vision.cluster_radius_m,
        )
        if len(self._drop_targets) < self.config.drop.required_payload_drops:
            self._transition_to(RescueStage.FAILSAFE)
            return "not_enough_drop_targets"
        self._transition_to(RescueStage.GOTO_DROP_TARGET)
        return "drop_targets_planned"

    def _goto_current_drop_target(self, context: MissionContext, actions: list[MissionAction]) -> str:
        target = self._current_drop_target()
        if target is None:
            self._transition_to(RescueStage.NEXT_DROP_OR_RECCE)
            return "no_drop_target"
        if self._goto_xy_alt(
            context,
            actions,
            target.x,
            target.y,
            self.config.drop.transit_altitude_m,
            f"drop_target_{target.target_id}",
        ):
            self._transition_to(RescueStage.LOCK_DROP_TARGET)
            return "at_drop_target"
        return "goto_drop_target"

    def _lock_target(self, context: MissionContext, actions: list[MissionAction], *, recce: bool) -> str:
        target = self._current_recce_target() if recce else self._current_drop_target()
        if target is None:
            self._transition_to(RescueStage.NEXT_RECCE_OR_REPORT if recce else RescueStage.NEXT_DROP_OR_RECCE)
            return "no_target"
        detection = self._select_center_lock_detection(context) if recce else self._select_lock_detection(context, target)
        if detection is None or detection.track_id is None:
            return "waiting_lock_candidate"
        actions.append(
            MissionAction(
                "yolo_lock_target",
                {"track_id": int(detection.track_id)},
                key=f"rescue_lock_{'recce' if recce else 'drop'}_{target.target_id}_{int(context.timestamp * 10)}",
                once=True,
            )
        )
        self._transition_to(RescueStage.ALIGN_DESCEND_RECCE if recce else RescueStage.ALIGN_DESCEND_DROP)
        return "lock_target_requested"

    def _align_descend_drop(self, context: MissionContext) -> str:
        if self._height_m(context.drone) <= max(self.config.drop.release_altitude_m, self.config.align.min_altitude_m):
            if self._aligned(context):
                self._transition_to(RescueStage.RELEASE_PAYLOAD)
                return "drop_release_altitude_reached"
            return "align_at_release_altitude"
        return "align_descend_drop"

    def _release_payload(self, context: MissionContext, actions: list[MissionAction]) -> str:
        slot = self._current_payload()
        if slot is None:
            self._transition_to(RescueStage.FAILSAFE)
            return "no_payload_slot"
        if self._release_started_at is None:
            actions.append(
                MissionAction(
                    "set_servo",
                    {"channel": slot.servo_channel, "pwm": slot.release_pwm},
                    key=f"release_payload_{slot.payload_id}",
                    once=True,
                )
            )
            self._release_started_at = float(context.timestamp)
            return "payload_release_requested"
        if not hold_elapsed(context.timestamp, self._release_started_at, self.config.payload.release_wait_s):
            return "waiting_payload_release"
        if self.config.payload.return_hold_pwm_after_release:
            actions.append(
                MissionAction(
                    "set_servo",
                    {"channel": slot.servo_channel, "pwm": slot.hold_pwm},
                    key=f"hold_payload_{slot.payload_id}",
                    once=True,
                )
            )
        self._drop_count += 1
        target = self._current_drop_target()
        if target is not None:
            target.visited = True
        self._release_started_at = None
        actions.append(
            MissionAction(
                "yolo_unlock_target",
                key=f"unlock_after_drop_{slot.payload_id}",
                once=True,
            )
        )
        self._transition_to(RescueStage.ASCEND_AFTER_DROP)
        return "payload_released"

    def _ascend_after_drop(self, context: MissionContext, actions: list[MissionAction]) -> str:
        target = self._current_drop_target()
        x = self.config.route.drop_area_x if target is None else target.x
        y = self.config.route.drop_area_y if target is None else target.y
        if self._goto_xy_alt(context, actions, x, y, self.config.drop.transit_altitude_m, "ascend_drop"):
            self._drop_target_index += 1
            self._transition_to(RescueStage.NEXT_DROP_OR_RECCE)
            return "drop_transit_altitude_reached"
        return "ascending_after_drop"

    def _next_drop_or_recce(self) -> str:
        if self._drop_count >= self.config.drop.required_payload_drops:
            self._transition_to(RescueStage.GOTO_RECCE_SURVEY)
            return "drop_complete"
        if self._drop_target_index >= len(self._drop_targets):
            self._transition_to(RescueStage.FAILSAFE)
            return "drop_incomplete_no_targets"
        self._transition_to(RescueStage.GOTO_DROP_TARGET)
        return "next_drop_target"

    def _goto_recce_survey(self, context: MissionContext, actions: list[MissionAction]) -> str:
        if self._drop_count < self.config.drop.required_payload_drops:
            self._transition_to(RescueStage.FAILSAFE)
            return "drop_gate_failed"
        if not self.config.recce.survey_points:
            self._transition_to(RescueStage.FAILSAFE)
            return "no_recce_survey_points"
        point = self.config.recce.survey_points[0]
        if self._goto_xy_alt(context, actions, point.x, point.y, self.config.recce.survey_altitude_m, "recce_survey_0"):
            self._transition_to(RescueStage.SURVEY_RECCE_POINTS)
            return "recce_survey_start"
        return "goto_recce_survey"

    def _survey_recce(self, context: MissionContext, actions: list[MissionAction]) -> str:
        if self._recce_scan_index >= len(self.config.recce.survey_points):
            self._transition_to(RescueStage.PLAN_RECCE_TARGETS)
            return "recce_survey_complete"
        point = self.config.recce.survey_points[self._recce_scan_index]
        if not self._goto_xy_alt(
            context,
            actions,
            point.x,
            point.y,
            self.config.recce.survey_altitude_m,
            f"recce_survey_{self._recce_scan_index}",
        ):
            return f"goto_{point.name}"
        self._collect_cylinders(context, self._recce_estimates, point.name)
        if self._goal_reached_since is None:
            self._goal_reached_since = float(context.timestamp)
        if hold_elapsed(context.timestamp, self._goal_reached_since, self.config.recce.survey_hold_s):
            self._recce_scan_index += 1
            self._goal_reached_since = None
        return f"survey_{point.name}"

    def _plan_recce_targets(self) -> str:
        clusters = cluster_estimates(
            self._recce_estimates,
            radius_m=self.config.vision.cluster_radius_m,
        )
        self._recce_targets = select_targets(
            clusters,
            count=self.config.recce.visit_max_count,
            min_separation_m=self.config.vision.cluster_radius_m,
        )
        if not self._recce_targets:
            self._transition_to(RescueStage.REPORT_RECCE)
            return "no_recce_targets"
        self._transition_to(RescueStage.GOTO_RECCE_TARGET)
        return "recce_targets_planned"

    def _goto_current_recce_target(self, context: MissionContext, actions: list[MissionAction]) -> str:
        target = self._current_recce_target()
        if target is None:
            self._transition_to(RescueStage.REPORT_RECCE)
            return "no_recce_target"
        if self._goto_xy_alt(
            context,
            actions,
            target.x,
            target.y,
            self.config.recce.identify_altitude_m,
            f"recce_target_{target.target_id}",
        ):
            self._transition_to(RescueStage.LOCK_RECCE_TARGET)
            return "at_recce_target"
        return "goto_recce_target"

    def _align_descend_recce(self, context: MissionContext) -> str:
        target_altitude_m = max(
            self.config.recce.visual_descend_altitude_m,
            self.config.align.min_altitude_m,
        )
        if self._height_m(context.drone) <= target_altitude_m:
            self._transition_to(RescueStage.CAPTURE_RECCE)
            return "recce_visual_descend_altitude_reached"
        return "align_descend_recce"

    def _capture_recce(self, context: MissionContext) -> str:
        target = self._current_recce_target()
        if target is None:
            self._transition_to(RescueStage.NEXT_RECCE_OR_REPORT)
            return "no_recce_target"
        self._collect_hazard_votes(context)
        if hold_elapsed(context.timestamp, self._stage_started_at, self.config.recce.capture_hold_s):
            result = self._build_recce_result(target)
            self._recce_results.append(result)
            target.visited = True
            self._recce_votes = {}
            self._transition_to(RescueStage.ASCEND_AFTER_RECCE)
            return "recce_capture_complete"
        return "capturing_recce"

    def _ascend_after_recce(self, context: MissionContext, actions: list[MissionAction]) -> str:
        target = self._current_recce_target()
        x = self.config.route.recce_area_x if target is None else target.x
        y = self.config.route.recce_area_y if target is None else target.y
        if self._goto_xy_alt(context, actions, x, y, self.config.recce.transit_altitude_m, "ascend_recce"):
            self._recce_target_index += 1
            actions.append(MissionAction("yolo_unlock_target", key=f"unlock_after_recce_{self._recce_target_index}", once=True))
            self._transition_to(RescueStage.NEXT_RECCE_OR_REPORT)
            return "recce_transit_altitude_reached"
        return "ascending_after_recce"

    def _next_recce_or_report(self) -> str:
        confirmed = sum(1 for item in self._recce_results if item.status == "confirmed")
        if confirmed >= self.config.recce.required_confirmed_count:
            self._transition_to(RescueStage.REPORT_RECCE)
            return "recce_confirmed_complete"
        if self._recce_target_index >= len(self._recce_targets):
            self._transition_to(RescueStage.REPORT_RECCE)
            return "recce_targets_exhausted"
        self._transition_to(RescueStage.GOTO_RECCE_TARGET)
        return "next_recce_target"

    def _report_recce(self, context: MissionContext) -> str:
        if not self._recce_report_path:
            self._recce_report_path = write_recce_report(
                output_dir=self.config.recce.output_dir,
                timestamp=context.timestamp,
                results=self._recce_results,
            )
        self._transition_to(RescueStage.RETURN_HOME)
        return "recce_report_written"

    def _return_home(self, context: MissionContext, actions: list[MissionAction]) -> str:
        if self._goto_xy_alt(
            context,
            actions,
            self.config.route.home_x,
            self.config.route.home_y,
            self.config.drop.transit_altitude_m,
            "return_home",
        ):
            self._transition_to(RescueStage.LAND)
            return "home_reached"
        return "returning_home"

    def _land(self, context: MissionContext, actions: list[MissionAction]) -> str:
        actions.append(MissionAction("land", key="rescue_land", once=True))
        if context.drone.relative_alt_valid and context.drone.relative_altitude <= self.config.land_complete_altitude_m:
            self._transition_to(RescueStage.FINISH)
            return "landed"
        return "landing"

    def _goto_xy_alt(
        self,
        context: MissionContext,
        actions: list[MissionAction],
        x: float,
        y: float,
        altitude_m: float,
        key: str,
    ) -> bool:
        if self._origin is None:
            return False
        goal = LocalGoal(
            name=key,
            x=float(x),
            y=float(y),
            z=-abs(float(altitude_m)),
            xy_tolerance_m=self.config.xy_tolerance_m,
            z_tolerance_m=self.config.z_tolerance_m,
            max_speed_mps=self.config.max_goal_speed_mps,
        )
        lx, ly, lz = mission_to_local_position((goal.x, goal.y, goal.z), self._origin)
        actions.append(
            MissionAction(
                "local_position",
                {
                    "x": lx,
                    "y": ly,
                    "z": lz,
                    "frame": self.config.local_position_frame,
                    "yaw": self._origin.yaw_rad,
                },
                key=f"goto_{key}",
                once=False,
            )
        )
        if not context.drone.local_position_valid:
            return False
        current = to_mission_position(context.drone, self._origin)
        target = (goal.x, goal.y, goal.z)
        stable = local_goal_stable(
            context.drone,
            current,
            target,
            goal.xy_tolerance_m,
            goal.z_tolerance_m,
            goal.max_speed_mps,
        )
        if stable:
            if self._goal_reached_since is None:
                self._goal_reached_since = float(context.timestamp)
            return True
        self._goal_reached_since = None
        return False

    def _collect_cylinders(
        self,
        context: MissionContext,
        estimates: list[EstimatedObject],
        source: str,
    ) -> None:
        scene = context.scene
        if scene is None or not scene.valid:
            return
        position = self._mission_position(context.drone)
        if position is None:
            return
        altitude_m = self._height_m(context.drone)
        for detection in scene.detections:
            if not self._is_cylinder(detection):
                continue
            if abs(float(detection.ex)) > self.config.vision.edge_margin_norm:
                continue
            if abs(float(detection.ey)) > self.config.vision.edge_margin_norm:
                continue
            x, y = detection_to_mission_xy(
                detection,
                drone_mission_x=position[0],
                drone_mission_y=position[1],
                altitude_m=altitude_m,
                config=self.config.vision.geometry,
                drone_yaw_rad=float(context.drone.yaw),
                mission_yaw_rad=float(self._origin.yaw_rad) if self._origin is not None else 0.0,
            )
            estimates.append(
                EstimatedObject(
                    class_name=detection.class_name,
                    confidence=detection.confidence,
                    target_size=detection.target_size,
                    x=x,
                    y=y,
                    track_id=detection.track_id,
                    source=source,
                    timestamp=context.timestamp,
                )
            )

    def _select_lock_detection(
        self,
        context: MissionContext,
        target: SurveyTarget,
    ) -> SceneObject | None:
        scene = context.scene
        if scene is None or not scene.valid:
            return None
        position = self._mission_position(context.drone)
        if position is None:
            return None
        altitude_m = self._height_m(context.drone)
        candidates: list[tuple[float, SceneObject]] = []
        for detection in scene.detections:
            if not self._is_cylinder(detection):
                continue
            if math.hypot(float(detection.ex), float(detection.ey)) > self.config.vision.lock_center_max_error:
                continue
            x, y = detection_to_mission_xy(
                detection,
                drone_mission_x=position[0],
                drone_mission_y=position[1],
                altitude_m=altitude_m,
                config=self.config.vision.geometry,
                drone_yaw_rad=float(context.drone.yaw),
                mission_yaw_rad=float(self._origin.yaw_rad) if self._origin is not None else 0.0,
            )
            candidates.append((math.hypot(x - target.x, y - target.y), detection))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])[1]

    def _select_center_lock_detection(self, context: MissionContext) -> SceneObject | None:
        scene = context.scene
        if scene is None or not scene.valid:
            return None
        candidates = [
            detection
            for detection in scene.detections
            if self._is_cylinder(detection)
            and math.hypot(float(detection.ex), float(detection.ey)) <= self.config.vision.lock_center_max_error
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: math.hypot(float(item.ex), float(item.ey)))

    def _collect_hazard_votes(self, context: MissionContext) -> None:
        scene = context.scene
        if scene is None or not scene.valid:
            return
        for detection in scene.detections:
            name = detection.class_name.strip().lower()
            if name not in self.config.vision.hazard_classes:
                continue
            if detection.confidence < self.config.vision.min_hazard_confidence:
                continue
            count, confidence = self._recce_votes.get(name, (0, 0.0))
            self._recce_votes[name] = (count + 1, confidence + float(detection.confidence))

    def _build_recce_result(self, target: SurveyTarget) -> RecceResult:
        if not self._recce_votes:
            return RecceResult(target.target_id, target.x, target.y, status="blank")
        hazard, (count, confidence_sum) = max(
            self._recce_votes.items(),
            key=lambda item: (item[1][0], item[1][1]),
        )
        confirmed = (
            count >= self.config.recce.vote_min_count
            and confidence_sum >= self.config.recce.vote_min_confidence_sum
        )
        return RecceResult(
            target_id=target.target_id,
            x=target.x,
            y=target.y,
            hazard_class=hazard if confirmed else None,
            vote_count=count,
            confidence_sum=confidence_sum,
            status="confirmed" if confirmed else "blank",
        )

    def _is_cylinder(self, detection: SceneObject) -> bool:
        return (
            detection.class_name.strip().lower() in self.config.vision.cylinder_classes
            and detection.confidence >= self.config.vision.min_cylinder_confidence
        )

    def _current_drop_target(self) -> SurveyTarget | None:
        if 0 <= self._drop_target_index < len(self._drop_targets):
            return self._drop_targets[self._drop_target_index]
        return None

    def _current_recce_target(self) -> SurveyTarget | None:
        if 0 <= self._recce_target_index < len(self._recce_targets):
            return self._recce_targets[self._recce_target_index]
        return None

    def _current_payload(self) -> PayloadSlot | None:
        if 0 <= self._drop_count < len(self.config.payload_slots):
            return self.config.payload_slots[self._drop_count]
        return None

    def _current_payload_offset(self) -> dict[str, float]:
        slot = self._current_payload()
        if slot is None:
            return {"ex_cam": 0.0, "ey_cam": 0.0}
        return {"ex_cam": slot.drop_center_x, "ey_cam": slot.drop_center_y}

    def _aligned(self, context: MissionContext) -> bool:
        return (
            context.inputs.target_valid
            and abs(float(context.inputs.ex_cam)) <= self.config.align.max_ex_cam
            and abs(float(context.inputs.ey_cam)) <= self.config.align.max_ey_cam
        )

    def _height_m(self, drone: DroneState) -> float:
        if drone.relative_alt_valid:
            return max(0.0, float(drone.relative_altitude))
        if self._origin is not None and drone.local_position_valid:
            return max(0.0, -(float(drone.local_z) - float(self._origin.origin_z)))
        return max(0.0, float(drone.altitude))

    def _mission_position(self, drone: DroneState) -> tuple[float, float, float] | None:
        if self._origin is None or not drone.local_position_valid:
            return None
        return to_mission_position(drone, self._origin)

    def _transition_to(self, stage: RescueStage) -> None:
        if stage == self._stage:
            return
        self._previous_stage = self._stage
        self._stage = stage
        self._stage_started_at = None
        self._goal_reached_since = None

    def _detail(self, drone: DroneState | None = None) -> dict[str, object]:
        detail: dict[str, object] = {
            "drop_scan_index": self._drop_scan_index,
            "drop_estimate_count": len(self._drop_estimates),
            "drop_targets": [item.to_detail() for item in self._drop_targets],
            "drop_target_index": self._drop_target_index,
            "drop_count": self._drop_count,
            "drop_required_count": self.config.drop.required_payload_drops,
            "recce_scan_index": self._recce_scan_index,
            "recce_estimate_count": len(self._recce_estimates),
            "recce_targets": [item.to_detail() for item in self._recce_targets],
            "recce_target_index": self._recce_target_index,
            "recce_results": [item.to_dict() for item in self._recce_results],
            "recce_required_confirmed_count": self.config.recce.required_confirmed_count,
            "recce_report_path": self._recce_report_path,
            "payload_slots": [item.to_detail() for item in self.config.payload_slots],
            "route": {
                "home": {"x": self.config.route.home_x, "y": self.config.route.home_y},
                "drop_area_center": {"x": self.config.route.drop_area_x, "y": self.config.route.drop_area_y},
                "recce_area_center": {"x": self.config.route.recce_area_x, "y": self.config.route.recce_area_y},
            },
            "drop_survey_points": [
                {"name": item.name, "x": item.x, "y": item.y}
                for item in self.config.drop.survey_points
            ],
            "recce_survey_points": [
                {"name": item.name, "x": item.x, "y": item.y}
                for item in self.config.recce.survey_points
            ],
        }
        if self._origin is not None:
            detail["origin"] = {
                "local_x": self._origin.origin_x,
                "local_y": self._origin.origin_y,
                "local_z": self._origin.origin_z,
                "yaw_rad": self._origin.yaw_rad,
            }
            if drone is not None and drone.local_position_valid:
                x, y, z = to_mission_position(drone, self._origin)
                detail["mission_position"] = {"x": x, "y": y, "z": z}
        return detail


def build_rescue_config(settings: dict[str, Any] | None = None) -> RescueCompetitionMissionConfig:
    data = settings or {}
    return RescueCompetitionMissionConfig(
        initial_stage=_stage_value(str(data.get("initial_stage", RescueStage.PREPARE.value))),
        idle_mode=str(data.get("idle_mode", "IDLE")),
        align_mode=str(data.get("align_mode", "DOWNWARD_ALIGN_DESCEND")),
        auto_start=_strict_bool(data.get("auto_start", False), "auto_start"),
        takeoff_altitude_m=float(data.get("takeoff_altitude_m", 5.0)),
        takeoff_altitude_tolerance_m=float(data.get("takeoff_altitude_tolerance_m", 0.5)),
        land_complete_altitude_m=float(data.get("land_complete_altitude_m", 0.3)),
        local_position_frame=int(data.get("local_position_frame", 1)),
        xy_tolerance_m=float(data.get("xy_tolerance_m", 0.6)),
        z_tolerance_m=float(data.get("z_tolerance_m", 0.35)),
        max_goal_speed_mps=float(data.get("max_goal_speed_mps", 0.5)),
        route=_route_config(_section(data, "route")),
        drop=_drop_config(_section(data, "drop")),
        payload=_payload_config(_section(data, "payload")),
        payload_slots=_payload_slots(data.get("payload_slots", [])),
        recce=_recce_config(_section(data, "recce")),
        vision=_vision_config(_section(data, "vision")),
        align=_align_config(_section(data, "align")),
    )


def _route_config(data: dict[str, Any]) -> RouteConfig:
    home = _section(data, "home")
    drop = _section(data, "drop_area_center")
    recce = _section(data, "recce_area_center")
    return RouteConfig(
        home_x=float(home.get("x", 0.0)),
        home_y=float(home.get("y", 0.0)),
        drop_area_x=float(drop.get("x", 30.0)),
        drop_area_y=float(drop.get("y", 0.0)),
        recce_area_x=float(recce.get("x", 55.0)),
        recce_area_y=float(recce.get("y", 0.0)),
    )


def _stage_value(value: str | RescueStage) -> RescueStage:
    if isinstance(value, RescueStage):
        return value
    normalized = str(value).strip().upper()
    aliases = {
        "DONE": RescueStage.FINISH,
        "DROP_SCAN": RescueStage.SURVEY_DROP_POINTS,
        "RECON_SCAN": RescueStage.SURVEY_RECCE_POINTS,
        "RECCE_SCAN": RescueStage.SURVEY_RECCE_POINTS,
    }
    return aliases.get(normalized, RescueStage(normalized))


def _drop_config(data: dict[str, Any]) -> DropConfig:
    return DropConfig(
        required_payload_drops=int(data.get("required_payload_drops", 2)),
        survey_altitude_m=float(data.get("survey_altitude_m", 5.0)),
        transit_altitude_m=float(data.get("transit_altitude_m", 3.0)),
        release_altitude_m=float(data.get("release_altitude_m", 1.0)),
        survey_hold_s=float(data.get("survey_hold_s", 1.2)),
        target_count=int(data.get("target_count", 2)),
        survey_points=_survey_points(data.get("survey_points", _default_drop_points())),
    )


def _payload_config(data: dict[str, Any]) -> PayloadConfig:
    return PayloadConfig(
        release_wait_s=float(data.get("release_wait_s", 1.0)),
        return_hold_pwm_after_release=_strict_bool(
            data.get("return_hold_pwm_after_release", True),
            "payload.return_hold_pwm_after_release",
        ),
    )


def _recce_config(data: dict[str, Any]) -> RecceConfig:
    return RecceConfig(
        survey_altitude_m=float(data.get("survey_altitude_m", 5.0)),
        transit_altitude_m=float(data.get("transit_altitude_m", 3.0)),
        identify_altitude_m=float(data.get("identify_altitude_m", 2.0)),
        visual_descend_altitude_m=float(data.get("visual_descend_altitude_m", 1.0)),
        survey_hold_s=float(data.get("survey_hold_s", 1.2)),
        capture_hold_s=float(data.get("capture_hold_s", 1.5)),
        visit_max_count=int(data.get("visit_max_count", 5)),
        required_confirmed_count=int(data.get("required_confirmed_count", 3)),
        vote_min_count=int(data.get("vote_min_count", 3)),
        vote_min_confidence_sum=float(data.get("vote_min_confidence_sum", 1.2)),
        output_dir=str(data.get("output_dir", "runtime/logs/recce")),
        survey_points=_survey_points(data.get("survey_points", _default_recce_points())),
    )


def _vision_config(data: dict[str, Any]) -> VisionConfig:
    return VisionConfig(
        geometry=CameraGeometryConfig(
            fov_x_deg=float(data.get("fov_x_deg", 75.0)),
            fov_y_deg=float(data.get("fov_y_deg", 75.0)),
            image_x_sign=float(data.get("image_x_sign", 1.0)),
            image_y_sign=float(data.get("image_y_sign", 1.0)),
        ),
        cylinder_classes={item.strip().lower() for item in _string_list(data, "cylinder_classes", ["cylinder"])},
        hazard_classes={item.strip().lower() for item in _string_list(data, "hazard_classes", [])},
        min_cylinder_confidence=float(data.get("min_cylinder_confidence", 0.4)),
        min_hazard_confidence=float(data.get("min_hazard_confidence", 0.4)),
        cluster_radius_m=float(data.get("cluster_radius_m", 0.8)),
        edge_margin_norm=float(data.get("edge_margin_norm", 0.85)),
        lock_center_max_error=float(data.get("lock_center_max_error", 0.65)),
    )


def _align_config(data: dict[str, Any]) -> AlignMissionConfig:
    return AlignMissionConfig(
        max_ex_cam=float(data.get("max_ex_cam", 0.06)),
        max_ey_cam=float(data.get("max_ey_cam", 0.06)),
        hold_s=float(data.get("hold_s", 0.5)),
        lost_timeout_s=float(data.get("lost_timeout_s", 1.0)),
        min_altitude_m=float(data.get("min_altitude_m", 0.8)),
    )


def _payload_slots(value: Any) -> list[PayloadSlot]:
    items = value if isinstance(value, list) else []
    if not items:
        items = [
            {"id": 1, "servo_channel": 8, "hold_pwm": 1100, "release_pwm": 1900},
            {"id": 2, "servo_channel": 9, "hold_pwm": 1100, "release_pwm": 1900},
        ]
    slots: list[PayloadSlot] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("payload_slots entries must be mappings")
        slots.append(
            PayloadSlot(
                payload_id=int(item.get("id", item.get("payload_id", index + 1))),
                servo_channel=int(item.get("servo_channel", index + 8)),
                hold_pwm=int(item.get("hold_pwm", 1100)),
                release_pwm=int(item.get("release_pwm", 1900)),
                drop_center_x=float(item.get("drop_center_x", 0.0)),
                drop_center_y=float(item.get("drop_center_y", 0.0)),
            )
        )
    return slots


def _survey_points(value: Any) -> list[SurveyPoint]:
    if not isinstance(value, list):
        raise ValueError("survey_points must be a list")
    points: list[SurveyPoint] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("survey_points entries must be mappings")
        points.append(
            SurveyPoint(
                name=str(item.get("name", f"p{index + 1}")),
                x=float(item["x"]),
                y=float(item["y"]),
            )
        )
    return points


def _default_drop_points() -> list[dict[str, object]]:
    return [
        {"name": "drop_p1", "x": 28.0, "y": -1.2},
        {"name": "drop_p2", "x": 28.0, "y": 1.2},
        {"name": "drop_p3", "x": 32.0, "y": -1.2},
        {"name": "drop_p4", "x": 32.0, "y": 1.2},
    ]


def _default_recce_points() -> list[dict[str, object]]:
    return [
        {"name": "recce_p1", "x": 53.0, "y": -1.2},
        {"name": "recce_p2", "x": 53.0, "y": 1.2},
        {"name": "recce_p3", "x": 57.0, "y": -1.2},
        {"name": "recce_p4", "x": 57.0, "y": 1.2},
    ]


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _string_list(data: dict[str, Any], key: str, default: list[str]) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return list(value)


def _strict_bool(value: Any, path: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{path} must be a YAML bool (true/false), got {value!r}")
