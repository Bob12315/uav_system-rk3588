from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.app_config import BlackboxConfig
from missions.common.control.types import FlightCommand
from fusion.models import FusedState, PerceptionTarget
from telemetry_link.models import DroneState, GimbalState, LinkStatus


class BlackboxRecorder:
    def __init__(self, config: BlackboxConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.enabled = bool(config.enabled)
        self.output_dir = Path(config.output_dir).expanduser()
        self.sample_interval_sec = 0.0 if config.sample_hz <= 0 else 1.0 / config.sample_hz
        self.rotate_bytes = int(max(config.rotate_mb, 0.0) * 1024 * 1024)
        self._handle = None
        self._path: Path | None = None
        self._seq = 0
        self._writes_since_flush = 0
        self._last_record_time = 0.0
        self._last_mode: str | None = None
        self._last_target_valid: bool | None = None
        self._last_send_commands: bool | None = None

    @property
    def path(self) -> Path | None:
        return self._path

    def start(self) -> None:
        if not self.enabled:
            return
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._open_new_file()
            self._write_meta()
            self._prune_old_files()
        except OSError as exc:
            self.enabled = False
            self.logger.warning("blackbox disabled because it cannot start: %s", exc)

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.flush()
            self._handle.close()
        finally:
            self._handle = None

    def record(
        self,
        *,
        now: float,
        dt: float,
        perception: PerceptionTarget,
        drone: DroneState,
        gimbal: GimbalState,
        link: LinkStatus | None,
        fused: FusedState,
        inputs,
        mission,
        health,
        mode_status,
        raw_command: FlightCommand,
        shaped_command: FlightCommand,
        send_commands: bool,
    ) -> None:
        if not self.enabled:
            return
        if self._handle is None:
            self.start()
            if self._handle is None:
                return
        if self.sample_interval_sec > 0 and (now - self._last_record_time) < self.sample_interval_sec:
            return

        events = self._events(mission.active_mode, perception.target_valid, send_commands)
        payload: dict[str, Any] = {
            "t": now,
            "dt": dt,
            "seq": self._seq,
            "runtime": {
                "mode": getattr(mode_status, "mode_name", ""),
                "mission": mission.active_mode,
                "health": health.hold_reason,
                "hold_reason": getattr(mode_status, "hold_reason", "") or mission.hold_reason,
                "send_commands": send_commands,
                "enable_gimbal": shaped_command.enable_gimbal,
                "enable_body": shaped_command.enable_body,
                "enable_approach": shaped_command.enable_approach,
                "control_allowed": inputs.control_allowed,
                "target_valid": inputs.target_valid,
            },
        }
        if self.config.include_perception:
            payload["perception"] = self._dataclass_dict(perception)
        if self.config.include_drone:
            payload["drone"] = self._dataclass_dict(drone)
            if link is not None:
                payload["link"] = self._dataclass_dict(link)
        if self.config.include_gimbal:
            payload["gimbal"] = self._dataclass_dict(gimbal)
        if self.config.include_fused:
            payload["fused"] = self._dataclass_dict(fused)
            payload["inputs"] = self._object_dict(inputs)
        if self.config.include_commands:
            payload["command_raw"] = self._command_dict(raw_command)
            payload["command_shaped"] = self._command_dict(shaped_command)
        if self.config.include_events:
            payload["events"] = events

        self._write(payload, now)

    def _open_new_file(self) -> None:
        self.close()
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        index = 1
        while True:
            path = self.output_dir / f"{stamp}_run{index:03d}.jsonl"
            if not path.exists():
                break
            index += 1
        self._path = path
        self._handle = path.open("a", encoding="utf-8")
        self.logger.info("blackbox recording to %s", path)

    def _write_meta(self) -> None:
        if self._path is None:
            return
        meta_path = self._path.with_suffix(".meta.json")
        meta = {
            "created_at": time.time(),
            "format": "uav_project.blackbox.v1",
            "data_file": self._path.name,
            "sample_hz": self.config.sample_hz,
            "fields": {
                "perception": self.config.include_perception,
                "drone": self.config.include_drone,
                "gimbal": self.config.include_gimbal,
                "fused": self.config.include_fused,
                "commands": self.config.include_commands,
                "events": self.config.include_events,
            },
        }
        meta_path.write_text(json.dumps(self._clean(meta), ensure_ascii=False, indent=2), encoding="utf-8")

    def _write(self, payload: dict[str, Any], now: float) -> None:
        assert self._handle is not None
        try:
            self._handle.write(json.dumps(self._clean(payload), ensure_ascii=False, separators=(",", ":")) + "\n")
            self._seq += 1
            self._last_record_time = now
            self._writes_since_flush += 1
            if self._writes_since_flush >= self.config.flush_every:
                self._handle.flush()
                self._writes_since_flush = 0
            if self.rotate_bytes > 0 and self._path is not None and self._path.stat().st_size >= self.rotate_bytes:
                self._open_new_file()
                self._write_meta()
                self._prune_old_files()
        except OSError as exc:
            self.enabled = False
            self.logger.warning("blackbox disabled after write failure: %s", exc)

    def _events(self, mode: str, target_valid: bool, send_commands: bool) -> list[str]:
        events: list[str] = []
        if self._last_mode is not None and self._last_mode != mode:
            events.append(f"mode_switch:{self._last_mode}->{mode}")
        if self._last_target_valid is not None and self._last_target_valid != target_valid:
            events.append("target_acquired" if target_valid else "target_lost")
        if self._last_send_commands is not None and self._last_send_commands != send_commands:
            events.append(f"send_commands:{int(self._last_send_commands)}->{int(send_commands)}")
        self._last_mode = mode
        self._last_target_valid = target_valid
        self._last_send_commands = send_commands
        return events

    def _prune_old_files(self) -> None:
        if self.config.keep_files <= 0:
            return
        files = sorted(self.output_dir.glob("*_run*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        for old_path in files[self.config.keep_files :]:
            try:
                old_path.unlink()
                meta_path = old_path.with_suffix(".meta.json")
                if meta_path.exists():
                    meta_path.unlink()
            except OSError as exc:
                self.logger.debug("failed to prune old blackbox file %s: %s", old_path, exc)

    @staticmethod
    def _command_dict(command: FlightCommand) -> dict[str, Any]:
        return {
            "vx": command.vx_cmd,
            "vy": command.vy_cmd,
            "vz": command.vz_cmd,
            "yaw_rate": command.yaw_rate_cmd,
            "gimbal_yaw_rate": command.gimbal_yaw_rate_cmd,
            "gimbal_pitch_rate": command.gimbal_pitch_rate_cmd,
            "gimbal_yaw_angle": command.gimbal_yaw_angle_cmd,
            "gimbal_pitch_angle": command.gimbal_pitch_angle_cmd,
            "enable_body": command.enable_body,
            "enable_gimbal": command.enable_gimbal,
            "enable_gimbal_angle": command.enable_gimbal_angle,
            "enable_approach": command.enable_approach,
            "active": command.active,
            "valid": command.valid,
        }

    @staticmethod
    def _dataclass_dict(value: Any) -> dict[str, Any]:
        if is_dataclass(value):
            return asdict(value)
        return {}

    @staticmethod
    def _object_dict(value: Any) -> dict[str, Any]:
        if is_dataclass(value):
            return asdict(value)
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }

    @classmethod
    def _clean(cls, value: Any) -> Any:
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(key): cls._clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._clean(item) for item in value]
        return value
