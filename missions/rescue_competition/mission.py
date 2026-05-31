from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from missions.base import MissionAction, MissionContext, MissionOutput
from missions.common.navigation import (
    LocalMissionFrame,
    goal_target_tuple,
    hold_elapsed,
    local_goal_stable,
    mission_to_local_position,
    to_mission_position,
)
from missions.common.recce import RecceAccumulator, RecceConfig, RecceResultItem
from missions.common.recce_output import write_recce_results


class RescueStage(str, Enum):
    PREPARE = "PREPARE"
    TAKEOFF = "TAKEOFF"
    GOTO_DROPZONE = "GOTO_DROPZONE"
    FOLLOW_ROUTE_TO_DROP_ZONE = "GOTO_DROPZONE"
    DROP_SCAN = "DROP_SCAN"
    SEARCH_DROP_TARGETS = "DROP_SCAN"
    DROP_ALIGN = "DROP_ALIGN"
    ALIGN_AND_DROP = "DROP_ALIGN"
    DROP_DESCEND = "DROP_DESCEND"
    DROP_RELEASE = "DROP_RELEASE"
    DROP_ASCEND = "DROP_ASCEND"
    WAIT_PAYLOAD_RELEASE = "DROP_ASCEND"
    DROP_RESUME_SCAN = "DROP_RESUME_SCAN"
    GOTO_RECON = "GOTO_RECON"
    RESUME_ROUTE_TO_RECCE_ZONE = "GOTO_RECON"
    RECON_SCAN = "RECON_SCAN"
    SCAN_RECCE_AREA = "RECON_SCAN"
    RECON_ALIGN = "RECON_ALIGN"
    RECON_DESCEND = "RECON_DESCEND"
    RECON_REPORT = "RECON_REPORT"
    RETURN_HOME = "RETURN_HOME"
    FOLLOW_ROUTE_HOME = "RETURN_HOME"
    LAND = "LAND"
    FINISH = "FINISH"
    DONE = "FINISH"
    FAILSAFE = "FAILSAFE"
    ABORT = "FAILSAFE"


@dataclass(slots=True)
class RoutePoint:
    name: str
    x: float
    y: float
    z: float
    xy_tolerance_m: float = 1.0
    z_tolerance_m: float = 0.5
    max_speed_mps: float = 0.5


@dataclass(slots=True)
class MissionZone:
    name: str
    x: float
    y: float
    radius_m: float
    z: float | None = None


@dataclass(slots=True)
class PayloadRelease:
    type: str
    channel: int | None = None
    pwm: int | None = None
    hold_pwm: int | None = None
    relay_id: int | None = None
    state: bool | None = None


@dataclass(slots=True)
class PayloadSlot:
    payload_id: int
    label: str = ""
    release: PayloadRelease | None = None
    drop_center_x: float = 0.0
    drop_center_y: float = 0.0


@dataclass(slots=True)
class DroppedTarget:
    local_x: float
    local_y: float
    timestamp: float
    payload_id: int

    def to_detail(self) -> dict[str, object]:
        return {
            "local_x": self.local_x,
            "local_y": self.local_y,
            "timestamp": self.timestamp,
            "payload_id": self.payload_id,
        }


