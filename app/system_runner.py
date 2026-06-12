from __future__ import annotations

import inspect
import logging
import math
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import yaml
from pymavlink import mavutil

from app.app_config import AppConfig, ROOT_DIR, load_mission_stage_runtime_config, load_telemetry_config
from app.action_dispatcher import ActionDispatcher
from app.action_runtime import ActionRuntimeService
from app.blackbox_recorder import BlackboxRecorder
from app.mission_orchestrator import MissionActionStep, MissionOrchestrator
from app.runtime_context import RuntimeContextBuilder
from app.debug_runtime import DebugRuntime
from app.health_monitor import HealthMonitor
from app.service_manager import ServiceManager
from missions.common.actions.action_lab import action_lab_specs, create_action_lab_registry
from missions.common.actions.runner import ActionRunner
from uav_ui.control_switches import ControlRuntimeSwitches
from uav_ui.terminal_ui import run_terminal_ui
from uav_ui.ui_commands import CommandResult, build_ui_command_handler, format_controller_snapshot
from uav_ui.yolo_command_client import YoloCommandClient

try:
    from app.mission_runner import MissionRunner
    from app.stage_registry import StageRegistry, copy_dataclass_values
    from missions.common.control import (
        CommandShaper,
        FlightCommand,
        FlightCommandExecutor,
        StageInputAdapter,
    )
    from missions.base import MissionContext
    from missions.registry import available_mission_names, build_mission, build_mission_from_settings

    MISSION_RUNTIME_AVAILABLE = True
    MISSION_RUNTIME_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:
    MissionRunner = Any
    StageRegistry = Any
    CommandShaper = Any
    FlightCommandExecutor = Any
    StageInputAdapter = Any
    MissionContext = Any
    MISSION_RUNTIME_AVAILABLE = False
    MISSION_RUNTIME_IMPORT_ERROR = exc

    def available_mission_names() -> tuple[str, ...]:
        return ("action_lab_only",)

    def build_mission(*_args, **_kwargs):
        raise RuntimeError("mission runtime unavailable")

    def build_mission_from_settings(*_args, **_kwargs):
        raise RuntimeError("mission runtime unavailable")

    def copy_dataclass_values(_target, _source) -> None:
        return None

    @dataclass
    class FlightCommand:
        vx_cmd: float = 0.0
        vy_cmd: float = 0.0
        vz_cmd: float = 0.0
        yaw_rate_cmd: float = 0.0
        gimbal_yaw_rate_cmd: float = 0.0
        gimbal_pitch_rate_cmd: float = 0.0
        gimbal_yaw_angle_cmd: float = 0.0
        gimbal_pitch_angle_cmd: float = 0.0
        enable_body: bool = False
        enable_gimbal: bool = False
        enable_gimbal_angle: bool = False
        enable_approach: bool = False
        active: bool = False
        valid: bool = True


