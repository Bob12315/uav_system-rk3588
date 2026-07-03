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
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any

from pymavlink import mavutil

from app.app_config import AppConfig, ROOT_DIR, load_telemetry_config
from app.action_dispatcher import ActionDispatcher
from app.action_runtime import ActionRuntimeService
from app.blackbox_recorder import BlackboxRecorder
from app.mission_orchestrator import MissionActionStep, MissionOrchestrator
from app.runtime_context import RuntimeContextBuilder
from app.field_reference_service import FieldReferenceService
from app.field_reference_controller import FieldReferenceController
from app.field_profile_service import FieldProfileService
from app.field_profile import FieldProfile
from app.web_status_service import WebStatusService
from app.command_pipeline import CommandPipeline
from app.debug_runtime import DebugRuntime
from app.health_monitor import HealthMonitor
from app.service_manager import ServiceManager
from missions.common.actions.action_lab import action_lab_specs, create_action_lab_registry
from missions.common.actions.runner import ActionRunner
from app.control_switches import ControlRuntimeSwitches

from app.ui_commands import CommandResult, build_ui_command_handler, format_controller_snapshot
from app.yolo_command_client import YoloCommandClient

@dataclass(frozen=True, slots=True)
class _IdleCommandSnapshot:
    """Neutral blackbox/status value for the current Action-only runtime."""

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
        self.mission_enabled = False
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
        self.latest_mission_name = "action_lab_only"
        self.latest_mission_stage = "NO_MISSION"
        self.latest_stage_controller = "NO_MISSION"
        self.latest_hold_reason = "mission_disabled"
        self.last_send_commands: bool | None = None
        self.web_server = None
        self.system_events: deque[dict[str, object]] = deque(maxlen=160)
        self.latest_snapshot: dict[str, object] = {}
        self.latest_localization_result: dict[str, object] = {}
        self.latest_drop_targets_result: dict[str, object] = {}
        self.latest_recon_inspection_result: dict[str, object] = {}
        self.camera_recording: dict[str, object] = {
            "recording": False,
            "path": "",
            "message": "未录制",
        }
        self.external_processes: dict[str, subprocess.Popen] = {}
        self.action_lab_specs = action_lab_specs()
        self.action_lab_enabled = True
        self.action_runtime_lock = threading.RLock()
        self.runtime_context_builder = RuntimeContextBuilder(logger=self.logger)
        self.field_reference_service = FieldReferenceService()
        self.field_reference_controller = FieldReferenceController(
            field_reference_service=self.field_reference_service,
            runtime_context_builder=self.runtime_context_builder,
            get_drone_snapshot=self._drone_snapshot_raw,
        )
        self.web_status_service = WebStatusService(
            runtime_context_builder=self.runtime_context_builder,
            get_snapshot=lambda: self.latest_snapshot,
            lock=self.control_command_log_lock,
            debug_runtime=self.debug_runtime,
            controller_switches=self.controller_switches,
            control_command_log=self.control_command_log,
            system_events=self.system_events,
            action_lab_enabled=self.action_lab_enabled,
            action_lab_specs=self.action_lab_specs,
            get_action_mission_status_payload=self.action_mission_status_payload,
            get_link_manager=lambda: self.services.link_manager,
            get_action_runtime=lambda: self.action_runtime,
            latest_mission_name=self.latest_mission_name,
            latest_mission_stage=self.latest_mission_stage,
            latest_stage_controller=self.latest_stage_controller,
            latest_hold_reason=self.latest_hold_reason,
        )
        self.command_pipeline = CommandPipeline(
            yolo_command_config=self.config.yolo_command,
            camera_recording=self.camera_recording,
            external_processes=self.external_processes,
            record_event=self._record_event,
        )
        self.action_runtime = ActionRuntimeService(
            runner=ActionRunner(create_action_lab_registry()),
            dispatcher=ActionDispatcher(
                logger=self.logger,
                yolo_client=YoloCommandClient(self.config.yolo_command),
                field_heading_confirmer=self.protected_confirm_field_heading,
            )
        )
        self.action_mission_orchestrator: MissionOrchestrator | None = None

    def run(self) -> None:
        self.services.start()
        self.blackbox.start()
        if self.config.ui.web_enabled:
            from web_ui.server import WebUiServer

            self.web_server = WebUiServer(self, self.config.ui)
            self.web_server.start()
        try:
            self._action_lab_only_loop()
        finally:
            self.stop()

    def stop(self) -> None:
        self.stop_event.set()
        self.blackbox.close()
        if self.web_server is not None:
            self.web_server.stop()
            self.web_server = None
        self.services.stop()
        self._stop_external_processes()
        self.logger.info("app runtime stopped")

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
                fused = self.services.fusion_manager.update(perception, drone, gimbal)
                command = _IdleCommandSnapshot()
                inputs = SimpleNamespace(
                    dt=loop_sleep_sec,
                    target_valid=bool(getattr(perception, "target_valid", False)),
                    target_locked=str(getattr(perception, "tracking_state", "")).lower() == "locked",
                    control_allowed=bool(getattr(drone, "control_allowed", False)),
                )
                mission = SimpleNamespace(
                    active_mode="action_lab_only",
                    hold_reason="mission_disabled",
                )
                mode_status = SimpleNamespace(
                    mode_name="action_lab_only",
                    hold_reason="mission_disabled",
                )
                health = SimpleNamespace(hold_reason="mission_disabled")

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

                self._record_blackbox_cycle(
                    now=now,
                    dt=loop_sleep_sec,
                    perception=perception,
                    drone=drone,
                    gimbal=gimbal,
                    link=link,
                    fused=fused,
                    inputs=inputs,
                    mission=mission,
                    health=health,
                    mode_status=mode_status,
                    raw_command=command,
                    shaped_command=command,
                    send_commands=False,
                )

                if (now - last_print_time) >= print_sleep_sec:
                    self.logger.info(
                        "mode=action_lab_only mission disabled; web UI active; SEND=OFF"
                    )
                    last_print_time = now

                time.sleep(loop_sleep_sec)
        except Exception:
            self.logger.exception("app action-lab-only loop failed")
            self.stop_event.set()

    def _record_blackbox_cycle(
        self,
        *,
        now: float,
        dt: float,
        perception,
        drone,
        gimbal,
        link,
        fused,
        inputs,
        mission,
        health,
        mode_status,
        raw_command: _IdleCommandSnapshot,
        shaped_command: _IdleCommandSnapshot,
        send_commands: bool,
    ) -> None:
        armed = bool(getattr(drone, "armed", False))
        if not self.blackbox.update_recording_state(armed=armed, now=now):
            return
        self.blackbox.record(
            now=now,
            dt=dt,
            perception=perception,
            drone=drone,
            gimbal=gimbal,
            link=link,
            fused=fused,
            inputs=inputs,
            mission=mission,
            health=health,
            mode_status=mode_status,
            raw_command=raw_command,
            shaped_command=shaped_command,
            send_commands=send_commands,
            debug=self._blackbox_debug_payload(
                raw_command=raw_command,
                shaped_command=shaped_command,
                send_commands=send_commands,
            ),
        )

    def _blackbox_debug_payload(
        self,
        *,
        raw_command: _IdleCommandSnapshot,
        shaped_command: _IdleCommandSnapshot,
        send_commands: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "commands": {
                "raw": asdict(raw_command),
                "shaped": asdict(shaped_command),
                "send_commands": bool(send_commands),
            }
        }
        runtime = getattr(self, "action_runtime", None)
        if runtime is None:
            return payload

        last_result = runtime.last_result or {}
        dispatcher = runtime.dispatcher
        action_name = runtime.action_name
        action_payload: dict[str, object] = {
            "name": action_name,
            "state": runtime.runner.state,
            "send_actions_requested": bool(runtime.send_actions_requested),
            "last_result": last_result,
            "last_dispatch": getattr(dispatcher, "last_dispatch", {}),
        }
        payload["action_lab"] = action_payload

        if action_name == "align_descend" or _result_name_is_align_descend(last_result):
            detail = last_result.get("detail") if isinstance(last_result, dict) else {}
            if not isinstance(detail, dict):
                detail = {}
            payload["align_descend"] = {
                "state": runtime.runner.state,
                "reason": last_result.get("reason", "") if isinstance(last_result, dict) else "",
                "done": bool(last_result.get("done", False)) if isinstance(last_result, dict) else False,
                "failed": bool(last_result.get("failed", False)) if isinstance(last_result, dict) else False,
                "detail": detail,
                "command": detail.get("command", {}),
                "last_dispatch": getattr(dispatcher, "last_dispatch", {}),
            }
        return payload

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
        return self.web_status_service.snapshot()

    def action_lab_context(self) -> dict[str, object]:
        with self.control_command_log_lock:
            snapshot = dict(self.latest_snapshot)
        return self.runtime_context_builder.build_action_context(snapshot)

    def field_heading_status(self) -> dict[str, object]:
        return self.web_status_service.field_heading_status()

    # ------------------------------------------------------------------
    # Field Reference API handlers (Phase 4C-1)
    # ------------------------------------------------------------------

    def field_reference_status(self) -> dict[str, object]:
        return self.field_reference_controller.status()

    def _drone_snapshot_raw(self) -> dict[str, object]:
        with self.control_command_log_lock:
            return dict(self.latest_snapshot).get("drone", {}) or {}

    def field_reference_mark_origin(self) -> dict[str, object]:
        return self.field_reference_controller.mark_origin()

    def field_reference_mark_forward(self) -> dict[str, object]:
        return self.field_reference_controller.mark_forward()

    def field_reference_use_current_yaw(self) -> dict[str, object]:
        return self.field_reference_controller.use_current_yaw()

    def field_reference_set_manual_heading(self, yaw_deg: float) -> dict[str, object]:
        return self.field_reference_controller.set_manual_heading(yaw_deg)

    def field_reference_confirm(self) -> dict[str, object]:
        return self.field_reference_controller.confirm()

    def field_reference_reset(self) -> dict[str, object]:
        return self.field_reference_controller.reset()

    def field_reference_freeze(self) -> dict[str, object]:
        return self.field_reference_controller.freeze()

    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Field Profile API handlers (Phase C-1)
    # ------------------------------------------------------------------

    _PROFILE_DIRS = [
        os.path.join(ROOT_DIR, "config", "field_profiles"),
        os.path.join(ROOT_DIR, "runtime", "field_profiles"),
    ]

    def field_profile_list(self) -> dict[str, object]:
        profiles = []
        for d in self._PROFILE_DIRS:
            source = "config" if "config" in d else "runtime"
            for path in FieldProfileService.list_profiles(d):
                pid = os.path.splitext(os.path.basename(path))[0]
                try:
                    p = FieldProfileService.load_profile(pid, profile_dir=d)
                    profiles.append({
                        "profile_id": p.profile_id,
                        "name": p.name,
                        "source": source,
                        "schema_version": p.schema_version,
                        "valid": True,
                        "errors": [],
                        "warnings": [],
                    })
                except Exception as exc:
                    profiles.append({
                        "profile_id": pid,
                        "name": pid,
                        "source": source,
                        "schema_version": None,
                        "valid": False,
                        "errors": [str(exc)],
                        "warnings": [],
                    })
        return {"ok": True, "profiles": profiles}

    def field_profile_get(self, profile_id: str) -> dict[str, object]:
        for d in self._PROFILE_DIRS:
            try:
                p = FieldProfileService.load_profile(profile_id, profile_dir=d)
                return {
                    "ok": True,
                    "profile_id": p.profile_id,
                    "name": p.name,
                    "schema_version": p.schema_version,
                    "created_at": p.created_at,
                    "points": {
                        k: {"name": pt.name, "role": pt.role,
                            "lat": pt.lat, "lon": pt.lon,
                            "field_x_m": pt.field_x_m, "field_y_m": pt.field_y_m}
                        for k, pt in p.points.items()
                    },
                    "gps_quality": {
                        "min_fix_type": p.gps_quality.min_fix_type,
                        "min_satellites": p.gps_quality.min_satellites,
                        "max_eph": p.gps_quality.max_eph,
                        "max_epv": p.gps_quality.max_epv,
                    },
                }
            except FileNotFoundError:
                continue
            except Exception as exc:
                return self._field_profile_error(profile_id, str(exc))
        return self._field_profile_error(
            profile_id, f"profile not found: {profile_id}"
        )

    def field_profile_validate(self, profile_id: str) -> dict[str, object]:
        for d in self._PROFILE_DIRS:
            try:
                p = FieldProfileService.load_profile(profile_id, profile_dir=d)
                diag = FieldProfileService.validate_profile(p)
                return {
                    "ok": diag.ok,
                    "profile_id": p.profile_id,
                    "errors": diag.errors,
                    "warnings": diag.warnings,
                }
            except FileNotFoundError:
                continue
            except Exception as exc:
                return self._field_profile_error(profile_id, str(exc))
        return self._field_profile_error(
            profile_id, f"profile not found: {profile_id}"
        )

    def field_profile_bind_current(self, profile_id: str) -> dict[str, object]:
        with self.action_runtime_lock:
            return self.field_reference_controller.bind_profile_current(profile_id)

    @staticmethod
    def _field_profile_error(profile_id: str, error: str) -> dict[str, object]:
        return {
            "ok": False,
            "error": error,
            "profile_id": profile_id,
            "errors": [error],
            "warnings": [],
            "diagnostics": {"errors": [error], "warnings": []},
        }

    def _with_field_coordinates(self, items: list[object]) -> list[object]:
        enriched: list[object] = []
        for item in items:
            if not isinstance(item, dict):
                enriched.append(item)
                continue
            copy = dict(item)
            converted = self.runtime_context_builder.local_to_field_xy(
                copy.get("local_x", copy.get("x")), copy.get("local_y", copy.get("y"))
            )
            if converted is not None:
                copy["field_x"], copy["field_y"] = converted
            enriched.append(copy)
        return enriched

    def confirm_field_heading_manual(self) -> CommandResult:
        reference = self.field_reference_service.reference
        if reference.is_frozen:
            return CommandResult(
                False,
                "FieldReference is frozen; use /api/field-reference/reset to unfreeze before confirming via legacy API",
            )
        if reference.is_confirmed or reference.is_ready():
            return CommandResult(
                False,
                "FieldReference is already confirmed; reset it before confirming via legacy API",
            )
        with self.control_command_log_lock:
            snapshot = dict(self.latest_snapshot)
        drone = snapshot.get("drone", {})
        if not isinstance(drone, dict):
            return CommandResult(False, "drone state unavailable")
        if not bool(drone.get("attitude_valid", False)):
            return CommandResult(False, "attitude yaw not valid")
        yaw = RuntimeContextBuilder._float_or_none(drone.get("yaw"))
        if yaw is None:
            return CommandResult(False, "attitude yaw not valid")
        ok = self.protected_confirm_field_heading(
            yaw_rad=yaw,
            drone=drone,
            source="manual_web",
        )
        if not ok:
            return CommandResult(False, "无法确认原点：当前 LOCAL_NED 位置无效")
        status = self.field_heading_status()
        yaw_deg = status.get("field_heading_yaw_deg")
        origin_x = status.get("origin_local_x")
        origin_y = status.get("origin_local_y")
        origin_z = status.get("origin_local_z")
        message = (
            (
                f"field heading/origin confirmed yaw={yaw_deg:.1f} deg "
                f"origin=({origin_x:.2f},{origin_y:.2f},{origin_z:.2f})"
            )
            if yaw_deg is not None
            and origin_x is not None
            and origin_y is not None
            and origin_z is not None
            else "field heading/origin confirmed"
        )
        if bool(drone.get("armed", False)):
            message = f"{message}; vehicle is armed, confirm on ground before flight when possible"
        self._record_event("OK", message)
        return CommandResult(True, message)

    def protected_confirm_field_heading(
        self,
        yaw_rad: float | None = None,
        *,
        drone: dict[str, object] | None = None,
        source: str = "takeoff_auto",
    ) -> bool:
        """Guard the legacy runtime-context field-heading write path.

        A confirmed or frozen FieldReference is authoritative.  Takeoff's
        compatibility auto-confirm action succeeds as a no-op in that case,
        so it cannot overwrite a profile binding or fail an otherwise valid
        mission start.
        """
        reference = self.field_reference_service.reference
        if reference.is_frozen or reference.is_confirmed or reference.is_ready():
            self.logger.info(
                "field heading confirm skipped: existing FieldReference "
                "confirmed=%s ready=%s frozen=%s source=%s",
                reference.is_confirmed,
                reference.is_ready(),
                reference.is_frozen,
                source,
            )
            return True
        return self.runtime_context_builder.confirm_field_heading(
            yaw_rad=yaw_rad,
            drone=drone,
            source=source,
        )

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
            self._maybe_save_recon_inspection_result()
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
            "objects": self._with_field_coordinates(localized),
            "object_count": detail.get("object_count", len(localized)),
            "raw_estimates_count": detail.get("raw_estimates_count", 0),
            "captures_count": detail.get("captures_count", 0),
        }

    def clear_localization_result(self) -> CommandResult:
        self.latest_localization_result = {}
        result = CommandResult(True, "localized object coordinates cleared")
        self._record_event("OK", result.message)
        return result

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
            "selected_targets": self._with_field_coordinates(selected),
            "selected_count": detail.get("selected_count", len(selected)),
            "candidate_count": detail.get("candidate_count", 0),
        }

    def _maybe_save_recon_inspection_result(self) -> None:
        name = getattr(self.action_runtime, "action_name", None)
        if name not in ("recon_inspect_target", "build_recon_report"):
            return
        last = getattr(self.action_runtime, "last_result", None)
        if last is None:
            return
        detail = last.get("detail") if isinstance(last, dict) else getattr(last, "detail", None)
        if not isinstance(detail, dict):
            detail = {}
        done = last.get("done") if isinstance(last, dict) else getattr(last, "done", False)
        if not done:
            return

        # new path: build_recon_report output
        if name == "build_recon_report":
            recon_report = detail.get("recon_report", {})
            barrels = recon_report.get("barrels", []) if isinstance(recon_report, dict) else []
            self.latest_recon_inspection_result = {
                "source": "build_recon_report", "updated_at": time.time(),
                "barrels": self._with_field_coordinates(barrels),
                "barrel_count": detail.get("barrel_count", len(barrels)),
                "detected_count": detail.get("detected_count", 0),
                "blank_count": detail.get("blank_count", 0),
                "skipped_count": detail.get("skipped_count", 0),
                "report": self._with_field_coordinates(barrels),
                "inspected_count": len(barrels),
                "detected_sign_count": detail.get("detected_count", 0),
                "no_sign_count": detail.get("blank_count", 0),
                "failed_count": detail.get("skipped_count", 0),
            }
            return

        # old path: recon_inspect_target output (unchanged)
        target_index = detail.get("target_index")
        if not isinstance(target_index, int):
            return
        existing = self.latest_recon_inspection_result.get("report", [])
        by_index = {item.get("target_index"): item for item in existing if isinstance(item, dict)}
        by_index[target_index] = detail
        report = [by_index[index] for index in sorted(by_index) if isinstance(index, int)]
        detected = sum(item.get("status") == "detected" for item in report)
        no_sign = sum(item.get("status") == "no_sign" for item in report)
        failed = sum(item.get("status") in {"goto_failed", "lock_failed", "align_failed"} for item in report)
        self.latest_recon_inspection_result = {
            "source": "recon_inspect_target", "updated_at": time.time(),
            "report": self._with_field_coordinates(report),
            "inspected_count": len(report), "detected_sign_count": detected,
            "no_sign_count": no_sign, "failed_count": failed,
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
        except (KeyError, ValueError):
            return CommandResult(False, "current local position unavailable")
        yaw = self.runtime_context_builder.arm_heading_yaw_rad
        if yaw is None:
            if not bool(drone.get("attitude_valid", False)):
                return CommandResult(False, "arm heading yaw unavailable and current attitude is invalid")
            try:
                yaw = float(drone["yaw"])
            except (KeyError, ValueError):
                return CommandResult(False, "current yaw unavailable")
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

    def camera_recording_status(self) -> dict[str, object]:
        return self.command_pipeline.camera_recording_status()

    def camera_recording_toggle(self) -> CommandResult:
        return self.command_pipeline.camera_recording_toggle()

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
            self.latest_recon_inspection_result = {}
            if self._action_mission_uses_field_coordinates():
                reason = self._field_mission_preflight_reason()
                if reason is not None:
                    return self._reject_action_mission_start(reason)
                freeze_result = self.field_reference_service.freeze()
                if not bool(freeze_result.get("ok", False)):
                    return self._reject_action_mission_start(
                        "field_reference_freeze_failed",
                        error=str(freeze_result.get("error") or "freeze failed"),
                    )
            self.action_mission_orchestrator.start(
                link_manager=self.services.link_manager,
            )
            return self.action_mission_status_payload()

    def _action_mission_uses_field_coordinates(self) -> bool:
        orchestrator = self.action_mission_orchestrator
        if orchestrator is None:
            return False
        return any(
            str(step.params.get("waypoint_mode", "")).strip().lower() == "field"
            for step in orchestrator.steps
        )

    def _field_mission_preflight_reason(self) -> str | None:
        reference = self.field_reference_service.reference
        if not reference.is_confirmed:
            return "field_reference_not_confirmed"
        if not reference.is_ready():
            return "field_reference_not_ready"

        builder = self.runtime_context_builder
        if not builder.field_heading_confirmed or not builder.field_origin_confirmed:
            return "field_reference_not_synced"

        pairs = (
            (builder.field_heading_yaw_rad, reference.field_heading_yaw_rad),
            (builder.field_origin_local_x, reference.origin_local_n_m),
            (builder.field_origin_local_y, reference.origin_local_e_m),
        )
        for runtime_value, reference_value in pairs:
            runtime_float = RuntimeContextBuilder._float_or_none(runtime_value)
            reference_float = RuntimeContextBuilder._float_or_none(reference_value)
            if runtime_float is None or reference_float is None or not math.isclose(
                runtime_float,
                reference_float,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                return "field_reference_not_synced"

        if reference.origin_local_z_m is not None:
            runtime_z = RuntimeContextBuilder._float_or_none(builder.field_origin_local_z)
            reference_z = RuntimeContextBuilder._float_or_none(reference.origin_local_z_m)
            if runtime_z is None or reference_z is None or not math.isclose(
                runtime_z,
                reference_z,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                return "field_reference_not_synced"
        return None

    def _reject_action_mission_start(
        self,
        reason: str,
        *,
        error: str | None = None,
    ) -> dict[str, object]:
        orchestrator = self.action_mission_orchestrator
        if orchestrator is not None:
            orchestrator.running = False
            orchestrator.done = False
            orchestrator.failed = True
            orchestrator.reason = reason
            orchestrator.detail = {"error": error} if error else {}
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
            self.latest_recon_inspection_result = {}
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
            self._maybe_save_recon_inspection_result()
            return self.action_mission_status_payload()

    def action_mission_skip_current(self) -> dict[str, object]:
        if self.action_mission_orchestrator is None:
            return self.action_mission_status_payload()
        with self.action_runtime_lock:
            self.action_mission_orchestrator.skip_current_step(
                link_manager=self.services.link_manager,
                hold_current=True,
                reason="manual_web_skip",
            )
            self._record_event("WARN", "action mission current step skipped manually")
            return self.action_mission_status_payload()

    def web_execute_command(self, command: str) -> CommandResult:
        stripped = command.strip()
        if not stripped:
            return CommandResult(False, "empty command")
        if stripped.startswith("switch_source "):
            self.disable_automatic_sending("source_switch")
        manager = self.services.link_manager
        if manager is None:
            if stripped.startswith("target "):
                return self.command_pipeline.execute_yolo_command(stripped)
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
        return self.command_pipeline.execute_yolo_command(command)

    # ------------------------------------------------------------------
    # action lab dispatch helpers
    # ------------------------------------------------------------------

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

    def web_missions(self) -> list[dict[str, object]]:
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

    def _web_stage_modes_for_mission(self, mission_name: str) -> list[str]:
        if self.web_status_service is None:
            return ["NO_MISSION"]
        return self.web_status_service.web_stage_modes_for_mission(mission_name)

    def apply_active_mission_config(self, relative_path: str) -> CommandResult:
        del relative_path
        return CommandResult(True, "legacy mission runtime disabled; configuration saved only")

    def reconnect_telemetry_from_saved_config(self) -> CommandResult:
        try:
            config = load_telemetry_config(str(ROOT_DIR / "config" / "telemetry.yaml"))
        except Exception as exc:
            return CommandResult(False, f"telemetry configuration invalid: {exc}")
        self.disable_automatic_sending("telemetry_reconnect")
        self.services.reconnect_telemetry(config)
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
        return self.command_pipeline.restart_external_service(service, command)

    def _stop_external_processes(self) -> None:
        self.command_pipeline.stop_all_external_processes()

    def _stop_external_process(self, service: str) -> None:
        self.command_pipeline.stop_external_process(service)

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
        del mode_name
        return CommandResult(False, "legacy mission stages disabled; stage override unavailable")

    def _handle_mission_command(self, parts: list[str]) -> CommandResult:
        del parts
        return CommandResult(False, "legacy mission runtime disabled; use Action Mission")

    def _reset_mission_runtime(self, *, clear_for_safety: bool) -> None:
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

    def _reload_mission_stage_config(self) -> CommandResult:
        return CommandResult(False, "legacy mission stages disabled; config reload unavailable")

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


def _result_name_is_align_descend(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    reason = str(result.get("reason", ""))
    if reason.startswith("align_") or reason in {
        "aligning",
        "align_descending",
        "descending",
        "descending_slow",
        "min_altitude_reached",
        "finish_altitude_reached",
    }:
        return True
    detail = result.get("detail")
    return isinstance(detail, dict) and "ex_cam" in detail and "ey_cam" in detail and "height_m" in detail