@dataclass(slots=True)
class ReportedTarget:
    local_x: float
    local_y: float
    label: str
    confidence: float
    timestamp: float

    def to_detail(self) -> dict[str, object]:
        return {
            "local_x": self.local_x,
            "local_y": self.local_y,
            "label": self.label,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class DropAlignConfig:
    max_ex_cam: float = 0.08
    max_ey_cam: float = 0.08
    min_target_size: float = 0.0
    require_target_locked: bool = True
    require_target_stable: bool = True
    hold_s: float = 0.8
    timeout_s: float = 15.0
    lost_timeout_s: float = 2.0


@dataclass(slots=True)
class DropMissionConfig:
    required_payload_drops: int = 2
    scan_direction: str = "left_to_right"
    scan_height_m: float = 5.0
    intermediate_height_m: float = 3.0
    final_height_m: float = 1.0
    ascend_height_m: float = 5.0
    scan_width_m: float = 5.0
    scan_speed_mps: float = 0.4
    scan_timeout_s: float = 45.0
    descend_hold_s: float = 0.3
    stable_hold_s: float = 3.0
    dropped_target_radius_m: float = 0.8
    resume_skip_m: float = 0.6


@dataclass(slots=True)
class ReconMissionConfig:
    scan_height_m: float = 5.0
    identify_height_m: float = 2.0
    scan_width_m: float = 5.0
    scan_speed_mps: float = 0.5
    scan_timeout_s: float = 40.0
    align_hold_s: float = 0.5
    descend_hold_s: float = 0.5
    reported_target_radius_m: float = 0.8


@dataclass(slots=True)
class PayloadReleaseTiming:
    delay_after_action_s: float = 1.0


@dataclass(slots=True)
class RecceMissionConfig:
    config: RecceConfig = field(default_factory=RecceConfig)
    scan_duration_s: float = 8.0
    output_dir: str = "runtime/logs/recce"
    output_json: bool = True
    output_csv: bool = True


@dataclass(slots=True)
class DropTargetSelection:
    track_id: int | None
    class_name: str
    confidence: float
    ex: float
    ey: float
    target_size: float
    selected_at: float

    def to_detail(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "ex": self.ex,
            "ey": self.ey,
            "target_size": self.target_size,
            "selected_at": self.selected_at,
        }


@dataclass(slots=True)
class RescueCompetitionMissionConfig:
    initial_stage: RescueStage = RescueStage.PREPARE
    idle_mode: str = "IDLE"
    auto_start: bool = False
    takeoff_altitude_m: float = 5.0
    takeoff_altitude_tolerance_m: float = 0.5
    local_position_frame: int = 1
    drop_route_end_name: str = "drop_center"
    recce_route_end_name: str = "recce_center"
    home_route_end_name: str = "home"
    route_hold_s: float = 0.0
    align_mode: str = "OVERHEAD_HOLD"
    dry_run_skip_vision: bool = False
    dry_run_skip_payload_release: bool = False
    search_drop_duration_s: float = 2.0
    align_drop_duration_s: float = 1.0
    drop_target_classes: list[str] = field(
        default_factory=lambda: ["drop_cylinder", "cylinder", "target"]
    )
    drop_target_min_confidence: float = 0.45
    drop_target_stable_frames: int = 5
    drop_target_max_center_error: float = 0.35
    align: DropAlignConfig = field(default_factory=DropAlignConfig)
    drop: DropMissionConfig = field(default_factory=DropMissionConfig)
    payload_release: PayloadReleaseTiming = field(default_factory=PayloadReleaseTiming)
    recce: RecceMissionConfig = field(default_factory=RecceMissionConfig)
    recon: ReconMissionConfig = field(default_factory=ReconMissionConfig)
    scan_duration_s: float = 3.0
    land_complete_altitude_m: float = 0.3
    route: list[RoutePoint] = field(default_factory=list)
    drop_zones: list[MissionZone] = field(default_factory=list)
    recce_zones: list[MissionZone] = field(default_factory=list)
    payloads: list[PayloadSlot] = field(default_factory=list)


@dataclass(slots=True)
class RescueCompetitionMission:
    config: RescueCompetitionMissionConfig = field(
        default_factory=RescueCompetitionMissionConfig
    )

    name: str = "rescue_competition"
    _stage: RescueStage = field(init=False)
    _origin: LocalMissionFrame | None = field(init=False, default=None)
    _route_index: int = field(init=False, default=0)
    _payload_index: int = field(init=False, default=0)
    _drop_count: int = field(init=False, default=0)
    _stage_started_at: float | None = field(init=False, default=None)
    _goal_reached_since: float | None = field(init=False, default=None)
    _drop_candidate_track_id: int | None = field(init=False, default=None)
    _drop_candidate_seen_frames: int = field(init=False, default=0)
    _drop_candidate_last_center: tuple[float, float] | None = field(init=False, default=None)
    _drop_candidate_class_name: str = field(init=False, default="")
    _selected_drop_target: DropTargetSelection | None = field(init=False, default=None)
    _align_ready_since: float | None = field(init=False, default=None)
    _target_lost_since: float | None = field(init=False, default=None)
    _payload_release_started_at: float | None = field(init=False, default=None)
    _recce_accumulator: RecceAccumulator = field(init=False)
    _recce_output_written: bool = field(init=False, default=False)
    _recce_results: list[RecceResultItem] = field(init=False, default_factory=list)
    _recce_output_paths: list[str] = field(init=False, default_factory=list)
    _start_requested: bool = field(init=False, default=False)
    _dropped_targets: list[DroppedTarget] = field(init=False, default_factory=list)
    _reported_targets: list[ReportedTarget] = field(init=False, default_factory=list)
    _scan_resume_y: float | None = field(init=False, default=None)
    _recon_candidate: Any | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._stage = self._stage_value(self.config.initial_stage)
        self._recce_accumulator = RecceAccumulator(self.config.recce.config)

    def reset(self) -> None:
        self._stage = self._stage_value(self.config.initial_stage)
        self._origin = None
        self._route_index = 0
        self._payload_index = 0
        self._drop_count = 0
        self._stage_started_at = None
        self._goal_reached_since = None
        self._reset_drop_candidate()
        self._selected_drop_target = None
        self._align_ready_since = None
        self._target_lost_since = None
        self._payload_release_started_at = None
        self._recce_accumulator.reset()
        self._recce_output_written = False
        self._recce_results = []
        self._recce_output_paths = []
        self._start_requested = False
        self._dropped_targets = []
        self._reported_targets = []
        self._scan_resume_y = None
        self._recon_candidate = None

    def start(self) -> None:
        self._start_requested = True

    def set_stage(self, stage: str) -> None:
        self._transition_to(self._stage_value(stage))
        self._start_requested = False

    def update(self, context: MissionContext) -> MissionOutput:
        previous = self._stage
        self._ensure_stage_started(context)
        actions: list[MissionAction] = []
        hold_reason = ""
        active_mode = self.config.idle_mode

        target_error_offset: dict[str, float] | None = None

        if self._stage == RescueStage.PREPARE:
            hold_reason = self._update_prepare(context)
        elif self._stage == RescueStage.TAKEOFF:
            actions.append(
                MissionAction(
                    "takeoff",
                    params={"altitude_m": self.config.takeoff_altitude_m},
                    key="rescue_takeoff",
                    once=True,
                    priority=2,
                )
            )
            if context.drone.relative_alt_valid and context.drone.relative_altitude >= (
                self.config.takeoff_altitude_m - self.config.takeoff_altitude_tolerance_m
            ):
                self._transition_to(RescueStage.GOTO_DROPZONE)
        elif self._stage == RescueStage.GOTO_DROPZONE:
            hold_reason = self._update_goto_dropzone(context, actions)
        elif self._stage == RescueStage.DROP_SCAN:
            hold_reason = self._update_drop_scan(context, actions)
        elif self._stage == RescueStage.DROP_ALIGN:
            active_mode = self.config.align_mode
            target_error_offset = self._current_payload_offset()
            hold_reason = self._update_drop_align(context, actions)
        elif self._stage == RescueStage.DROP_DESCEND:
            active_mode = self.config.align_mode
            target_error_offset = self._current_payload_offset()
            hold_reason = self._update_drop_descend(context, actions)
        elif self._stage == RescueStage.DROP_RELEASE:
            active_mode = self.config.align_mode
            target_error_offset = self._current_payload_offset()
            hold_reason = self._update_drop_release(context, actions)
        elif self._stage == RescueStage.DROP_ASCEND:
            hold_reason = self._update_drop_ascend(context, actions)
        elif self._stage == RescueStage.DROP_RESUME_SCAN:
            hold_reason = self._update_drop_resume_scan(context, actions)
        elif self._stage == RescueStage.GOTO_RECON:
            hold_reason = self._follow_route_until(
                context,
                actions,
                self.config.recce_route_end_name,
                RescueStage.RECON_SCAN,
                "enroute",
            )
        elif self._stage == RescueStage.RECON_SCAN:
            hold_reason = self._update_recon_scan(context, actions)
        elif self._stage == RescueStage.RECON_ALIGN:
            active_mode = self.config.align_mode
            hold_reason = self._update_recon_align(context, actions)
        elif self._stage == RescueStage.RECON_DESCEND:
            active_mode = self.config.align_mode
            hold_reason = self._update_recon_descend(context, actions)
        elif self._stage == RescueStage.RECON_REPORT:
            hold_reason = self._update_recon_report(context)
        elif self._stage == RescueStage.RETURN_HOME:
            hold_reason = self._follow_route_until(
                context,
                actions,
                self.config.home_route_end_name,
                RescueStage.LAND,
                "returning_home",
            )
        elif self._stage == RescueStage.LAND:
            actions.append(
                MissionAction(
                    "land",
                    key="rescue_land",
                    once=True,
                    priority=2,
                )
            )
            if context.drone.relative_alt_valid and context.drone.relative_altitude <= self.config.land_complete_altitude_m:
                self._transition_to(RescueStage.FINISH)

        return MissionOutput(
            active_mode=active_mode,
            actions=actions,
            stage=self._stage.value,
            previous_stage=previous.value if previous != self._stage else None,
            hold_reason=hold_reason,
            done=self._stage == RescueStage.FINISH,
            aborted=self._stage == RescueStage.FAILSAFE,
            detail={
                "mission": self.name,
                "timestamp": float(context.timestamp),
                "origin_captured": self._origin is not None,
                "route_index": self._route_index,
                "payload_index": self._payload_index,
                "drop_count": self._drop_count,
                "route_points": len(self.config.route),
                "drop_zones": len(self.config.drop_zones),
                "recce_zones": len(self.config.recce_zones),
                "payloads": len(self.config.payloads),
                "required_payload_drops": self.config.drop.required_payload_drops,
                "dropped_targets": [target.to_detail() for target in self._dropped_targets],
                "reported_targets": [target.to_detail() for target in self._reported_targets],
                "target_error_offset": target_error_offset,
                "selected_drop_target": (
                    None
                    if self._selected_drop_target is None
                    else self._selected_drop_target.to_detail()
                ),
                "recce_observation_count": self._recce_accumulator.observation_count,
                "recce_confirmed_count": self._recce_confirmed_count(),
                "recce_results": [item.to_dict() for item in self._recce_results],
                "recce_output_paths": list(self._recce_output_paths),
            },
        )

    @staticmethod
    def _stage_value(stage: RescueStage | str) -> RescueStage:
        if isinstance(stage, RescueStage):
            return stage
        legacy = {
            "FOLLOW_ROUTE_TO_DROP_ZONE": RescueStage.GOTO_DROPZONE,
            "SEARCH_DROP_TARGETS": RescueStage.DROP_SCAN,
            "ALIGN_AND_DROP": RescueStage.DROP_ALIGN,
            "WAIT_PAYLOAD_RELEASE": RescueStage.DROP_ASCEND,
            "RESUME_ROUTE_TO_RECCE_ZONE": RescueStage.GOTO_RECON,
            "SCAN_RECCE_AREA": RescueStage.RECON_SCAN,
            "FOLLOW_ROUTE_HOME": RescueStage.RETURN_HOME,
            "DONE": RescueStage.FINISH,
            "ABORT": RescueStage.FAILSAFE,
        }
        value = str(stage)
        return legacy[value] if value in legacy else RescueStage(value)

    def _update_prepare(self, context: MissionContext) -> str:
        if not context.drone.local_position_valid:
            return "local_position_not_ready"
        if self._origin is None:
            self._origin = LocalMissionFrame(
                origin_x=float(context.drone.local_x),
                origin_y=float(context.drone.local_y),
                origin_z=float(context.drone.local_z),
                yaw_rad=float(context.drone.yaw),
            )
        if self.config.auto_start or self._start_requested:
            self._transition_to(RescueStage.TAKEOFF)
            self._start_requested = False
        return ""

    def _update_goto_dropzone(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        return self._follow_route_until(
            context,
            actions,
            self.config.drop_route_end_name,
            RescueStage.DROP_SCAN,
            "enroute",
        )

    def _follow_route_until(
        self,
        context: MissionContext,
        actions: list[MissionAction],
        end_name: str,
        next_stage: RescueStage,
        progress_reason: str,
    ) -> str:
        if not self.config.route:
            self._transition_to(next_stage)
            return "route_empty"
        end_index = self._route_index_for_name(end_name)
        if end_index is None:
            self._transition_to(RescueStage.FAILSAFE)
            return "route_invalid"
        if self._origin is None:
            if not context.drone.local_position_valid:
                return "local_position_not_ready"
            self._origin = LocalMissionFrame(
                origin_x=float(context.drone.local_x),
                origin_y=float(context.drone.local_y),
                origin_z=float(context.drone.local_z),
                yaw_rad=float(context.drone.yaw),
            )
        if self._route_index > end_index:
            self._transition_to(next_stage)
            return f"route_end_reached:{end_name}"

        current_point = self.config.route[min(self._route_index, end_index)]
        current = to_mission_position(context.drone, self._origin)
        target = goal_target_tuple(current_point)
        local_target = mission_to_local_position(target, self._origin)
        actions.append(
            MissionAction(
                "local_position",
                params={
                    "x": local_target[0],
                    "y": local_target[1],
                    "z": local_target[2],
                    "frame": self.config.local_position_frame,
                },
                key=f"rescue_route_{self._route_index}_{current_point.name}",
                once=False,
                priority=4,
            )
        )
        if local_goal_stable(
            context.drone,
            current,
            target,
            current_point.xy_tolerance_m,
            current_point.z_tolerance_m,
            current_point.max_speed_mps,
        ):
            if self._goal_reached_since is None:
                self._goal_reached_since = float(context.timestamp)
            if not hold_elapsed(
                context.timestamp,
                self._goal_reached_since,
                self.config.route_hold_s,
            ):
                return f"arrived:{current_point.name}"
            arrived_name = current_point.name
            self._route_index += 1
            self._goal_reached_since = None
            if arrived_name == end_name or self._route_index > end_index:
                self._transition_to(next_stage)
                return f"route_end_reached:{end_name}"
            return f"arrived:{arrived_name}"

        self._goal_reached_since = None
        return f"{progress_reason}:{current_point.name}"

    def _update_drop_scan(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        actions.append(self._set_mode_action("GUIDED", "drop_scan_guided"))
        if self._drop_count >= self.config.drop.required_payload_drops:
            self._transition_to(RescueStage.GOTO_RECON)
            return "required_payload_drops_complete"

        candidate = None
        if not self.config.dry_run_skip_vision:
            candidate = self._update_drop_candidate(context)
        if candidate is not None:
            self._select_drop_target(candidate, context, actions)
            self._transition_to(RescueStage.DROP_ALIGN)
            return "drop_target_acquired"
        if self.config.dry_run_skip_vision and hold_elapsed(
            context.timestamp,
            self._stage_started_at,
            self.config.search_drop_duration_s,
        ):
            self._transition_to(RescueStage.DROP_ALIGN)
            return "dry_run_drop_target_skip"

        self._append_local_position_action(actions, self._drop_scan_target(), "drop_scan_sweep")
        if hold_elapsed(context.timestamp, self._stage_started_at, self.config.drop.scan_timeout_s):
            self._transition_to(RescueStage.FAILSAFE)
            return "drop_scan_timeout"
        return "drop_scanning"

    def _update_drop_align(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        actions.append(self._set_mode_action("GUIDED", "drop_align_guided"))
        if self.config.dry_run_skip_vision:
            if hold_elapsed(context.timestamp, self._stage_started_at, self.config.align_drop_duration_s):
                self._transition_to(RescueStage.DROP_DESCEND)
                return "drop_align_dry_run_complete"
            return "aligning_drop_dry_run"
        lost_reason = self._align_lost_reason(context)
        if lost_reason:
            self._align_ready_since = None
            if self._target_lost_since is None:
                self._target_lost_since = float(context.timestamp)
            if hold_elapsed(
                context.timestamp,
                self._target_lost_since,
                self.config.align.lost_timeout_s,
            ):
                self._return_to_drop_search(actions)
                return "drop_target_lost"
            return lost_reason
        self._target_lost_since = None

        if hold_elapsed(context.timestamp, self._stage_started_at, self.config.align.timeout_s):
            self._return_to_drop_search(actions)
            return "drop_align_timeout"
        if not self._drop_alignment_ready(context, self._current_payload_offset()):
            self._align_ready_since = None
            return "aligning_drop"
        if self._align_ready_since is None:
            self._align_ready_since = float(context.timestamp)
        if not hold_elapsed(context.timestamp, self._align_ready_since, self.config.align.hold_s):
            return "aligning_drop"
        self._transition_to(RescueStage.DROP_DESCEND)
        return "drop_align_complete"

    def _update_drop_descend(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        actions.append(self._set_mode_action("GUIDED", "drop_descend_guided"))
        if self.config.dry_run_skip_payload_release and not context.actions_enabled:
            if hold_elapsed(context.timestamp, self._stage_started_at, self.config.align_drop_duration_s):
                self._transition_to(RescueStage.DROP_RELEASE)
                return "drop_descend_dry_run_complete"
            return "drop_descending_dry_run"
        target = self._current_xy_target(context, -abs(self.config.drop.final_height_m))
        self._append_local_position_action(actions, target, "drop_descend_final")
        if self._mission_goal_stable(context, target, xy_tolerance_m=0.45, z_tolerance_m=0.25):
            if self._align_ready_since is None:
                self._align_ready_since = float(context.timestamp)
            if hold_elapsed(context.timestamp, self._align_ready_since, self.config.drop.stable_hold_s):
                self._transition_to(RescueStage.DROP_RELEASE)
                return "drop_descend_complete"
            return "drop_final_hold"
        self._align_ready_since = None
        return "drop_descending"

    def _update_drop_release(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        if self.config.dry_run_skip_payload_release and not context.actions_enabled:
            self._record_drop(context)
            self._payload_release_started_at = float(context.timestamp)
            self._transition_to(RescueStage.DROP_ASCEND)
            return "payload_release_simulated"
        if self._payload_index >= len(self.config.payloads):
            self._transition_to(RescueStage.FAILSAFE)
            return "no_payload_configured"
        payload = self.config.payloads[self._payload_index]
        action = self._release_action(payload)
        if action is None:
            self._transition_to(RescueStage.FAILSAFE)
            return "payload_release_not_configured"
        if not context.actions_enabled:
            return "payload_release_actions_disabled"
        actions.append(action)
        self._record_drop(context)
        self._payload_release_started_at = float(context.timestamp)
        self._transition_to(RescueStage.DROP_ASCEND)
        return "payload_release_requested"

    def _update_drop_ascend(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        if self._payload_release_started_at is None:
            self._payload_release_started_at = float(context.timestamp)
        if not hold_elapsed(
            context.timestamp,
            self._payload_release_started_at,
            self.config.payload_release.delay_after_action_s,
        ):
            return "waiting_payload_release"
        payload = self._last_payload()
        hold_action = self._hold_action(payload) if payload is not None else None
        if hold_action is not None and context.actions_enabled:
            actions.append(hold_action)
        target = self._current_xy_target(context, -abs(self.config.drop.ascend_height_m))
        self._append_local_position_action(actions, target, "drop_ascend_scan_height")
        if self._mission_goal_stable(context, target, xy_tolerance_m=0.7, z_tolerance_m=0.4):
            actions.append(
                MissionAction(
                    "yolo_unlock_target",
                    key=f"unlock_drop_target_after_release_{self._drop_count}",
                    once=True,
                    priority=5,
                )
            )
            self._clear_drop_target_selection()
            if self._drop_count >= self.config.drop.required_payload_drops:
                self._transition_to(RescueStage.GOTO_RECON)
                return "payload_drops_complete"
            self._transition_to(RescueStage.DROP_RESUME_SCAN)
            return "drop_ascend_complete"
        return "drop_ascending"

    def _update_drop_resume_scan(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        actions.append(self._set_mode_action("GUIDED", "drop_resume_scan_guided"))
        target = self._drop_resume_target(context)
        self._append_local_position_action(actions, target, "drop_resume_scan")
        if self._mission_goal_stable(context, target, xy_tolerance_m=0.7, z_tolerance_m=0.4):
            self._transition_to(RescueStage.DROP_SCAN)
            return "drop_scan_resumed"
        return "drop_resuming_scan"

    def _update_recon_scan(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        actions.append(self._set_mode_action("GUIDED", "recon_scan_guided"))
        if context.scene is not None and context.scene.valid:
            self._recce_accumulator.update(context.scene, context.timestamp)
        candidate = None if self._near_reported_target(context) else self._select_recon_candidate(context.scene)
        if candidate is not None:
            self._recon_candidate = candidate
            self._transition_to(RescueStage.RECON_ALIGN)
            return "recon_target_acquired"
        self._append_local_position_action(actions, self._recon_scan_target(), "recon_scan_sweep")
        elapsed = 0.0 if self._stage_started_at is None else float(context.timestamp) - self._stage_started_at
        if elapsed >= min(self.config.recce.scan_duration_s, self.config.recon.scan_timeout_s):
            self._finalize_recce_results(context.timestamp)
            self._transition_to(RescueStage.RETURN_HOME)
            return "recon_scan_complete"
        return "recon_scanning"

    def _update_recon_align(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        actions.append(self._set_mode_action("GUIDED", "recon_align_guided"))
        if self._align_lost_reason(context):
            self._transition_to(RescueStage.RECON_SCAN)
            return "recon_target_lost"
        if self._align_ready_since is None:
            self._align_ready_since = float(context.timestamp)
        if hold_elapsed(context.timestamp, self._align_ready_since, self.config.recon.align_hold_s):
            self._transition_to(RescueStage.RECON_DESCEND)
            return "recon_align_complete"
        return "recon_aligning"

    def _update_recon_descend(
        self,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> str:
        actions.append(self._set_mode_action("GUIDED", "recon_descend_guided"))
        target = self._current_xy_target(context, -abs(self.config.recon.identify_height_m))
        self._append_local_position_action(actions, target, "recon_descend_identify")
        if self._mission_goal_stable(context, target, xy_tolerance_m=0.6, z_tolerance_m=0.35):
            if self._align_ready_since is None:
                self._align_ready_since = float(context.timestamp)
            if hold_elapsed(context.timestamp, self._align_ready_since, self.config.recon.descend_hold_s):
                self._transition_to(RescueStage.RECON_REPORT)
                return "recon_descend_complete"
        return "recon_descending"

    def _update_recon_report(self, context: MissionContext) -> str:
        if context.scene is not None and context.scene.valid:
            self._recce_accumulator.update(context.scene, context.timestamp)
        candidate = self._recon_candidate
        if candidate is not None and self._origin is not None and context.drone.local_position_valid:
            pos = to_mission_position(context.drone, self._origin)
            self._reported_targets.append(
                ReportedTarget(
                    local_x=float(pos[0]),
                    local_y=float(pos[1]),
                    label=str(getattr(candidate, "class_name", "")),
                    confidence=float(getattr(candidate, "confidence", 0.0)),
                    timestamp=float(context.timestamp),
                )
            )
        self._recon_candidate = None
        self._transition_to(RescueStage.RECON_SCAN)
        return "recon_target_reported"

    def _update_scan_recce_area(self, context: MissionContext) -> str:
        if context.scene is not None and context.scene.valid:
            self._recce_accumulator.update(context.scene, context.timestamp)
        elapsed = 0.0 if self._stage_started_at is None else float(context.timestamp) - self._stage_started_at
        if elapsed >= self.config.recce.scan_duration_s:
            self._finalize_recce_results(context.timestamp)
            self._transition_to(RescueStage.RETURN_HOME)
            return ""
        return "scanning_recce_area"

    def _finalize_recce_results(self, timestamp: float) -> None:
        self._recce_results = self._recce_accumulator.results()
        if self._recce_output_written:
            return
        paths = write_recce_results(
            output_dir=self.config.recce.output_dir,
            mission=self.name,
            timestamp=timestamp,
            items=self._recce_results,
            write_json=self.config.recce.output_json,
            write_csv=self.config.recce.output_csv,
        )
        self._recce_output_paths = [str(path) for path in paths]
        self._recce_output_written = True

    def _recce_confirmed_count(self) -> int:
        return sum(1 for item in self._recce_results if item.status == "confirmed")

    def _ensure_stage_started(self, context: MissionContext) -> None:
        if self._stage_started_at is None:
            self._stage_started_at = float(context.timestamp)

    def _transition_to(self, stage: RescueStage) -> None:
        if self._stage == stage:
            return
        self._stage = stage
        self._stage_started_at = None
        self._goal_reached_since = None
        self._align_ready_since = None
        self._target_lost_since = None

    def _route_index_for_name(self, name: str) -> int | None:
        for index, point in enumerate(self.config.route):
            if point.name == name:
                return index
        return None

    def _append_local_position_action(
        self,
        actions: list[MissionAction],
        target: tuple[float, float, float],
        key: str,
    ) -> None:
        if self._origin is None:
            return
        local_target = mission_to_local_position(target, self._origin)
        actions.append(
            MissionAction(
                "local_position",
                params={
                    "x": local_target[0],
                    "y": local_target[1],
                    "z": local_target[2],
                    "frame": self.config.local_position_frame,
                },
                key=key,
                once=False,
                priority=4,
            )
        )

    @staticmethod
    def _set_mode_action(mode: str, key: str) -> MissionAction:
        return MissionAction(
            "set_mode",
            params={"mode": mode},
            key=key,
            once=True,
            priority=2,
        )

    def _drop_scan_target(self) -> tuple[float, float, float]:
        center = self._route_point_for_name(self.config.drop_route_end_name)
        y = (
            center.y + self.config.drop.scan_width_m / 2.0
            if self.config.drop.scan_direction == "left_to_right"
            else center.y - self.config.drop.scan_width_m / 2.0
        )
        if self._scan_resume_y is not None:
            y = (
                max(y, self._scan_resume_y)
                if self.config.drop.scan_direction == "left_to_right"
                else min(y, self._scan_resume_y)
            )
        return (center.x, y, -abs(self.config.drop.scan_height_m))

    def _drop_resume_target(self, context: MissionContext) -> tuple[float, float, float]:
        current = self._current_mission_position(context)
        step = self.config.drop.resume_skip_m
        if self.config.drop.scan_direction == "right_to_left":
            step = -step
        y = current[1] + step
        self._scan_resume_y = y
        center = self._route_point_for_name(self.config.drop_route_end_name)
        return (center.x, y, -abs(self.config.drop.scan_height_m))

    def _recon_scan_target(self) -> tuple[float, float, float]:
        center = self._route_point_for_name(self.config.recce_route_end_name)
        y = center.y + self.config.recon.scan_width_m / 2.0
        return (center.x, y, -abs(self.config.recon.scan_height_m))

    def _route_point_for_name(self, name: str) -> RoutePoint:
        for point in self.config.route:
            if point.name == name:
                return point
        return RoutePoint(name=name, x=0.0, y=0.0, z=-abs(self.config.drop.scan_height_m))

    def _current_xy_target(self, context: MissionContext, z: float) -> tuple[float, float, float]:
        current = self._current_mission_position(context)
        return (current[0], current[1], z)

    def _current_mission_position(self, context: MissionContext) -> tuple[float, float, float]:
        if self._origin is not None and context.drone.local_position_valid:
            return to_mission_position(context.drone, self._origin)
        return (0.0, 0.0, 0.0)

    def _mission_goal_stable(
        self,
        context: MissionContext,
        target: tuple[float, float, float],
        *,
        xy_tolerance_m: float,
        z_tolerance_m: float,
    ) -> bool:
        if self._origin is None:
            return False
        current = to_mission_position(context.drone, self._origin)
        return local_goal_stable(
            context.drone,
            current,
            target,
            xy_tolerance_m,
            z_tolerance_m,
            max_speed_mps=0.6,
        )

    def _current_payload_offset(self) -> dict[str, float]:
        payload = self._current_payload()
        if payload is None:
            return {"ex_cam": 0.0, "ey_cam": 0.0}
        return {"ex_cam": payload.drop_center_x, "ey_cam": payload.drop_center_y}

    def _current_payload(self) -> PayloadSlot | None:
        if 0 <= self._payload_index < len(self.config.payloads):
            return self.config.payloads[self._payload_index]
        return None

    def _last_payload(self) -> PayloadSlot | None:
        index = self._payload_index - 1
        if 0 <= index < len(self.config.payloads):
            return self.config.payloads[index]
        return None

    def _record_drop(self, context: MissionContext) -> None:
        payload = self._current_payload()
        payload_id = self._payload_index + 1 if payload is None else payload.payload_id
        pos = self._current_mission_position(context)
        self._dropped_targets.append(
            DroppedTarget(
                local_x=float(pos[0]),
                local_y=float(pos[1]),
                timestamp=float(context.timestamp),
                payload_id=payload_id,
            )
        )
        self._drop_count += 1
        if self._payload_index < len(self.config.payloads):
            self._payload_index += 1

    def _select_drop_target(
        self,
        candidate,
        context: MissionContext,
        actions: list[MissionAction],
    ) -> None:
        self._selected_drop_target = DropTargetSelection(
            track_id=candidate.track_id,
            class_name=str(candidate.class_name),
            confidence=float(candidate.confidence),
            ex=float(getattr(candidate, "ex", 0.0)),
            ey=float(getattr(candidate, "ey", 0.0)),
            target_size=float(getattr(candidate, "target_size", 0.0)),
            selected_at=float(context.timestamp),
        )
        if candidate.track_id is not None:
            actions.append(
                MissionAction(
                    "yolo_lock_target",
                    params={"track_id": int(candidate.track_id)},
                    key=f"lock_drop_target_{int(candidate.track_id)}",
                    once=True,
                    priority=5,
                )
            )

    def _clear_drop_target_selection(self) -> None:
        self._selected_drop_target = None
        self._reset_drop_candidate()
        self._payload_release_started_at = None

    def _return_to_drop_search(self, actions: list[MissionAction]) -> None:
        actions.append(
            MissionAction(
                "yolo_unlock_target",
                key="unlock_drop_target_for_search",
                once=True,
                priority=5,
            )
        )
        self._clear_drop_target_selection()
        self._transition_to(RescueStage.DROP_SCAN)

    def _align_lost_reason(self, context: MissionContext) -> str:
        if not context.health.vision_fresh:
            return "drop_target_vision_stale"
        if not context.inputs.target_valid:
            return "drop_target_not_ready"
        return ""

    def _drop_alignment_ready(
        self,
        context: MissionContext,
        offset: dict[str, float] | None = None,
    ) -> bool:
        inputs = context.inputs
        config = self.config.align
        offset = offset or {"ex_cam": 0.0, "ey_cam": 0.0}
        if not context.health.vision_fresh or not inputs.target_valid:
            return False
        if config.require_target_locked and not inputs.target_locked:
            return False
        if config.require_target_stable and not inputs.target_stable:
            return False
        if abs(float(inputs.ex_cam) - float(offset.get("ex_cam", 0.0))) > config.max_ex_cam:
            return False
        if abs(float(inputs.ey_cam) - float(offset.get("ey_cam", 0.0))) > config.max_ey_cam:
            return False
        if float(inputs.target_size) < config.min_target_size:
            return False
        return True

    def _update_drop_candidate(self, context: MissionContext):
        candidate = self._select_drop_candidate(context.scene, context)
        if candidate is None:
            self._reset_drop_candidate()
            return None
        if self._same_drop_candidate(candidate):
            self._drop_candidate_seen_frames += 1
        else:
            self._drop_candidate_track_id = candidate.track_id
            self._drop_candidate_seen_frames = 1
            self._drop_candidate_class_name = str(candidate.class_name).lower()
        self._drop_candidate_last_center = (float(candidate.cx), float(candidate.cy))
        if self._drop_candidate_seen_frames >= max(1, int(self.config.drop_target_stable_frames)):
            return candidate
        return None

    def _select_drop_candidate(self, scene, context: MissionContext | None = None):
        if scene is None or not getattr(scene, "valid", False):
            return None
        if context is not None and self._near_dropped_target(context):
            return None
        classes = {name.strip().lower() for name in self.config.drop_target_classes if name.strip()}
        candidates = []
        for detection in getattr(scene, "detections", []):
            class_name = str(getattr(detection, "class_name", "")).lower()
            if classes and class_name not in classes:
                continue
            if float(getattr(detection, "confidence", 0.0)) < self.config.drop_target_min_confidence:
                continue
            center_error = self._center_error(detection)
            if center_error > self.config.drop_target_max_center_error:
                continue
            candidates.append((center_error, detection))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])[1]

    def _near_dropped_target(self, context: MissionContext) -> bool:
        if not self._dropped_targets:
            return False
        pos = self._current_mission_position(context)
        radius = self.config.drop.dropped_target_radius_m
        radius_sq = radius * radius
        for target in self._dropped_targets:
            dx = float(pos[0]) - target.local_x
            dy = float(pos[1]) - target.local_y
            if (dx * dx + dy * dy) <= radius_sq:
                return True
        return False

    def _near_reported_target(self, context: MissionContext) -> bool:
        if not self._reported_targets:
            return False
        pos = self._current_mission_position(context)
        radius = self.config.recon.reported_target_radius_m
        radius_sq = radius * radius
        for target in self._reported_targets:
            dx = float(pos[0]) - target.local_x
            dy = float(pos[1]) - target.local_y
            if (dx * dx + dy * dy) <= radius_sq:
                return True
        return False

    def _select_recon_candidate(self, scene):
        if scene is None or not getattr(scene, "valid", False):
            return None
        classes = {name.strip().lower() for name in self.config.recce.config.hazard_classes}
        candidates = []
        for detection in getattr(scene, "detections", []):
            class_name = str(getattr(detection, "class_name", "")).lower()
            if classes and class_name not in classes:
                continue
            if float(getattr(detection, "confidence", 0.0)) < self.config.recce.config.min_hazard_confidence:
                continue
            candidates.append((float(getattr(detection, "confidence", 0.0)), detection))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _same_drop_candidate(self, candidate) -> bool:
        if candidate.track_id is not None and self._drop_candidate_track_id is not None:
            return int(candidate.track_id) == int(self._drop_candidate_track_id)
        if self._drop_candidate_last_center is None:
            return False
        if str(candidate.class_name).lower() != self._drop_candidate_class_name:
            return False
        dx = float(candidate.cx) - self._drop_candidate_last_center[0]
        dy = float(candidate.cy) - self._drop_candidate_last_center[1]
        return (dx * dx + dy * dy) <= 64.0

    @staticmethod
    def _center_error(detection) -> float:
        ex = float(getattr(detection, "ex", 0.0))
        ey = float(getattr(detection, "ey", 0.0))
        return (ex * ex + ey * ey) ** 0.5

    def _reset_drop_candidate(self) -> None:
        self._drop_candidate_track_id = None
        self._drop_candidate_seen_frames = 0
        self._drop_candidate_last_center = None
        self._drop_candidate_class_name = ""

    @staticmethod
    def _target_ready(context: MissionContext) -> bool:
        return bool(
            context.health.vision_fresh
            and context.inputs.target_valid
            and context.inputs.target_locked
            and context.inputs.target_stable
        )

    @staticmethod
    def _release_action(payload: PayloadSlot) -> MissionAction | None:
        release = payload.release
        if release is None:
            return None
        release_type = str(release.type).strip().lower()
        key = f"rescue_release_payload_{payload.payload_id}"
        if release_type == "servo":
            if release.channel is None or release.pwm is None:
                return None
            return MissionAction(
                "set_servo",
                params={"channel": int(release.channel), "pwm": int(release.pwm)},
                key=key,
                once=True,
                priority=3,
            )
        if release_type == "relay":
            if release.relay_id is None or release.state is None:
                return None
            return MissionAction(
                "set_relay",
                params={"relay_id": int(release.relay_id), "state": bool(release.state)},
                key=key,
                once=True,
                priority=3,
            )
        return None

    @staticmethod
    def _hold_action(payload: PayloadSlot) -> MissionAction | None:
        release = payload.release
        if release is None:
            return None
        if str(release.type).strip().lower() != "servo":
            return None
        if release.channel is None or release.hold_pwm is None:
            return None
        return MissionAction(
            "set_servo",
            params={"channel": int(release.channel), "pwm": int(release.hold_pwm)},
            key=f"rescue_hold_payload_{payload.payload_id}",
            once=True,
            priority=3,
        )


def build_rescue_config(settings: dict[str, Any]) -> RescueCompetitionMissionConfig:
    config = RescueCompetitionMissionConfig(
        initial_stage=RescueCompetitionMission._stage_value(
            str(settings.get("initial_stage", RescueStage.PREPARE.value))
        ),
        idle_mode=str(settings.get("idle_mode", "IDLE")),
        auto_start=_strict_bool(settings.get("auto_start", False)),
        takeoff_altitude_m=float(settings.get("takeoff_altitude_m", 5.0)),
        takeoff_altitude_tolerance_m=float(settings.get("takeoff_altitude_tolerance_m", 0.5)),
        local_position_frame=int(settings.get("local_position_frame", 1)),
        drop_route_end_name=str(settings.get("drop_route_end_name", "drop_center")),
        recce_route_end_name=str(settings.get("recce_route_end_name", "recce_center")),
        home_route_end_name=str(settings.get("home_route_end_name", "home")),
        route_hold_s=float(settings.get("route_hold_s", 0.0)),
        align_mode=str(settings.get("align_mode", "OVERHEAD_HOLD")),
        dry_run_skip_vision=_strict_bool(settings.get("dry_run_skip_vision", False)),
        dry_run_skip_payload_release=_strict_bool(settings.get("dry_run_skip_payload_release", False)),
        search_drop_duration_s=float(settings.get("search_drop_duration_s", 2.0)),
        align_drop_duration_s=float(settings.get("align_drop_duration_s", 1.0)),
        drop_target_classes=_string_list(
            settings,
            "drop_target_classes",
            ["drop_cylinder", "cylinder", "target"],
        ),
        drop_target_min_confidence=float(settings.get("drop_target_min_confidence", 0.45)),
        drop_target_stable_frames=int(settings.get("drop_target_stable_frames", 5)),
        drop_target_max_center_error=float(settings.get("drop_target_max_center_error", 0.35)),
        align=_align_config(settings.get("align", {})),
        drop=_drop_config(settings.get("drop", settings)),
        payload_release=_payload_release_timing(settings.get("payload_release", {})),
        recce=_recce_mission_config(settings.get("recce", {}), settings.get("scan_duration_s", None)),
        recon=_recon_config(settings.get("recon", {})),
        scan_duration_s=float(settings.get("scan_duration_s", 3.0)),
        land_complete_altitude_m=float(settings.get("land_complete_altitude_m", 0.3)),
        route=[_route_point(item, index) for index, item in enumerate(_list(settings, "route"))],
        drop_zones=[_mission_zone(item, index, "drop_zone") for index, item in enumerate(_list(settings, "drop_zones"))],
        recce_zones=[_mission_zone(item, index, "recce_zone") for index, item in enumerate(_list(settings, "recce_zones"))],
        payloads=[_payload_slot(item, index) for index, item in enumerate(_payload_items(settings))],
    )
    _validate_route_end_names(config)
    return config


def _list(settings: dict[str, Any], key: str) -> list[Any]:
    value = settings.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"rescue_competition.{key} must be a list")
    return value


def _payload_items(settings: dict[str, Any]) -> list[Any]:
    if "payload_slots" in settings:
        return _list(settings, "payload_slots")
    return _list(settings, "payloads")


def _string_list(
    settings: dict[str, Any],
    key: str,
    default: list[str],
) -> list[str]:
    value = settings.get(key, default)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"rescue_competition.{key} must be a list")
    return [str(item) for item in value]


def _route_point(item: Any, index: int) -> RoutePoint:
    data = _mapping(item, "route", index)
    return RoutePoint(
        name=str(data.get("name", f"route_{index + 1}")),
        x=float(data["x"]),
        y=float(data["y"]),
        z=float(data["z"]),
        xy_tolerance_m=float(data.get("xy_tolerance_m", data.get("radius_m", 1.0))),
        z_tolerance_m=float(data.get("z_tolerance_m", 0.5)),
        max_speed_mps=float(data.get("max_speed_mps", 0.5)),
    )


def _mission_zone(item: Any, index: int, prefix: str) -> MissionZone:
    data = _mapping(item, prefix, index)
    return MissionZone(
        name=str(data.get("name", f"{prefix}_{index + 1}")),
        x=float(data["x"]),
        y=float(data["y"]),
        radius_m=float(data["radius_m"]),
        z=None if data.get("z") is None else float(data["z"]),
    )


def _payload_slot(item: Any, index: int) -> PayloadSlot:
    data = _mapping(item, "payloads", index)
    release = data.get("release")
    if release is None and data.get("servo_channel") is not None:
        release = {
            "type": "servo",
            "channel": data.get("servo_channel"),
            "pwm": data.get("release_pwm"),
            "hold_pwm": data.get("hold_pwm"),
        }
    return PayloadSlot(
        payload_id=int(data.get("payload_id", data.get("id", index + 1))),
        label=str(data.get("label", "")),
        release=_payload_release(release, index),
        drop_center_x=float(data.get("drop_center_x", 0.0)),
        drop_center_y=float(data.get("drop_center_y", 0.0)),
    )


def _payload_release(item: Any, index: int) -> PayloadRelease | None:
    if item is None:
        return None
    data = _mapping(item, "payloads.release", index)
    release_type = str(data.get("type", "")).strip().lower()
    if release_type == "servo":
        return PayloadRelease(
            type=release_type,
            channel=int(data["channel"]) if data.get("channel") is not None else None,
            pwm=int(data["pwm"]) if data.get("pwm") is not None else None,
            hold_pwm=int(data["hold_pwm"]) if data.get("hold_pwm") is not None else None,
        )
    if release_type == "relay":
        return PayloadRelease(
            type=release_type,
            relay_id=int(data["relay_id"]) if data.get("relay_id") is not None else None,
            state=_strict_bool(data["state"]) if data.get("state") is not None else None,
        )
    raise ValueError(f"rescue_competition.payloads[{index}].release.type must be servo or relay")


def _align_config(item: Any) -> DropAlignConfig:
    if item is None:
        item = {}
    if not isinstance(item, dict):
        raise ValueError("rescue_competition.align must be a mapping")
    return DropAlignConfig(
        max_ex_cam=float(item.get("max_ex_cam", 0.08)),
        max_ey_cam=float(item.get("max_ey_cam", 0.08)),
        min_target_size=float(item.get("min_target_size", 0.0)),
        require_target_locked=_strict_bool(item.get("require_target_locked", True)),
        require_target_stable=_strict_bool(item.get("require_target_stable", True)),
        hold_s=float(item.get("hold_s", 0.8)),
        timeout_s=float(item.get("timeout_s", 15.0)),
        lost_timeout_s=float(item.get("lost_timeout_s", 2.0)),
    )


def _drop_config(item: Any) -> DropMissionConfig:
    if item is None:
        item = {}
    if not isinstance(item, dict):
        raise ValueError("rescue_competition.drop must be a mapping")
    direction = str(item.get("scan_direction", "left_to_right")).strip().lower()
    if direction not in {"left_to_right", "right_to_left"}:
        raise ValueError("rescue_competition.drop.scan_direction must be left_to_right or right_to_left")
    return DropMissionConfig(
        required_payload_drops=int(item.get("required_payload_drops", 2)),
        scan_direction=direction,
        scan_height_m=float(item.get("drop_scan_height_m", item.get("scan_height_m", 5.0))),
        intermediate_height_m=float(
            item.get("drop_intermediate_height_m", item.get("intermediate_height_m", 3.0))
        ),
        final_height_m=float(item.get("drop_final_height_m", item.get("final_height_m", 1.0))),
        ascend_height_m=float(item.get("drop_ascend_height_m", item.get("ascend_height_m", 5.0))),
        scan_width_m=float(item.get("drop_scan_width_m", item.get("scan_width_m", 5.0))),
        scan_speed_mps=float(item.get("drop_scan_speed_mps", item.get("scan_speed_mps", 0.4))),
        scan_timeout_s=float(item.get("drop_scan_timeout_s", item.get("scan_timeout_s", 45.0))),
        descend_hold_s=float(item.get("drop_descend_hold_s", item.get("descend_hold_s", 0.3))),
        stable_hold_s=float(item.get("drop_stable_hold_s", item.get("stable_hold_s", 3.0))),
        dropped_target_radius_m=float(
            item.get("dropped_target_radius_m", item.get("target_blacklist_radius_m", 0.8))
        ),
        resume_skip_m=float(item.get("drop_resume_skip_m", item.get("resume_skip_m", 0.6))),
    )


def _recon_config(item: Any) -> ReconMissionConfig:
    if item is None:
        item = {}
    if not isinstance(item, dict):
        raise ValueError("rescue_competition.recon must be a mapping")
    return ReconMissionConfig(
        scan_height_m=float(item.get("scan_height_m", 5.0)),
        identify_height_m=float(item.get("identify_height_m", 2.0)),
        scan_width_m=float(item.get("scan_width_m", 5.0)),
        scan_speed_mps=float(item.get("scan_speed_mps", 0.5)),
        scan_timeout_s=float(item.get("scan_timeout_s", 40.0)),
        align_hold_s=float(item.get("align_hold_s", 0.5)),
        descend_hold_s=float(item.get("descend_hold_s", 0.5)),
        reported_target_radius_m=float(item.get("reported_target_radius_m", 0.8)),
    )


def _payload_release_timing(item: Any) -> PayloadReleaseTiming:
    if item is None:
        item = {}
    if not isinstance(item, dict):
        raise ValueError("rescue_competition.payload_release must be a mapping")
    return PayloadReleaseTiming(
        delay_after_action_s=float(item.get("delay_after_action_s", 1.0)),
    )


def _recce_mission_config(item: Any, legacy_scan_duration: Any = None) -> RecceMissionConfig:
    if item is None:
        item = {}
    if not isinstance(item, dict):
        raise ValueError("rescue_competition.recce must be a mapping")
    scan_default = 3.0 if legacy_scan_duration is None else float(legacy_scan_duration)
    return RecceMissionConfig(
        config=RecceConfig(
            cylinder_classes=set(_string_list(item, "cylinder_classes", ["recce_cylinder", "cylinder"])),
            hazard_classes=set(
                _string_list(
                    item,
                    "hazard_classes",
                    [
                        "explosive",
                        "flammable",
                        "corrosive",
                        "toxic",
                        "oxidizer",
                        "biohazard",
                        "hazard_sign",
                    ],
                )
            ),
            min_cylinder_confidence=float(item.get("min_cylinder_confidence", 0.35)),
            min_hazard_confidence=float(item.get("min_hazard_confidence", 0.35)),
            vote_min_count=int(item.get("vote_min_count", 3)),
            vote_min_confidence_sum=float(item.get("vote_min_confidence_sum", 1.2)),
        ),
        scan_duration_s=float(item.get("scan_duration_s", scan_default)),
        output_dir=str(item.get("output_dir", "runtime/logs/recce")),
        output_json=_strict_bool(item.get("output_json", True)),
        output_csv=_strict_bool(item.get("output_csv", True)),
    )


def _mapping(item: Any, key: str, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"rescue_competition.{key}[{index}] must be a mapping")
    return item


def _validate_route_end_names(config: RescueCompetitionMissionConfig) -> None:
    if not config.route:
        return
    names = {point.name for point in config.route}
    for field_name, end_name in (
        ("drop_route_end_name", config.drop_route_end_name),
        ("recce_route_end_name", config.recce_route_end_name),
        ("home_route_end_name", config.home_route_end_name),
    ):
        if end_name not in names:
            raise ValueError(f"rescue_competition.{field_name} not found in route: {end_name}")


def _strict_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"invalid payload release boolean: {value!r}")