class SystemRunner:
    def __init__(self, config: AppConfig, stop_event: threading.Event | None = None) -> None:
        self.config = config
        self.stop_event = stop_event or threading.Event()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.services = ServiceManager(config, self.stop_event)
        self.health_monitor = HealthMonitor(config.health)
        self.mission_enabled = bool(
            getattr(config, "mission_enabled", True) and MISSION_RUNTIME_AVAILABLE
        )
        if not self.mission_enabled:
            reason = MISSION_RUNTIME_IMPORT_ERROR or "mission disabled by configuration"
            self.logger.warning(
                "mission modules unavailable, running action-lab-only mode: %s",
                reason,
            )
            self.input_adapter = None
            self.mission_runner = None
            self.stage_registry = None
            self.command_shaper = None
            self.executor = None
        else:
            self.input_adapter = StageInputAdapter(config=config.input_adapter)
            self.mission_runner = MissionRunner(
                build_mission(config.mission_name, config),
                link_manager=self.services.link_manager,
                yolo_client=YoloCommandClient(config.yolo_command),
            )
            self.stage_registry = StageRegistry(
                approach_config=config.approach_track,
                overhead_config=config.overhead_hold,
                downward_align_descend_config=config.downward_align_descend,
            )
            self.command_shaper = CommandShaper(config=config.shaper)
            self.executor = FlightCommandExecutor(config=config.executor)
        self.blackbox = BlackboxRecorder(config.blackbox)
        self.debug_runtime = DebugRuntime(config.debug)
        self.controller_switches = ControlRuntimeSwitches(
            gimbal=config.start_gimbal,
            body=config.start_body,
            approach=config.start_approach,
            send_commands=config.start_send_commands,
        )
        self.control_command_log: deque[str] = deque(maxlen=120)
        self.control_command_log_lock = threading.Lock()
        self.runtime_config_lock = threading.RLock()
        self.latest_mission_name = config.mission_name if self.mission_enabled else "action_lab_only"
        self.latest_mission_stage = "UNKNOWN" if self.mission_enabled else "NO_MISSION"
        self.latest_stage_controller = "UNKNOWN" if self.mission_enabled else "NO_MISSION"
        self.mission_stage_selections = {
            name: "AUTO" for name in available_mission_names()
        }
        self.latest_hold_reason = ""
        self.last_send_commands: bool | None = None
        self.target_lost_since: float | None = None
        self.lost_target_recenter_sent = False
        self.web_server = None
        self.system_events: deque[dict[str, object]] = deque(maxlen=160)
        self.latest_snapshot: dict[str, object] = {}
        self.latest_localization_result: dict[str, object] = {}
        self.latest_drop_targets_result: dict[str, object] = {}
        self.external_processes: dict[str, subprocess.Popen] = {}
        self.action_lab_specs = action_lab_specs()
        self.action_lab_enabled = True
        self.action_runtime_lock = threading.RLock()
        self.action_runtime = ActionRuntimeService(
            runner=ActionRunner(create_action_lab_registry()),
            dispatcher=ActionDispatcher(
                logger=self.logger,
                yolo_client=YoloCommandClient(self.config.yolo_command),
            )
        )
        self.runtime_context_builder = RuntimeContextBuilder(logger=self.logger)
        self.action_mission_orchestrator: MissionOrchestrator | None = None

    def run(self) -> None:
        self.services.start()
        if self.mission_runner is not None:
            self.mission_runner.link_manager = self.services.link_manager
        self.blackbox.start()
        if self.executor is not None:
            self.executor.set_telemetry_link(self.services.link_manager)
        if self.config.ui.web_enabled:
            from web_ui.server import WebUiServer

            self.web_server = WebUiServer(self, self.config.ui)
            self.web_server.start()
        try:
            if not self.mission_enabled:
                self._action_lab_only_loop()
                return
            if self.config.ui.terminal_enabled and self.services.link_manager is not None:
                self._run_with_ui()
            else:
                if self.config.ui.terminal_enabled and self.services.link_manager is None:
                    self.logger.warning("UI disabled because telemetry is not connected")
                self._control_loop()
        finally:
            self.stop()

    def stop(self) -> None:
        self.stop_event.set()
        if self.executor is not None:
            self.executor.reset()
        self.blackbox.close()
        if self.web_server is not None:
            self.web_server.stop()
            self.web_server = None
        self.services.stop()
        self._stop_external_processes()
        self.logger.info("app runtime stopped")

    def _run_with_ui(self) -> None:
        assert self.services.link_manager is not None
        ui_command_handler = build_ui_command_handler(
            self.services.link_manager,
            controller_switches=self.controller_switches,
            yolo_client=YoloCommandClient(self.config.yolo_command),
            mission_command_handler=self._handle_mission_command,
            stage_override_handler=self._set_stage_override,
            stage_config_reload_handler=self._reload_mission_stage_config,
        )
        control_thread = threading.Thread(
            name="AppControlLoop",
            target=self._control_loop,
            daemon=True,
        )
        control_thread.start()
        try:
            run_terminal_ui(
                self.services.link_manager,
                self.stop_event,
                self._get_mission_control_lines,
                ui_command_handler,
            )
        finally:
            self.stop_event.set()
            control_thread.join(timeout=1.0)

    def _action_lab_only_loop(self) -> None:
        loop_sleep_sec = 1.0 / max(self.config.runtime.loop_hz, 0.1)
        print_sleep_sec = 1.0 / max(self.config.runtime.print_rate_hz, 0.1)
        started_at = time.time()
        last_print_time = 0.0

        try:
            while not self.stop_event.is_set():
                now = time.time()
                run_seconds = self.config.runtime.run_seconds
                if run_seconds is not None and (now - started_at) >= run_seconds:
                    self.stop_event.set()
                    break

                perception = self.services.get_perception(now)
                scene = self.services.get_scene_detections(now)
                drone = self.services.get_drone_state()
                gimbal = self.services.get_gimbal_state()
                link = self.services.get_link_status()
                self.services.fusion_manager.update(perception, drone, gimbal)
                command = FlightCommand(valid=True)

                with self.control_command_log_lock:
                    self.latest_mission_name = "action_lab_only"
                    self.latest_mission_stage = "NO_MISSION"
                    self.latest_stage_controller = "NO_MISSION"
                    self.latest_hold_reason = "mission_disabled"
                    self.latest_snapshot = {
                        "perception": asdict(perception),
                        "scene": asdict(scene),
                        "drone": asdict(drone),
                        "gimbal": asdict(gimbal),
                        "link": asdict(link) if link is not None else {},
                        "health": {"hold_reason": "mission_disabled"},
                        "command": asdict(command),
                        "mission_detail": {
                            "enabled": False,
                            "name": "action_lab_only",
                            "reason": "mission_modules_unavailable",
                        },
                    }

                if (now - last_print_time) >= print_sleep_sec:
                    self.logger.info(
                        "mode=action_lab_only mission disabled; web UI active; SEND=OFF"
                    )
                    last_print_time = now

                time.sleep(loop_sleep_sec)
        except Exception:
            self.logger.exception("app action-lab-only loop failed")
            self.stop_event.set()

    def _control_loop(self) -> None:
        loop_sleep_sec = 1.0 / max(self.config.runtime.loop_hz, 0.1)
        print_sleep_sec = 1.0 / max(self.config.runtime.print_rate_hz, 0.1)
        started_at = time.time()
        last_print_time = 0.0

        try:
            while not self.stop_event.is_set():
                now = time.time()
                run_seconds = self.config.runtime.run_seconds
                if run_seconds is not None and (now - started_at) >= run_seconds:
                    self.stop_event.set()
                    break

                perception = self.services.get_perception(now)
                scene = self.services.get_scene_detections(now)
                drone = self.services.get_drone_state()
                gimbal = self.services.get_gimbal_state()
                link = self.services.get_link_status()
                fused = self.services.fusion_manager.update(perception, drone, gimbal)
                controller_enabled = self.controller_switches.snapshot()
                with self.runtime_config_lock:
                    inputs = self.input_adapter.adapt(fused)
                    health = self.health_monitor.update(inputs)
                    context = MissionContext(
                        timestamp=now,
                        inputs=inputs,
                        health=health,
                        perception=perception,
                        drone=drone,
                        gimbal=gimbal,
                        link=link,
                        scene=scene,
                        actions_enabled=bool(controller_enabled.send_commands),
                    )
                    self.mission_runner.send_actions = bool(controller_enabled.send_commands)
                    mission = self.mission_runner.update(context)
                    mission = self.debug_runtime.apply_mission_override(mission)
                    controller_inputs = self._apply_mission_target_offset(inputs, mission)
                    raw_command, mode_status = self._update_active_mode(
                        mission.active_mode,
                        controller_inputs,
                    )
                    raw_command = self.debug_runtime.apply_command_override(raw_command)
                    raw_command = self._apply_controller_switches(raw_command)
                    raw_for_log = FlightCommand(
                        vx_cmd=raw_command.vx_cmd,
                        vy_cmd=raw_command.vy_cmd,
                        vz_cmd=raw_command.vz_cmd,
                        yaw_rate_cmd=raw_command.yaw_rate_cmd,
                        gimbal_yaw_rate_cmd=raw_command.gimbal_yaw_rate_cmd,
                        gimbal_pitch_rate_cmd=raw_command.gimbal_pitch_rate_cmd,
                        enable_body=raw_command.enable_body,
                        enable_gimbal=raw_command.enable_gimbal,
                        enable_approach=raw_command.enable_approach,
                        active=raw_command.active,
                        valid=raw_command.valid,
                    )
                    shaped = self.command_shaper.update(raw_command, inputs.dt)

                self.executor.config.send_commands = bool(controller_enabled.send_commands)
                if controller_enabled.send_commands:
                    self.executor.execute(shaped)
                    self._record_control_command(now, shaped, send_commands=True)
                    self._maybe_recenter_gimbal_after_target_loss(now, bool(inputs.target_valid), True)
                else:
                    if self.last_send_commands is not False:
                        with self.control_command_log_lock:
                            self.control_command_log.clear()
                            self.control_command_log.appendleft(
                                f"{time.strftime('%H:%M:%S', time.localtime(now))} "
                                "DRY continuous command sending disabled"
                            )
                    self._maybe_recenter_gimbal_after_target_loss(now, bool(inputs.target_valid), False)
                self.last_send_commands = bool(controller_enabled.send_commands)

                self.blackbox.record(
                    now=now,
                    dt=inputs.dt,
                    perception=perception,
                    drone=drone,
                    gimbal=gimbal,
                    link=link,
                    fused=fused,
                    inputs=inputs,
                    mission=mission,
                    health=health,
                    mode_status=mode_status,
                    raw_command=raw_for_log,
                    shaped_command=shaped,
                    send_commands=bool(controller_enabled.send_commands),
                )

                with self.control_command_log_lock:
                    self.latest_mission_name = self.mission_runner.mission.name
                    self.latest_mission_stage = mission.stage or "UNKNOWN"
                    self.latest_stage_controller = mission.active_mode
                    self.latest_hold_reason = mode_status.hold_reason or mission.hold_reason
                    self.latest_snapshot = {
                        "perception": asdict(perception),
                        "scene": asdict(scene),
                        "drone": asdict(drone),
                        "gimbal": asdict(gimbal),
                        "link": asdict(link) if link is not None else {},
                        "health": {"hold_reason": health.hold_reason},
                        "command": asdict(shaped),
                        "mission_detail": dict(mission.detail),
                    }

                if (now - last_print_time) >= print_sleep_sec:
                    self.logger.info(
                        "mode=%s mission=%s health=%s hold=%s enabled=(gimbal:%s body:%s approach:%s send:%s) "
                        "control_allowed=%s target_valid=%s track_id=%s target_size=%.3f "
                        "raw=(vx=%.3f vy=%.3f vz=%.3f yaw=%.3f gimbal=%.3f,%.3f) "
                        "shaped=(vx=%.3f vy=%.3f vz=%.3f yaw=%.3f gimbal=%.3f,%.3f)",
                        mode_status.mode_name,
                        mission.active_mode,
                        health.hold_reason,
                        mode_status.hold_reason or mission.hold_reason,
                        shaped.enable_gimbal,
                        shaped.enable_body,
                        shaped.enable_approach,
                        controller_enabled.send_commands,
                        inputs.control_allowed,
                        inputs.target_valid,
                        inputs.track_id,
                        inputs.target_size,
                        raw_for_log.vx_cmd,
                        raw_for_log.vy_cmd,
                        raw_for_log.vz_cmd,
                        raw_for_log.yaw_rate_cmd,
                        raw_for_log.gimbal_yaw_rate_cmd,
                        raw_for_log.gimbal_pitch_rate_cmd,
                        shaped.vx_cmd,
                        shaped.vy_cmd,
                        shaped.vz_cmd,
                        shaped.yaw_rate_cmd,
                        shaped.gimbal_yaw_rate_cmd,
                        shaped.gimbal_pitch_rate_cmd,
                    )
                    last_print_time = now

                time.sleep(loop_sleep_sec)
        except Exception:
            self.logger.exception("app control loop failed")
            self.stop_event.set()

    def _update_active_mode(self, mode_name: str, inputs) -> tuple[FlightCommand, object]:
        if mode_name == "IDLE":
            return FlightCommand(valid=True), _Status("IDLE", False, True, "idle")
        try:
            mode = self.stage_registry.get(mode_name)
        except KeyError:
            self.logger.warning("unknown mission stage controller %s; commanding zero", mode_name)
            return FlightCommand(valid=True), _Status(mode_name, False, False, "unknown_mode")
        return mode.update(inputs)

    def _apply_mission_target_offset(self, inputs, mission):
        detail = getattr(mission, "detail", {}) or {}
        offset = detail.get("target_error_offset")
        if not isinstance(offset, dict):
            return inputs
        ex_offset = float(offset.get("ex_cam", 0.0))
        ey_offset = float(offset.get("ey_cam", 0.0))
        if math.isclose(ex_offset, 0.0, abs_tol=1e-12) and math.isclose(
            ey_offset,
            0.0,
            abs_tol=1e-12,
        ):
            return inputs
        return replace(
            inputs,
            ex_cam=float(inputs.ex_cam) - ex_offset,
            ey_cam=float(inputs.ey_cam) - ey_offset,
        )

    def _apply_controller_switches(self, command: FlightCommand) -> FlightCommand:
        snapshot = self.controller_switches.snapshot()
        if not snapshot.gimbal:
            command.enable_gimbal = False
            command.gimbal_yaw_rate_cmd = 0.0
            command.gimbal_pitch_rate_cmd = 0.0
        if not snapshot.body:
            command.enable_body = False
            command.vy_cmd = 0.0
            command.vz_cmd = 0.0
            command.yaw_rate_cmd = 0.0
        if not snapshot.approach:
            command.enable_approach = False
            command.vx_cmd = 0.0
        command.active = bool(command.enable_gimbal or command.enable_body or command.enable_approach)
        return command

    def _format_control_command(self, now: float, shaped: FlightCommand, send_commands: bool) -> str:
        return (
            f"{time.strftime('%H:%M:%S', time.localtime(now))} "
            f"{'TX' if send_commands else 'DRY'} "
            f"vx={shaped.vx_cmd:.3f} vy={shaped.vy_cmd:.3f} vz={shaped.vz_cmd:.3f} "
            f"yaw={shaped.yaw_rate_cmd:.3f} "
            f"gimbal=({shaped.gimbal_yaw_rate_cmd:.3f},{shaped.gimbal_pitch_rate_cmd:.3f}) "
            f"en=G{int(shaped.enable_gimbal)} B{int(shaped.enable_body)} A{int(shaped.enable_approach)} "
            f"active={shaped.active} valid={shaped.valid}"
        )

    def _record_control_command(self, now: float, shaped: FlightCommand, send_commands: bool) -> None:
        line = self._format_control_command(now, shaped, send_commands)
        with self.control_command_log_lock:
            self.control_command_log.appendleft(line)

    def disable_automatic_sending(self, reason: str) -> None:
        self.controller_switches.set_send_commands(False)
        if self.services.link_manager is not None:
            self.services.link_manager.clear_continuous_commands()
        self._record_event("SAFETY", f"automatic command sending disabled: {reason}")

    def _record_event(self, level: str, message: str) -> None:
        with self.control_command_log_lock:
            self.system_events.appendleft(
                {"timestamp": time.time(), "level": level, "message": message}
            )

    def web_status_snapshot(self) -> dict[str, object]:
        with self.control_command_log_lock:
            snapshot = dict(self.latest_snapshot)
            snapshot.update(
                {
                    "mission": self.latest_mission_name,
                    "stage": self.latest_mission_stage,
                    "stage_controller": self.latest_stage_controller,
                    "stage_override": self.debug_runtime.config.force_mode,
                    "mission_stage_selection": self._active_mission_stage_selection(),
                    "stage_modes": self._web_stage_modes(),
                    "hold_reason": self.latest_hold_reason,
                    "controllers": asdict(self.controller_switches.snapshot()),
                    "control_commands": list(self.control_command_log)[:40],
                    "events": list(self.system_events)[:40],
                    "actions": self._mission_action_log_lines()[:20],
                    "action_lab": self._action_lab_snapshot(),
                    "action_mission": self.action_mission_status_payload(),
                    "localization": self.latest_localization_result,
                    "drop_targets": self.latest_drop_targets_result,
                }
            )
        manager = self.services.link_manager
        snapshot["active_source"] = manager.get_active_source() if manager is not None else "none"
        return self._json_safe(snapshot)

    def action_lab_context(self) -> dict[str, object]:
        with self.control_command_log_lock:
            snapshot = dict(self.latest_snapshot)
        return self.runtime_context_builder.build_action_context(snapshot)

    def _update_arm_heading(self, drone: dict[str, object]) -> None:
        return self.runtime_context_builder._update_arm_heading(drone)

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        return RuntimeContextBuilder._float_or_none(value)

    def action_lab_tick(self) -> dict[str, object]:
        if not getattr(self, "action_runtime", None):
            return {}
        with self.action_runtime_lock:
            status = self.action_runtime.tick(
                self.action_lab_context(),
                link_manager=self.services.link_manager,
                send_commands=bool(self.controller_switches.snapshot().send_commands),
            )
            self._maybe_save_localization_result()
            self._maybe_save_drop_targets_result()
            self.logger.info(
                "action_lab_tick called current_action=%s dispatch=%s",
                self.action_runtime.action_name,
                self.action_runtime.dispatcher.last_dispatch,
            )
            return status

    def _maybe_save_localization_result(self) -> None:
        """If multi_view_localize just completed, persist its result for Web UI display."""
        name = getattr(self.action_runtime, "action_name", None)
        if name != "multi_view_localize":
            return
        last = getattr(self.action_runtime, "last_result", None)
        if last is None:
            return
        detail = last.get("detail") if isinstance(last, dict) else getattr(last, "detail", None)
        if isinstance(detail, dict):
            detail = detail  # it's a dict
        elif hasattr(detail, "__dict__"):
            detail = detail.__dict__  # type: ignore[union-attr]
        else:
            detail = {}
        done = last.get("done") if isinstance(last, dict) else getattr(last, "done", False)
        if not done:
            return
        localized = detail.get("localized_objects")
        if not isinstance(localized, list):
            return
        self.latest_localization_result = {
            "source": "multi_view_localize",
            "updated_at": time.time(),
            "run_id": detail.get("run_id", ""),
            "objects": localized,
            "object_count": detail.get("object_count", len(localized)),
            "raw_estimates_count": detail.get("raw_estimates_count", 0),
            "captures_count": detail.get("captures_count", 0),
        }

    def _maybe_save_drop_targets_result(self) -> None:
        """If select_drop_targets just completed, persist selected targets for Web UI map."""
        name = getattr(self.action_runtime, "action_name", None)
        if name != "select_drop_targets":
            return
        last = getattr(self.action_runtime, "last_result", None)
        if last is None:
            return
        detail = last.get("detail") if isinstance(last, dict) else getattr(last, "detail", None)
        if isinstance(detail, dict):
            detail = detail
        elif hasattr(detail, "__dict__"):
            detail = detail.__dict__  # type: ignore[union-attr]
        else:
            detail = {}
        done = last.get("done") if isinstance(last, dict) else getattr(last, "done", False)
        if not done:
            return
        selected = detail.get("selected_targets")
        if not isinstance(selected, list):
            return
        self.latest_drop_targets_result = {
            "source": "select_drop_targets",
            "updated_at": time.time(),
            "selected_targets": selected,
            "selected_count": detail.get("selected_count", len(selected)),
            "candidate_count": detail.get("candidate_count", 0),
        }

    def manual_step_move(self, direction: str, step_m: float) -> CommandResult:
        """Move the drone by step_m in the given body-frame direction.

        Allowed directions: forward, back, left, right, up, down.
        The backend reads current LOCAL_NED position and yaw, computes a
        LOCAL_NED absolute target, and sends it with the current yaw as
        a hold value.  Before sending, any running Action is stopped and
        continuous/position queues are cleared.
        """
        allowed = {"forward", "back", "left", "right", "up", "down"}
        if direction not in allowed:
            return CommandResult(False, f"invalid direction: {direction}")
        if not step_m > 0:
            return CommandResult(False, "step_m must be positive")

        manager = self.services.link_manager
        if manager is None:
            return CommandResult(False, "telemetry is not connected")

        with self.control_command_log_lock:
            drone = dict(self.latest_snapshot.get("drone") or {})

        if not drone.get("local_position_valid"):
            return CommandResult(False, "no valid local position — cannot compute manual step target")
        try:
            x = float(drone["local_x"])
            y = float(drone["local_y"])
            z = float(drone["local_z"])
            yaw = float(drone["yaw"])
        except (KeyError, ValueError):
            return CommandResult(False, "current local position or yaw unavailable")
        if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(z) or not math.isfinite(yaw):
            return CommandResult(False, "current position or yaw is not finite")

        # body-frame offset
        forward_m = 0.0
        right_m = 0.0
        down_m = 0.0
        if direction == "forward":
            forward_m = step_m
        elif direction == "back":
            forward_m = -step_m
        elif direction == "right":
            right_m = step_m
        elif direction == "left":
            right_m = -step_m
        elif direction == "down":
            down_m = step_m
        elif direction == "up":
            down_m = -step_m

        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        dx = forward_m * cos_yaw - right_m * sin_yaw
        dy = forward_m * sin_yaw + right_m * cos_yaw
        target_x = x + dx
        target_y = y + dy
        target_z = z + down_m

        # stop any running action and clear queues
        with self.action_runtime_lock:
            if self.action_runtime.runner.state == "running":
                self.action_runtime.stop(link_manager=manager, hold_current=False)
            if self.action_mission_orchestrator is not None and self.action_mission_orchestrator.running:
                self.action_mission_orchestrator.stop(link_manager=manager, hold_current=False)

        clear_continuous = getattr(manager, "clear_continuous_commands", None)
        if callable(clear_continuous):
            clear_continuous()
        clear_pending = getattr(manager, "clear_pending_local_position_actions", None)
        if callable(clear_pending):
            clear_pending()

        from pymavlink import mavutil
        manager.local_position(target_x, target_y, target_z,
                               frame=mavutil.mavlink.MAV_FRAME_LOCAL_NED,
                               yaw=yaw, priority=2)

        with self.control_command_log_lock:
            self.system_events.appendleft({
                "timestamp": time.time(),
                "level": "INFO",
                "message": (f"MANUAL_STEP {direction}={step_m:.2f} "
                            f"from=({x:.2f},{y:.2f},{z:.2f},yaw={yaw:.2f}) "
                            f"to=({target_x:.2f},{target_y:.2f},{target_z:.2f})"),
            })

        return CommandResult(True,
                             f"manual_step {direction} queued "
                             f"target x={target_x:.2f} y={target_y:.2f} z={target_z:.2f} yaw={yaw:.2f}")

    def action_lab_status_payload(self) -> dict[str, object]:
        return self.action_runtime.status_payload(
            send_commands=bool(self.controller_switches.snapshot().send_commands),
        )

    def action_lab_start_action(
        self,
        action_name: str,
        params: dict[str, object] | None = None,
        *,
        send_actions: bool | None = None,
    ):
        with self.action_runtime_lock:
            return self.action_runtime.start(
                action_name,
                params,
                send_actions=send_actions,
                link_manager=self.services.link_manager,
            )

    def action_lab_stop_action(self):
        with self.action_runtime_lock:
            return self.action_runtime.stop(
                link_manager=self.services.link_manager,
                hold_current=True,
            )

    def action_lab_reset_action(self):
        with self.action_runtime_lock:
            return self.action_runtime.reset(
                link_manager=self.services.link_manager,
                hold_current=True,
            )

    # ------------------------------------------------------------------
    # action-mission orchestrator (PR F — lightweight, opt-in)
    # ------------------------------------------------------------------

    def configure_action_mission(self, steps: list[MissionActionStep]) -> None:
        with self.action_runtime_lock:
            self.action_mission_orchestrator = MissionOrchestrator(
                runtime=self.action_runtime,
                steps=steps,
            )

    def action_mission_status_payload(self) -> dict[str, object]:
        if self.action_mission_orchestrator is None:
            return {
                "enabled": False,
                "running": False,
                "done": False,
                "failed": False,
                "current_index": 0,
                "current_action": None,
                "reason": "not_configured",
                "detail": {},
            }
        status = self.action_mission_orchestrator.status()
        detail = dict(status.detail)
        detail["blackboard"] = dict(self.action_mission_orchestrator.blackboard.data)
        return {
            "enabled": True,
            "running": status.running,
            "done": status.done,
            "failed": status.failed,
            "current_index": status.current_index,
            "current_action": status.current_action,
            "reason": status.reason,
            "detail": detail,
        }

    def action_mission_start(self) -> dict[str, object]:
        if self.action_mission_orchestrator is None:
            return self.action_mission_status_payload()
        with self.action_runtime_lock:
            self.action_mission_orchestrator.start(
                link_manager=self.services.link_manager,
            )
            return self.action_mission_status_payload()

    def action_mission_stop(self) -> dict[str, object]:
        if self.action_mission_orchestrator is None:
            return self.action_mission_status_payload()
        with self.action_runtime_lock:
            self.action_mission_orchestrator.stop(
                link_manager=self.services.link_manager,
                hold_current=True,
            )
            return self.action_mission_status_payload()

    def action_mission_reset(self) -> dict[str, object]:
        if self.action_mission_orchestrator is None:
            return self.action_mission_status_payload()
        with self.action_runtime_lock:
            self.action_mission_orchestrator.reset(
                link_manager=self.services.link_manager,
                hold_current=True,
            )
            return self.action_mission_status_payload()

    def action_mission_tick(self) -> dict[str, object]:
        if self.action_mission_orchestrator is None:
            return self.action_mission_status_payload()
        with self.action_runtime_lock:
            self.action_mission_orchestrator.tick(
                self.action_lab_context(),
                link_manager=self.services.link_manager,
                send_commands=bool(self.controller_switches.snapshot().send_commands),
            )
            self._maybe_save_localization_result()
            self._maybe_save_drop_targets_result()
            return self.action_mission_status_payload()

    def _action_lab_snapshot(self) -> dict[str, object]:
        return self.action_runtime.status_payload(
            send_commands=bool(self.controller_switches.snapshot().send_commands),
        ) | {
            "enabled": bool(self.action_lab_enabled),
            "specs": list(self.action_lab_specs),
        }

    def _action_lab_dispatch_gate(self, action_type: str | None = None) -> tuple[bool, str]:
        return self.action_runtime.dispatcher.gate(
            send_commands=bool(self.controller_switches.snapshot().send_commands),
            action_type=action_type,
            action_name=self.action_runtime.runner.action_name if self.action_runtime.runner else None,
        )

    @staticmethod
    def _empty_action_lab_dispatch() -> dict[str, list[dict[str, object]]]:
        return ActionDispatcher.empty_dispatch()

    def _dispatch_action_lab_result(self, result: dict[str, object]) -> dict[str, list[dict[str, object]]]:
        return self.action_runtime.dispatcher.dispatch_result(
            result,
            action_name=self.action_runtime.runner.action_name if self.action_runtime.runner else None,
            send_commands=bool(self.controller_switches.snapshot().send_commands),
            link_manager=self.services.link_manager,
        )

    def _dispatch_action_lab_actions(self, actions: list[object]) -> dict[str, list[dict[str, object]]]:
        return self.action_runtime.dispatcher.dispatch_actions(
            actions,
            action_name=self.action_runtime.runner.action_name if self.action_runtime.runner else None,
            send_commands=bool(self.controller_switches.snapshot().send_commands),
            link_manager=self.services.link_manager,
        )

    @staticmethod
    def _action_type_for_status(action: object) -> str:
        if isinstance(action, dict):
            return str(action.get("action_type") or "")
        return ""

    @staticmethod
    def _callable_accepts_keyword(func, name: str) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return True
        return any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            or parameter.name == name
            for parameter in signature.parameters.values()
        )

    def _web_stage_modes(self) -> list[str]:
        if self.mission_runner is None:
            return ["NO_MISSION"]
        mission_name = self.mission_runner.mission.name
        if mission_name == "rescue_competition":
            from missions.rescue_competition.mission import RescueStage

            return list(dict.fromkeys(["AUTO", *[stage.value for stage in RescueStage]]))
        if mission_name == "visual_tracking":
            return ["AUTO", "IDLE", "APPROACH_TRACK", "OVERHEAD_HOLD", "CORRIDOR_FOLLOW"]
        return ["AUTO", "IDLE"]

    def _active_mission_stage_selection(self) -> str:
        if self.mission_runner is None:
            return "NO_MISSION"
        return self.mission_stage_selections.get(self.mission_runner.mission.name, "AUTO")

    def _mission_action_log_lines(self) -> list[str]:
        if self.mission_runner is None:
            return []
        return self.mission_runner.get_action_log_lines()

    @classmethod
    def _json_safe(cls, value):
        return RuntimeContextBuilder.json_safe(value)

    def web_execute_command(self, command: str) -> CommandResult:
        stripped = command.strip()
        if not stripped:
            return CommandResult(False, "empty command")
        if stripped.startswith("switch_source "):
            self.disable_automatic_sending("source_switch")
        manager = self.services.link_manager
        if manager is None:
            if stripped.startswith("target "):
                return self._execute_yolo_command(stripped)
            return CommandResult(False, "telemetry is not connected")
        handler = build_ui_command_handler(
            manager,
            controller_switches=self.controller_switches,
            yolo_client=YoloCommandClient(self.config.yolo_command),
            mission_command_handler=self._handle_mission_command,
            stage_override_handler=self._set_stage_override,
            stage_config_reload_handler=self._reload_mission_stage_config,
        )
        result = handler(stripped)
        self._record_event("OK" if result.ok else "ERROR", result.message)
        return result

    def _execute_yolo_command(self, command: str) -> CommandResult:
        parts = command.split()
        client = YoloCommandClient(self.config.yolo_command)
        try:
            if parts[1] == "lock" and len(parts) == 3:
                client.lock_target(int(parts[2]))
            elif parts[1] == "unlock":
                client.unlock_target()
            elif parts[1] == "next":
                client.send("switch_next")
            elif parts[1] in {"prev", "previous"}:
                client.send("switch_prev")
            else:
                return CommandResult(False, "format: target <next|prev|lock <track_id>|unlock>")
        except Exception as exc:
            return CommandResult(False, f"target command failed: {exc}")
        result = CommandResult(True, f"{command} sent")
        self._record_event("OK", result.message)
        return result

    def web_missions(self) -> list[dict[str, object]]:
        if self.mission_runner is None:
            return [
                {
                    "name": "action_lab_only",
                    "active": True,
                    "enabled": False,
                    "config_path": "",
                    "stage_modes": ["NO_MISSION"],
                    "selected_stage": "NO_MISSION",
                }
            ]
        active = self.mission_runner.mission.name
        return [
            {
                "name": name,
                "active": name == active,
                "config_path": f"missions/{name}/config.yaml",
                "stage_modes": self._web_stage_modes_for_mission(name),
                "selected_stage": self.mission_stage_selections.get(name, "AUTO"),
            }
            for name in available_mission_names()
        ]

    def _web_stage_modes_for_mission(self, mission_name: str) -> list[str]:
        if self.mission_runner is None:
            return ["NO_MISSION"]
        if mission_name == "rescue_competition":
            from missions.rescue_competition.mission import RescueStage

            return list(dict.fromkeys([stage.value for stage in RescueStage]))
        if mission_name == "visual_tracking":
            return ["IDLE", "APPROACH_TRACK", "OVERHEAD_HOLD", "CORRIDOR_FOLLOW"]
        return []

    def apply_active_mission_config(self, relative_path: str) -> CommandResult:
        if self.mission_runner is None:
            return CommandResult(True, "mission disabled; configuration saved for later use")
        active_path = f"missions/{self.mission_runner.mission.name}/config.yaml"
        if relative_path != active_path:
            return CommandResult(True, "mission config saved; applies when that mission is selected")
        self.disable_automatic_sending("mission_config_apply")
        try:
            settings = self._load_mission_settings(self.mission_runner.mission.name)
            mission = build_mission_from_settings(
                self.mission_runner.mission.name,
                settings,
                visual_config=self.config.visual_tracking,
            )
            with self.runtime_config_lock:
                self.mission_runner.mission = mission
                self.config.mission_settings = dict(settings)
                self._reset_mission_runtime(clear_for_safety=True)
            result = self._reload_mission_stage_config()
        except Exception as exc:
            self.logger.exception("failed to reload active mission config")
            result = CommandResult(False, f"mission config reload failed: {exc}")
        self._record_event("CONFIG" if result.ok else "ERROR", result.message)
        return result

    def reconnect_telemetry_from_saved_config(self) -> CommandResult:
        try:
            config = load_telemetry_config(str(ROOT_DIR / "config" / "telemetry.yaml"))
        except Exception as exc:
            return CommandResult(False, f"telemetry configuration invalid: {exc}")
        self.disable_automatic_sending("telemetry_reconnect")
        self.services.reconnect_telemetry(config)
        if self.mission_runner is not None:
            self.mission_runner.link_manager = self.services.link_manager
        if self.executor is not None:
            self.executor.set_telemetry_link(self.services.link_manager)
        self._record_event("LINK", "telemetry reconnect started; SEND remains OFF")
        return CommandResult(True, "telemetry reconnect started; SEND remains OFF")

    def restart_external_service(self, service: str) -> CommandResult:
        command = (
            self.config.services_control.restart_yolo_command
            if service == "yolo"
            else self.config.services_control.restart_app_command
            if service == "app"
            else []
        )
        if not command:
            return CommandResult(False, f"{service} restart command is not configured")
        if service == "app":
            self.disable_automatic_sending("app_restart")
        try:
            self._stop_external_process(service)
            process = subprocess.Popen(command, start_new_session=True)
        except OSError as exc:
            return CommandResult(False, f"failed to restart {service}: {exc}")
        self.external_processes[service] = process
        self._record_event("SERVICE", f"{service} restart requested")
        return CommandResult(True, f"{service} restart requested pid={process.pid}")

    def _stop_external_processes(self) -> None:
        for service in list(self.external_processes):
            self._stop_external_process(service)

    def _stop_external_process(self, service: str) -> None:
        process = self.external_processes.pop(service, None)
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass

    def _get_mission_control_lines(self) -> list[str]:
        with self.control_command_log_lock:
            return [
                f"Controllers {format_controller_snapshot(self.controller_switches.snapshot())}",
                f"Mission {self.latest_mission_name} stage={self.latest_mission_stage}",
                f"Stage controller {self.latest_stage_controller}",
                f"Hold {self.latest_hold_reason or 'none'}",
                *self._mission_action_log_lines(),
                *list(self.control_command_log),
            ]

    def _set_stage_override(self, mode_name: str | None) -> CommandResult:
        if self.stage_registry is None:
            return CommandResult(False, "mission disabled; stage override unavailable")
        with self.runtime_config_lock:
            if mode_name is None:
                self.debug_runtime.config.force_mode = None
                self.stage_registry.reset_all()
                return CommandResult(True, "stage override auto")
            normalized = mode_name.strip().upper()
            if normalized == "IDLE":
                self.debug_runtime.config.force_mode = normalized
                return CommandResult(True, "stage override forced IDLE")
            try:
                self.stage_registry.get(normalized)
            except KeyError:
                return CommandResult(
                    False,
                    "stage override must be APPROACH_TRACK, OVERHEAD_HOLD, CORRIDOR_FOLLOW, IDLE, or auto",
                )
            self.debug_runtime.config.force_mode = normalized
            return CommandResult(True, f"stage override forced {normalized}")

    def _handle_mission_command(self, parts: list[str]) -> CommandResult:
        if self.mission_runner is None:
            return CommandResult(False, "mission disabled; running action_lab_only")
        if not parts:
            return CommandResult(
                False,
                "format: mission list | mission switch <name> | mission stage <name> | mission start | mission reset | mission current",
            )
        action = parts[0].lower()
        if action in {"list", "ls"}:
            names = ", ".join(available_mission_names())
            return CommandResult(
                True,
                f"missions: {names}; active={self.mission_runner.mission.name}",
            )
        if action in {"current", "status"}:
            return CommandResult(True, f"active mission={self.mission_runner.mission.name}")
        if action == "stage":
            if len(parts) != 2:
                return CommandResult(False, "format: mission stage <stage_name|auto>")
            stage_name = parts[1].strip().upper()
            if stage_name == "AUTO":
                with self.runtime_config_lock:
                    self.mission_stage_selections[self.mission_runner.mission.name] = "AUTO"
                    self.debug_runtime.config.force_mode = None
                    self.stage_registry.reset_all()
                return CommandResult(True, "mission stage auto")
            setter = getattr(self.mission_runner.mission, "set_stage", None)
            if not callable(setter):
                return CommandResult(False, f"mission stage unsupported: {self.mission_runner.mission.name}")
            try:
                with self.runtime_config_lock:
                    setter(stage_name)
                    self.mission_stage_selections[self.mission_runner.mission.name] = stage_name
                    self.debug_runtime.config.force_mode = None
                    self.stage_registry.reset_all()
                with self.control_command_log_lock:
                    self.latest_mission_stage = stage_name
                return CommandResult(True, f"mission stage set: {stage_name}")
            except Exception as exc:
                return CommandResult(False, f"mission stage failed: {exc}")
        if action == "start":
            starter = getattr(self.mission_runner.mission, "start", None)
            if not callable(starter):
                return CommandResult(
                    False,
                    f"mission start unsupported: {self.mission_runner.mission.name}",
                )
            with self.runtime_config_lock:
                starter()
                return CommandResult(True, f"mission start requested: {self.mission_runner.mission.name}")
        if action == "reset":
            with self.runtime_config_lock:
                self._reset_mission_runtime(clear_for_safety=True)
                return CommandResult(True, f"mission reset: {self.mission_runner.mission.name}; SEND=OFF")
        if action in {"switch", "select", "use"}:
            if len(parts) != 2:
                return CommandResult(False, "format: mission switch <name>")
            return self._switch_mission(parts[1])
        return CommandResult(
            False,
            "format: mission list | mission switch <name> | mission stage <name> | mission start | mission reset | mission current",
        )

    def _switch_mission(self, mission_name: str) -> CommandResult:
        if self.mission_runner is None:
            return CommandResult(False, "mission disabled; running action_lab_only")
        normalized = mission_name.strip().lower()
        if normalized not in available_mission_names():
            return CommandResult(
                False,
                f"unknown mission: {mission_name}; available={', '.join(available_mission_names())}",
            )
        try:
            settings = self._load_mission_settings(normalized)
            mission = build_mission_from_settings(
                normalized,
                settings,
                visual_config=self.config.visual_tracking,
            )
        except Exception as exc:
            self.logger.exception("failed to switch mission")
            return CommandResult(False, f"mission switch failed: {exc}")

        with self.runtime_config_lock:
            previous = self.mission_runner.mission.name
            self.mission_runner.mission = mission
            self.config.mission_name = normalized
            self.config.mission_settings = dict(settings)
            config_path = self._mission_config_path(normalized)
            self.config.mission_config_path = str(config_path)
            self.debug_runtime.config.force_mode = None
            self._reset_mission_runtime(clear_for_safety=True)
        reload_result = self._reload_mission_stage_config()
        if not reload_result.ok:
            return reload_result
        return CommandResult(
            True,
            f"mission switched {previous} -> {mission.name}; stage auto; SEND=OFF",
        )

    def _reset_mission_runtime(self, *, clear_for_safety: bool) -> None:
        if self.mission_runner is None:
            self.target_lost_since = None
            self.lost_target_recenter_sent = False
            with self.control_command_log_lock:
                self.latest_mission_name = "action_lab_only"
                self.latest_mission_stage = "NO_MISSION"
                self.latest_stage_controller = "NO_MISSION"
                self.latest_hold_reason = "mission_disabled"
                self.control_command_log.clear()
            if clear_for_safety:
                self.controller_switches.set_send_commands(False)
                if self.services.link_manager is not None:
                    clear_sender = getattr(self.services.link_manager, "clear_continuous_commands", None)
                    if callable(clear_sender):
                        clear_sender()
            return
        self.mission_runner.reset()
        self.mission_stage_selections[self.mission_runner.mission.name] = "AUTO"
        self.stage_registry.reset_all()
        self.command_shaper.reset()
        self.target_lost_since = None
        self.lost_target_recenter_sent = False
        with self.control_command_log_lock:
            self.latest_mission_name = self.mission_runner.mission.name
            self.latest_mission_stage = "UNKNOWN"
            self.latest_stage_controller = "UNKNOWN"
            self.latest_hold_reason = ""
            self.control_command_log.clear()
        if clear_for_safety:
            self.controller_switches.set_send_commands(False)
            if self.services.link_manager is not None:
                clear_sender = getattr(self.services.link_manager, "clear_continuous_commands", None)
                if callable(clear_sender):
                    clear_sender()

    def _load_mission_settings(self, mission_name: str) -> dict[str, object]:
        config_path = self._mission_config_path(mission_name)
        if not config_path.exists():
            if mission_name == self.config.mission_name:
                return dict(self.config.mission_settings)
            return {"name": mission_name}
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"mission config must be a mapping: {config_path}")
        return dict(data)

    def _mission_config_path(self, mission_name: str) -> Path:
        return (
            Path(__file__).resolve().parent.parent
            / "missions"
            / mission_name
            / "config.yaml"
        )

    def _reload_mission_stage_config(self) -> CommandResult:
        if self.mission_runner is None:
            return CommandResult(False, "mission disabled; stage config reload unavailable")
        path = self.config.mission_config_path
        if not path:
            return CommandResult(False, "mission config reload is unavailable for legacy config")
        try:
            (
                input_adapter_cfg,
                health_cfg,
                approach_cfg,
                overhead_cfg,
                downward_align_descend_cfg,
                shaper_cfg,
            ) = load_mission_stage_runtime_config(
                self.config.mission_config_path,
            )
        except Exception as exc:
            self.logger.exception("failed to reload mission config")
            return CommandResult(False, f"mission config reload failed: {exc}")

        with self.runtime_config_lock:
            copy_dataclass_values(self.config.input_adapter, input_adapter_cfg)
            copy_dataclass_values(self.config.health, health_cfg)
            copy_dataclass_values(self.config.approach_track, approach_cfg)
            copy_dataclass_values(self.config.overhead_hold, overhead_cfg)
            copy_dataclass_values(
                self.config.downward_align_descend,
                downward_align_descend_cfg,
            )
            copy_dataclass_values(self.config.shaper, shaper_cfg)
            self.stage_registry.apply_configs(
                approach_config=approach_cfg,
                overhead_config=overhead_cfg,
                downward_align_descend_config=downward_align_descend_cfg,
                reset=True,
            )
            self.input_adapter.config = self.config.input_adapter
            self.health_monitor.config = self.config.health
            self.command_shaper.config = self.config.shaper
            self.command_shaper.reset()

        self.logger.info("reloaded mission config from %s", path)
        return CommandResult(True, f"mission config reloaded: {path}")

    def _maybe_recenter_gimbal_after_target_loss(
        self,
        now: float,
        target_valid: bool,
        send_commands: bool,
    ) -> None:
        if target_valid:
            self.target_lost_since = None
            self.lost_target_recenter_sent = False
            return
        if self.target_lost_since is None:
            self.target_lost_since = now
            return
        if self.lost_target_recenter_sent or not send_commands:
            return
        if self.services.link_manager is None:
            return
        if not self.config.runtime.lost_target_recenter_enabled:
            return
        if (now - self.target_lost_since) < self.config.runtime.lost_target_recenter_timeout_sec:
            return
        clear_sender = getattr(self.services.link_manager, "clear_continuous_commands", None)
        if callable(clear_sender):
            clear_sender()
        self.services.link_manager.send_gimbal_angle(
            pitch=self.config.runtime.lost_target_recenter_pitch_deg,
            yaw=self.config.runtime.lost_target_recenter_yaw_deg,
            roll=self.config.executor.gimbal_roll_deg,
        )
        self.lost_target_recenter_sent = True
        with self.control_command_log_lock:
            self.control_command_log.appendleft(
                f"{time.strftime('%H:%M:%S', time.localtime(now))} "
                "TX lost target recenter gimbal "
                f"pitch={self.config.runtime.lost_target_recenter_pitch_deg:.1f} "
                f"yaw={self.config.runtime.lost_target_recenter_yaw_deg:.1f}"
            )

    # ------------------------------------------------------------------
    # backward-compatible properties for Action Lab fields
    # ------------------------------------------------------------------

    @property
    def action_runner(self):
        return self.action_runtime.runner

    # backward-compatible properties for arm heading / context builder
    # ------------------------------------------------------------------

    @property
    def arm_heading_yaw_rad(self) -> float | None:
        return self.runtime_context_builder.arm_heading_yaw_rad

    @arm_heading_yaw_rad.setter
    def arm_heading_yaw_rad(self, value: float | None) -> None:
        self.runtime_context_builder.arm_heading_yaw_rad = value

    @property
    def arm_heading_time(self) -> float | None:
        return self.runtime_context_builder.arm_heading_time

    @arm_heading_time.setter
    def arm_heading_time(self, value: float | None) -> None:
        self.runtime_context_builder.arm_heading_time = value

    @property
    def arm_heading_fallback(self) -> bool:
        return self.runtime_context_builder.arm_heading_fallback

    @arm_heading_fallback.setter
    def arm_heading_fallback(self, value: bool) -> None:
        self.runtime_context_builder.arm_heading_fallback = bool(value)

    @property
    def _last_vehicle_armed(self) -> bool | None:
        return self.runtime_context_builder._last_vehicle_armed

    @_last_vehicle_armed.setter
    def _last_vehicle_armed(self, value: bool | None) -> None:
        self.runtime_context_builder._last_vehicle_armed = value

    # backward-compatible properties for Action Lab dispatch fields
    # ------------------------------------------------------------------

    @property
    def action_lab_send_actions(self) -> bool:
        return self.action_runtime.dispatcher.send_actions

    @action_lab_send_actions.setter
    def action_lab_send_actions(self, value: bool) -> None:
        self.action_runtime.dispatcher.send_actions = bool(value)

    @property
    def action_lab_dispatched_keys(self) -> set[str]:
        return self.action_runtime.dispatcher.dispatched_keys

    @action_lab_dispatched_keys.setter
    def action_lab_dispatched_keys(self, value: set[str]) -> None:
        self.action_runtime.dispatcher.dispatched_keys = value

    @property
    def action_lab_last_dispatch(self) -> dict[str, list[dict[str, object]]]:
        return self.action_runtime.dispatcher.last_dispatch

    @action_lab_last_dispatch.setter
    def action_lab_last_dispatch(self, value: dict[str, list[dict[str, object]]]) -> None:
        self.action_runtime.dispatcher.last_dispatch = value

    @property
    def action_lab_last_servo_command(self) -> dict[str, object] | None:
        return self.action_runtime.dispatcher.last_servo_command

    @action_lab_last_servo_command.setter
    def action_lab_last_servo_command(self, value: dict[str, object] | None) -> None:
        self.action_runtime.dispatcher.last_servo_command = value


class _Status:
    def __init__(self, mode_name: str, active: bool, valid: bool, hold_reason: str) -> None:
        self.mode_name = mode_name
        self.active = active
        self.valid = valid
        self.hold_reason = hold_reason
        self.detail = {}
