from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ControlSwitchSnapshot:
    gimbal: bool
    body: bool
    approach: bool
    send_commands: bool


class ControlRuntimeSwitches:
    def __init__(
        self,
        *,
        gimbal: bool,
        body: bool,
        approach: bool,
        send_commands: bool,
    ) -> None:
        self._lock = threading.Lock()
        self._gimbal = bool(gimbal)
        self._body = bool(body)
        self._approach = bool(approach)
        self._send_commands = bool(send_commands)

    def snapshot(self) -> ControlSwitchSnapshot:
        with self._lock:
            return ControlSwitchSnapshot(
                gimbal=self._gimbal,
                body=self._body,
                approach=self._approach,
                send_commands=self._send_commands,
            )

    def set_controller(self, name: str, enabled: bool) -> ControlSwitchSnapshot:
        normalized = name.strip().lower()
        with self._lock:
            if normalized in {"gimbal", "all"}:
                self._gimbal = bool(enabled)
            if normalized in {"body", "all"}:
                self._body = bool(enabled)
            if normalized in {"approach", "all"}:
                self._approach = bool(enabled)
            return ControlSwitchSnapshot(
                gimbal=self._gimbal,
                body=self._body,
                approach=self._approach,
                send_commands=self._send_commands,
            )

    def toggle_controller(self, name: str) -> ControlSwitchSnapshot:
        normalized = name.strip().lower()
        with self._lock:
            if normalized == "gimbal":
                self._gimbal = not self._gimbal
            elif normalized == "body":
                self._body = not self._body
            elif normalized == "approach":
                self._approach = not self._approach
            elif normalized == "all":
                enabled = not (self._gimbal and self._body and self._approach)
                self._gimbal = enabled
                self._body = enabled
                self._approach = enabled
            return ControlSwitchSnapshot(
                gimbal=self._gimbal,
                body=self._body,
                approach=self._approach,
                send_commands=self._send_commands,
            )

    def set_send_commands(self, enabled: bool) -> ControlSwitchSnapshot:
        with self._lock:
            self._send_commands = bool(enabled)
            return ControlSwitchSnapshot(
                gimbal=self._gimbal,
                body=self._body,
                approach=self._approach,
                send_commands=self._send_commands,
            )

    def toggle_send_commands(self) -> ControlSwitchSnapshot:
        with self._lock:
            self._send_commands = not self._send_commands
            return ControlSwitchSnapshot(
                gimbal=self._gimbal,
                body=self._body,
                approach=self._approach,
                send_commands=self._send_commands,
            )
