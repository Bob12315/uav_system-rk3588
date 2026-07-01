from __future__ import annotations

import subprocess
from typing import Any

from app.yolo_command_client import YoloCommandClient


class CommandPipeline:
    """Low-risk command handlers extracted from SystemRunner (SR-3a).

    Handles camera recording, YOLO target commands, and external
    process management.  Does NOT send MAVLink or modify flight state.
    """

    def __init__(
        self,
        yolo_command_config: Any,
        camera_recording: dict[str, object],
        external_processes: dict[str, subprocess.Popen],
        record_event: Any,
    ) -> None:
        self._yolo_cfg = yolo_command_config
        self._camera_recording = camera_recording
        self._external_processes = external_processes
        self._record_event = record_event

    # ------------------------------------------------------------------
    # camera
    # ------------------------------------------------------------------

    def camera_recording_status(self) -> dict[str, object]:
        return dict(self._camera_recording)

    def camera_recording_toggle(self) -> Any:
        from telemetry_link.command_dispatcher import CommandResult

        recording = bool(self._camera_recording.get("recording"))
        client = YoloCommandClient(self._yolo_cfg)
        try:
            if recording:
                client.stop_recording()
                self._camera_recording.update({
                    "recording": False,
                    "message": "录制停止请求已发送",
                })
                message = "camera recording stop sent"
            else:
                client.start_recording()
                self._camera_recording.clear()
                self._camera_recording.update({
                    "recording": True,
                    "path": "~/uav_recordings/camera_*.mp4",
                    "message": "录制开始请求已发送",
                })
                message = "camera recording start sent"
        except Exception as exc:
            message = f"camera recording command failed: {exc}"
            self._camera_recording.update({"message": message})
            result = CommandResult(False, message)
            self._record_event("ERROR", result.message)
            return result
        result = CommandResult(True, message)
        self._record_event("OK", result.message)
        return result

    # ------------------------------------------------------------------
    # yolo target commands
    # ------------------------------------------------------------------

    def execute_yolo_command(self, command: str) -> Any:
        from telemetry_link.command_dispatcher import CommandResult

        parts = command.split()
        client = YoloCommandClient(self._yolo_cfg)
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
                return CommandResult(
                    False, "format: target <next|prev|lock <track_id>|unlock>"
                )
        except Exception as exc:
            return CommandResult(False, f"target command failed: {exc}")
        result = CommandResult(True, f"{command} sent")
        self._record_event("OK", result.message)
        return result

    # ------------------------------------------------------------------
    # external process management
    # ------------------------------------------------------------------

    def restart_external_service(self, service: str, command: list[str]) -> Any:
        from telemetry_link.command_dispatcher import CommandResult

        if not command:
            return CommandResult(False, f"{service} restart command is not configured")
        if service == "app":
            self._record_event("WARN", "app restart requested; process will exit")
        self._stop_external_process(service)
        self._external_processes[service] = subprocess.Popen(
            command,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid = self._external_processes[service].pid
        self._record_event("OK", f"{service} restarted pid={pid}")
        return CommandResult(True, f"{service} restarted; pid={pid}")

    def _stop_external_process(self, service: str) -> None:
        import os
        import signal
        import time

        proc = self._external_processes.pop(service, None)
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    def stop_external_process(self, service: str) -> None:
        """Public wrapper to stop a single service."""
        self._stop_external_process(service)

    def stop_all_external_processes(self) -> None:
        for service in list(self._external_processes):
            self._stop_external_process(service)
