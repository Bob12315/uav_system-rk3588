from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from math import degrees
from typing import Any, Protocol

from missions.common.control.types import FlightCommand

try:
    from telemetry_link.models import ControlCommand, ControlType
except Exception:  # pragma: no cover - keeps executor importable under partial envs
    ControlCommand = None
    ControlType = None


class TelemetryLinkLike(Protocol):
    def submit_control_command(self, command: Any) -> None:
        ...

    def stop_control(self, frame: int = 1) -> None:
        ...

    def send_gimbal_rate(self, yaw_rate: float, pitch_rate: float) -> None:
        ...

    def send_gimbal_angle(self, pitch: float, yaw: float, roll: float = 0.0) -> None:
        ...


@dataclass(slots=True)
class FlightCommandExecutorConfig:
    body_frame: int = 1
    gimbal_roll_deg: float = 0.0
    log_commands: bool = True
    send_commands: bool = True


@dataclass(slots=True)
class FlightCommandExecutor:
    telemetry_link: Any | None = None
    config: FlightCommandExecutorConfig = field(default_factory=FlightCommandExecutorConfig)
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("missions.common.control.executor")
    )
    _last_body_command: FlightCommand | None = field(init=False, default=None)
    _last_gimbal_command: FlightCommand | None = field(init=False, default=None)
    _last_exception: Exception | None = field(init=False, default=None)
    _last_gimbal_rate_command_at: float | None = field(init=False, default=None)

    def set_telemetry_link(self, telemetry_link: Any | None) -> None:
        self.telemetry_link = telemetry_link

    def update_transport(self, telemetry_link: Any | None) -> None:
        self.set_telemetry_link(telemetry_link)

    def reset(self) -> None:
        self._last_body_command = None
        self._last_gimbal_command = None
        self._last_exception = None
        self._last_gimbal_rate_command_at = None
        if not self.config.send_commands:
            self.logger.info("skip reset command send because executor.send_commands=false")
            return
        self._send_zero_body()
        self._send_zero_gimbal()

    def execute(self, cmd: FlightCommand | None) -> None:
        if cmd is None:
            return
        if not bool(getattr(cmd, "valid", False)):
            self.logger.debug("skip execute because flight command is invalid")
            return
        if not self.config.send_commands:
            if self.config.log_commands:
                self.logger.info(
                    "dry-run flight command vx=%.3f vy=%.3f vz=%.3f yaw_rate=%.3f "
                    "gimbal_rate=(%.3f,%.3f) gimbal_angle=(%s,%s) "
                    "enable=(gimbal:%s gimbal_angle:%s body:%s approach:%s) active=%s",
                    self._finite_or_zero(getattr(cmd, "vx_cmd", 0.0)),
                    self._finite_or_zero(getattr(cmd, "vy_cmd", 0.0)),
                    self._finite_or_zero(getattr(cmd, "vz_cmd", 0.0)),
                    self._finite_or_zero(getattr(cmd, "yaw_rate_cmd", 0.0)),
                    self._finite_or_zero(getattr(cmd, "gimbal_yaw_rate_cmd", 0.0)),
                    self._finite_or_zero(getattr(cmd, "gimbal_pitch_rate_cmd", 0.0)),
                    self._format_optional_angle(getattr(cmd, "gimbal_yaw_angle_cmd", None)),
                    self._format_optional_angle(getattr(cmd, "gimbal_pitch_angle_cmd", None)),
                    bool(getattr(cmd, "enable_gimbal", False)),
                    bool(getattr(cmd, "enable_gimbal_angle", False)),
                    bool(getattr(cmd, "enable_body", False)),
                    bool(getattr(cmd, "enable_approach", False)),
                    bool(getattr(cmd, "active", False)),
                )
            return
        if self.telemetry_link is None:
            self.logger.warning("skip execute because telemetry_link is not set")
            return

        try:
            self._execute_gimbal_angle(cmd)
            self._execute_body(cmd)
            self._execute_gimbal(cmd)
            self._last_exception = None
        except Exception as exc:
            self._last_exception = exc
            self.logger.exception("flight command execution failed: %s", exc)

    def _execute_body(self, cmd: FlightCommand) -> None:
        if not self._can_execute_body(cmd):
            return

        vx_cmd = self._finite_or_zero(getattr(cmd, "vx_cmd", 0.0))
        vy_cmd = self._finite_or_zero(getattr(cmd, "vy_cmd", 0.0))
        vz_cmd = self._finite_or_zero(getattr(cmd, "vz_cmd", 0.0))
        yaw_rate_cmd = self._finite_or_zero(getattr(cmd, "yaw_rate_cmd", 0.0))

        if hasattr(self.telemetry_link, "submit_control_command"):
            self._submit_body_control(
                vx_cmd=vx_cmd,
                vy_cmd=vy_cmd,
                vz_cmd=vz_cmd,
                yaw_rate_cmd=yaw_rate_cmd,
            )
        elif hasattr(self.telemetry_link, "send_velocity_command"):
            self.telemetry_link.send_velocity_command(
                vx=vx_cmd,
                vy=vy_cmd,
                vz=vz_cmd,
                frame=self.config.body_frame,
            )
            if not math.isclose(yaw_rate_cmd, 0.0, abs_tol=1e-9):
                self.logger.warning(
                    "body yaw_rate_cmd=%.3f not sent because telemetry_link has no unified body control interface",
                    yaw_rate_cmd,
                )
        else:
            raise AttributeError(
                "telemetry_link missing body control send interface: "
                "expected submit_control_command(...) or send_velocity_command(...)"
            )

        self._last_body_command = cmd
        if self.config.log_commands:
            self.logger.debug(
                "executed body command vx=%.3f vy=%.3f vz=%.3f yaw_rate=%.3f "
                "enable_body=%s enable_approach=%s active=%s",
                vx_cmd,
                vy_cmd,
                vz_cmd,
                yaw_rate_cmd,
                bool(getattr(cmd, "enable_body", False)),
                bool(getattr(cmd, "enable_approach", False)),
                bool(getattr(cmd, "active", False)),
            )

    def _execute_gimbal(self, cmd: FlightCommand) -> None:
        if not self._can_execute_gimbal(cmd):
            if self._last_gimbal_command is not None:
                self._send_zero_gimbal()
                self._last_gimbal_command = None
            return

        yaw_rate_cmd = self._finite_or_zero(getattr(cmd, "gimbal_yaw_rate_cmd", 0.0))
        pitch_rate_cmd = self._finite_or_zero(getattr(cmd, "gimbal_pitch_rate_cmd", 0.0))
        rate_sender = getattr(self.telemetry_link, "send_gimbal_rate", None)
        if callable(rate_sender):
            rate_sender(yaw_rate=yaw_rate_cmd, pitch_rate=pitch_rate_cmd)
            self._last_gimbal_rate_command_at = time.time()
            self._last_gimbal_command = cmd
            if self.config.log_commands:
                self.logger.debug(
                    "executed gimbal rate command yaw_rate=%.3f rad/s pitch_rate=%.3f rad/s (%.2f deg/s, %.2f deg/s)",
                    yaw_rate_cmd,
                    pitch_rate_cmd,
                    degrees(yaw_rate_cmd),
                    degrees(pitch_rate_cmd),
                )
            return
        self.logger.warning(
            "skip gimbal rate command because telemetry_link has no send_gimbal_rate(...) interface "
            "yaw_rate=%.3f pitch_rate=%.3f",
            yaw_rate_cmd,
            pitch_rate_cmd,
        )

    def _execute_gimbal_angle(self, cmd: FlightCommand) -> None:
        if not bool(getattr(cmd, "enable_gimbal_angle", False)):
            return
        if self.telemetry_link is None:
            return

        angle_sender = getattr(self.telemetry_link, "send_gimbal_angle", None)
        if not callable(angle_sender):
            self.logger.warning(
                "skip gimbal angle command because telemetry_link has no send_gimbal_angle(...) interface"
            )
            return

        yaw_angle = self._optional_finite(getattr(cmd, "gimbal_yaw_angle_cmd", None))
        pitch_angle = self._optional_finite(getattr(cmd, "gimbal_pitch_angle_cmd", None))
        if yaw_angle is None or pitch_angle is None:
            self.logger.warning(
                "skip gimbal angle command because yaw/pitch target is invalid yaw=%s pitch=%s",
                yaw_angle,
                pitch_angle,
            )
            return

        angle_sender(
            pitch=degrees(pitch_angle),
            yaw=degrees(yaw_angle),
            roll=self.config.gimbal_roll_deg,
        )
        if self.config.log_commands:
            self.logger.debug(
                "executed gimbal angle command yaw=%.3f rad pitch=%.3f rad (%.2f deg, %.2f deg)",
                yaw_angle,
                pitch_angle,
                degrees(yaw_angle),
                degrees(pitch_angle),
            )

    def _can_execute_body(self, cmd: FlightCommand) -> bool:
        if self.telemetry_link is None:
            return False
        if bool(getattr(cmd, "enable_body", False) or getattr(cmd, "enable_approach", False)):
            return True
        if not any(
            not math.isclose(self._finite_or_zero(value), 0.0, abs_tol=1e-9)
            for value in (
                getattr(cmd, "vx_cmd", 0.0),
                getattr(cmd, "vy_cmd", 0.0),
                getattr(cmd, "vz_cmd", 0.0),
                getattr(cmd, "yaw_rate_cmd", 0.0),
            )
        ):
            return False
        return True

    def _can_execute_gimbal(self, cmd: FlightCommand) -> bool:
        if self.telemetry_link is None:
            return False
        if bool(getattr(cmd, "enable_gimbal", False)):
            return True
        if not any(
            not math.isclose(self._finite_or_zero(value), 0.0, abs_tol=1e-9)
            for value in (
                getattr(cmd, "gimbal_yaw_rate_cmd", 0.0),
                getattr(cmd, "gimbal_pitch_rate_cmd", 0.0),
            )
        ):
            return False
        return True

    def _submit_body_control(
        self,
        *,
        vx_cmd: float,
        vy_cmd: float,
        vz_cmd: float,
        yaw_rate_cmd: float,
    ) -> None:
        if ControlCommand is None or ControlType is None:
            raise RuntimeError(
                "telemetry_link.models is unavailable; cannot build unified ControlCommand"
            )
        self.telemetry_link.submit_control_command(
            ControlCommand(
                command_type=ControlType.VELOCITY,
                vx=vx_cmd,
                vy=vy_cmd,
                vz=vz_cmd,
                yaw_rate=yaw_rate_cmd,
                timestamp=time.time(),
                frame=self.config.body_frame,
            )
        )

    def _send_zero_body(self) -> None:
        if self.telemetry_link is None:
            return
        if hasattr(self.telemetry_link, "stop_control"):
            self.telemetry_link.stop_control(frame=self.config.body_frame)
            return
        if (
            hasattr(self.telemetry_link, "submit_control_command")
            and ControlCommand is not None
            and ControlType is not None
        ):
            self.telemetry_link.submit_control_command(
                ControlCommand(
                    command_type=ControlType.STOP,
                    vx=0.0,
                    vy=0.0,
                    vz=0.0,
                    yaw_rate=0.0,
                    timestamp=time.time(),
                    frame=self.config.body_frame,
                )
            )

    def _send_zero_gimbal(self) -> None:
        if self.telemetry_link is None:
            return
        rate_sender = getattr(self.telemetry_link, "send_gimbal_rate", None)
        if callable(rate_sender):
            rate_sender(yaw_rate=0.0, pitch_rate=0.0)
            self._last_gimbal_rate_command_at = time.time()

    def _finite_or_zero(self, value: Any) -> float:
        if value is None:
            return 0.0
        value = float(value)
        if not math.isfinite(value):
            return 0.0
        return value

    def _optional_finite(self, value: Any) -> float | None:
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value):
            return None
        return value

    def _format_optional_angle(self, value: Any) -> str:
        finite = self._optional_finite(value)
        if finite is None:
            return "none"
        return f"{finite:.3f}"
