from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import asdict
from typing import Any, Callable

from field.context import RuntimeContextBuilder


class WebStatusService:
    """Read-only web status snapshot builder.

    Extracted from the application runner (SR-2). All dependencies are injected
    via constructor as callables or simple references.  Does not start
    or stop services, send commands, or touch LinkManager's write path.
    """

    def __init__(
        self,
        *,
        runtime_context_builder: RuntimeContextBuilder,
        get_snapshot: Callable[[], dict[str, object]],
        lock: threading.Lock,
        controller_switches: Any = None,
        control_command_log: deque | None = None,
        system_events: deque | None = None,
        action_lab_enabled: bool = False,
        action_lab_specs: list | None = None,
        get_action_mission_status_payload: Callable[[], dict[str, object]] | None = None,
        get_action_runtime: Callable[[], Any] | None = None,
        latest_localization_result: dict[str, object] | None = None,
        latest_drop_targets_result: dict[str, object] | None = None,
        latest_drop_localization_result: dict[str, object] | None = None,
        latest_recon_localization_result: dict[str, object] | None = None,
        latest_recon_targets_result: dict[str, object] | None = None,
        latest_recon_inspection_result: dict[str, object] | None = None,
        get_latest_localization_result: Callable[[], dict[str, object]] | None = None,
        get_latest_drop_targets_result: Callable[[], dict[str, object]] | None = None,
        get_latest_drop_localization_result: Callable[[], dict[str, object]] | None = None,
        get_latest_recon_localization_result: Callable[[], dict[str, object]] | None = None,
        get_latest_recon_targets_result: Callable[[], dict[str, object]] | None = None,
        get_latest_recon_inspection_result: Callable[[], dict[str, object]] | None = None,
        get_latest_drop_workflow_result: Callable[[], dict[str, object]] | None = None,
        get_link_manager: Callable[[], Any] | None = None,
        latest_mission_name: str = "",
        latest_mission_stage: str = "",
        latest_stage_controller: str = "",
        latest_hold_reason: str = "",
    ) -> None:
        self._builder = runtime_context_builder
        self._get_snapshot = get_snapshot
        self._lock = lock
        self._switches = controller_switches
        self._control_command_log = control_command_log or deque(maxlen=40)
        self._system_events = system_events or deque(maxlen=40)
        self._action_runtime = None  # resolved lazily via get_action_runtime
        self._get_action_runtime = get_action_runtime
        self._action_lab_enabled = action_lab_enabled
        self._action_lab_specs = action_lab_specs or []
        self._get_action_mission_status_payload = get_action_mission_status_payload
        self._latest_localization = latest_localization_result
        self._latest_drop_targets = latest_drop_targets_result
        self._latest_drop_localization = latest_drop_localization_result
        self._latest_recon_localization = latest_recon_localization_result
        self._latest_recon_targets = latest_recon_targets_result
        self._latest_recon = latest_recon_inspection_result
        self._get_latest_localization_result = get_latest_localization_result
        self._get_latest_drop_targets_result = get_latest_drop_targets_result
        self._get_latest_drop_localization_result = get_latest_drop_localization_result
        self._get_latest_recon_localization_result = get_latest_recon_localization_result
        self._get_latest_recon_targets_result = get_latest_recon_targets_result
        self._get_latest_recon_inspection_result = get_latest_recon_inspection_result
        self._get_latest_drop_workflow_result = get_latest_drop_workflow_result
        self._get_link_manager = get_link_manager
        self._latest_mission_name = latest_mission_name
        self._latest_mission_stage = latest_mission_stage
        self._latest_stage_controller = latest_stage_controller
        self._latest_hold_reason = latest_hold_reason

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        # Keep the shared-state critical section deliberately small.  The
        # callbacks below may acquire their own locks (Action runtime,
        # Mission orchestrator, LinkManager, and runtime switches), so calling
        # them while holding this plain Lock creates lock-order coupling with
        # the main loop and command handlers.
        with self._lock:
            snapshot = dict(self._get_snapshot())
            control_commands = list(self._control_command_log)[:40]
            events = list(self._system_events)[:40]

        snapshot.update({
            "mission": self._latest_mission_name,
            "stage": self._latest_mission_stage,
            "stage_controller": self._latest_stage_controller,
            "hold_reason": self._latest_hold_reason,
            "controllers": (
                asdict(self._switches.snapshot()) if self._switches else {}
            ),
            "control_commands": control_commands,
            "events": events,
            "actions": self._mission_action_log_lines()[:20],
            "action_lab": self._action_lab_snapshot(),
            "action_mission": (
                self._get_action_mission_status_payload()
                if self._get_action_mission_status_payload
                else {}
            ),
            "localization": (
                self._get_latest_localization_result()
                if self._get_latest_localization_result
                else self._latest_localization
            ) or {},
            "drop_targets": (
                self._get_latest_drop_targets_result()
                if self._get_latest_drop_targets_result
                else self._latest_drop_targets
            ) or {},
            "drop_localization": (self._get_latest_drop_localization_result() if self._get_latest_drop_localization_result else self._latest_drop_localization) or {},
            "recon_localization": (self._get_latest_recon_localization_result() if self._get_latest_recon_localization_result else self._latest_recon_localization) or {},
            "recon_targets": (self._get_latest_recon_targets_result() if self._get_latest_recon_targets_result else self._latest_recon_targets) or {},
            "recon_inspection": (
                self._get_latest_recon_inspection_result()
                if self._get_latest_recon_inspection_result
                else self._latest_recon
            ) or {},
            "drop_workflow": (
                self._get_latest_drop_workflow_result()
                if self._get_latest_drop_workflow_result
                else {}
            ) or {},
        })
        manager = self._get_link_manager() if self._get_link_manager else None
        snapshot["active_source"] = (
            manager.get_active_source() if manager is not None else "none"
        )
        snapshot["field_heading"] = self.field_heading_status()
        drone = snapshot.get("drone", {})
        snapshot["field_position"] = self._builder.field_position_from_drone(drone)
        return RuntimeContextBuilder.json_safe(snapshot)

    # ------------------------------------------------------------------
    # field heading status
    # ------------------------------------------------------------------

    def field_heading_status(self) -> dict[str, object]:
        builder = self._builder
        with self._lock:
            snapshot = dict(self._get_snapshot())
        drone = snapshot.get("drone", {})
        current_yaw = None
        attitude_valid = False
        local_position_valid = False
        if isinstance(drone, dict):
            attitude_valid = bool(drone.get("attitude_valid", False))
            local_position_valid = bool(drone.get("local_position_valid", False))
            current_yaw = RuntimeContextBuilder._float_or_none(drone.get("yaw"))

        field_yaw = builder.field_heading_yaw_rad
        pre_arm_yaw = builder.pre_arm_yaw_rad
        arm_yaw = builder.arm_heading_yaw_rad
        field_position = builder.field_position_from_drone(drone)

        def deg(rad: float | None) -> float | None:
            return None if rad is None else math.degrees(float(rad))

        def yaw_delta_deg(a: float | None, b: float | None) -> float | None:
            if a is None or b is None:
                return None
            delta = math.atan2(
                math.sin(float(a) - float(b)), math.cos(float(a) - float(b)),
            )
            return math.degrees(delta)

        return {
            "attitude_valid": attitude_valid,
            "local_position_valid": local_position_valid,
            "current_yaw_rad": current_yaw,
            "current_yaw_deg": deg(current_yaw),
            "pre_arm_yaw_rad": pre_arm_yaw,
            "pre_arm_yaw_deg": deg(pre_arm_yaw),
            "arm_heading_yaw_rad": arm_yaw,
            "arm_heading_yaw_deg": deg(arm_yaw),
            "arm_heading_fallback": bool(builder.arm_heading_fallback),
            "field_heading_yaw_rad": field_yaw,
            "field_heading_yaw_deg": deg(field_yaw),
            "field_heading_confirmed": bool(builder.field_heading_confirmed),
            "field_heading_source": builder.field_heading_source,
            "field_heading_time": builder.field_heading_time,
            "delta_current_to_field_deg": yaw_delta_deg(current_yaw, field_yaw),
            "field_origin_time": builder.field_origin_time,
            "current_field_x": field_position.get("x") if field_position else None,
            "current_field_y": field_position.get("y") if field_position else None,
            "current_field_z": field_position.get("z") if field_position else None,
            "current_local_z": field_position.get("local_z") if field_position else None,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _action_lab_snapshot(self) -> dict[str, object]:
        action_runtime = (
            self._get_action_runtime() if self._get_action_runtime else None
        )
        if action_runtime is None:
            return {"enabled": False, "specs": [], "status": {}}
        return action_runtime.status_payload(
            send_commands=bool(self._switches.snapshot().send_commands),
        ) | {
            "enabled": bool(self._action_lab_enabled),
            "specs": list(self._action_lab_specs),
        }

    def _mission_action_log_lines(self) -> list[str]:
        return []
