from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Callable

from application.send_state import SystemSendState
from application.yolo_command_client import YoloCommandClient
from contracts.action import OperationResult


class SystemControlService:
    """Administrative controls with mandatory authorization revocation and queue cleanup."""

    def __init__(
        self, *, send_state: SystemSendState, get_link: Callable[[], Any],
        action_runtime: Any, yolo_command_config: Any,
        restart_commands: dict[str, list[str]], record_event: Callable[[str, str], None],
        reconnect_telemetry: Callable[[], Any] | None = None,
        video_dir: str | Path = "runtime/videos",
    ) -> None:
        self.send_state = send_state
        self._get_link = get_link
        self._runtime = action_runtime
        self._yolo_cfg = yolo_command_config
        self._restart_commands = restart_commands
        self._record_event = record_event
        self._reconnect_telemetry = reconnect_telemetry
        self._video_dir = Path(video_dir)
        self._recording = {"recording": False, "path": "", "message": "未录制"}
        self._processes: dict[str, subprocess.Popen] = {}

    def _revoke_and_clear(self, reason: str) -> None:
        self._runtime.dispatcher.clear_authorization(reason)
        self._runtime.dispatcher.safety_pipeline.stop_continuous(reason)
        self._runtime.clear_navigation_queue(self._get_link())

    def set_send(self, enabled: bool) -> OperationResult:
        snapshot = self.send_state.set_send_commands(bool(enabled))
        if not snapshot.send_commands:
            self._revoke_and_clear("system_send_disabled")
        message = f"system SEND={'ON' if snapshot.send_commands else 'OFF'}"
        self._record_event("SAFETY", message)
        return OperationResult(True, message)

    def disable_send(self, reason: str) -> None:
        self.send_state.set_send_commands(False)
        self._revoke_and_clear(reason)
        self._record_event("SAFETY", f"automatic command sending disabled: {reason}")

    def switch_source(self, source: str) -> OperationResult:
        manager = self._get_link()
        if manager is None:
            return OperationResult(False, "telemetry is not connected")
        self.disable_send("source_switch")
        if not manager.switch_active_source(source):
            return OperationResult(False, f"source switch rejected: {source}")
        return OperationResult(True, f"active telemetry source={source}; SEND remains OFF")

    def active_source(self, default: str = "real") -> str:
        manager = self._get_link()
        getter = getattr(manager, "get_active_source", None)
        return str(getter()) if callable(getter) else str(default)

    def reconnect(self) -> OperationResult:
        self.disable_send("telemetry_reconnect")
        if not callable(self._reconnect_telemetry):
            return OperationResult(False, "telemetry reconnect is unavailable")
        self._reconnect_telemetry()
        return OperationResult(True, "telemetry reconnect requested; SEND remains OFF")

    def target_command(self, command: str) -> OperationResult:
        parts = command.split()
        client = YoloCommandClient(self._yolo_cfg)
        try:
            if len(parts) == 3 and parts[1] == "lock": client.lock_target(int(parts[2]))
            elif len(parts) >= 2 and parts[1] == "unlock": client.unlock_target()
            elif len(parts) >= 2 and parts[1] == "next": client.send("switch_next")
            elif len(parts) >= 2 and parts[1] in {"prev", "previous"}: client.send("switch_prev")
            else: return OperationResult(False, "format: target <next|prev|lock <track_id>|unlock>")
        except Exception as exc:
            return OperationResult(False, f"target command failed: {exc}")
        result = OperationResult(True, f"{command} sent")
        self._record_event("OK", result.message)
        return result

    def recording_status(self) -> dict[str, object]:
        return dict(self._recording)

    def recording_start(self, *, trigger: str = "system") -> OperationResult:
        self._video_dir.mkdir(parents=True, exist_ok=True)
        try:
            YoloCommandClient(self._yolo_cfg).start_recording()
        except Exception as exc:
            result = OperationResult(False, f"camera recording command failed: {exc}")
            self._record_event("ERROR", result.message)
            return result
        self._recording.update({"recording": True, "path": str(self._video_dir / "camera_*.mp4"),
                                "message": "录制开始请求已发送", "trigger": trigger})
        result = OperationResult(True, f"camera recording start sent trigger={trigger}")
        self._record_event("OK", result.message)
        return result

    def recording_stop(self, *, trigger: str = "system") -> OperationResult:
        try:
            YoloCommandClient(self._yolo_cfg).stop_recording()
        except Exception as exc:
            result = OperationResult(False, f"camera recording command failed: {exc}")
            self._record_event("ERROR", result.message)
            return result
        self._recording.update({"recording": False, "message": "录制停止请求已发送", "trigger": trigger})
        result = OperationResult(True, f"camera recording stop sent trigger={trigger}")
        self._record_event("OK", result.message)
        return result

    def recording_toggle(self) -> OperationResult:
        return self.recording_stop(trigger="manual") if self._recording["recording"] else self.recording_start(trigger="manual")

    def restart_service(self, service: str) -> OperationResult:
        command = list(self._restart_commands.get(service, []))
        if not command:
            return OperationResult(False, f"{service} restart command is not configured")
        self.disable_send(f"{service}_restart")
        self._stop_process(service)
        process = subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._processes[service] = process
        return OperationResult(True, f"{service} restarted; pid={process.pid}; SEND remains OFF")

    def _stop_process(self, service: str) -> None:
        process = self._processes.pop(service, None)
        if process is None: return
        try: os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError): pass
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError): pass

    def stop(self) -> None:
        for service in list(self._processes): self._stop_process(service)
