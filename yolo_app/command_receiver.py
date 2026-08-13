from __future__ import annotations

import json
import socket
import time
from contracts.perception_protocol import COMMAND_SCHEMA_VERSION

try:
    from .models import CommandMessage
except ImportError:
    from models import CommandMessage


class CommandReceiver:
    """
    Lightweight UDP command receiver.

    Accepted JSON examples:
    {"action": "switch_next"}
    {"action": "switch_prev"}
    {"action": "unlock_target"}
    {"action": "lock_target", "track_id": 7}
    {"action": "recording_start"}
    {"action": "recording_stop"}
    """

    def __init__(self, ip: str, port: int, enabled: bool = True) -> None:
        self.enabled = enabled
        self.sock: socket.socket | None = None
        self._last_sequence = -1
        if enabled:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((ip, port))
            self.sock.setblocking(False)

    def poll(self) -> list[CommandMessage]:
        if not self.enabled or self.sock is None:
            return []

        messages: list[CommandMessage] = []
        while True:
            try:
                payload, _ = self.sock.recvfrom(4096)
            except BlockingIOError:
                break

            try:
                decoded = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            if decoded.get("schema_version") != COMMAND_SCHEMA_VERSION:
                continue
            try:
                sequence = int(decoded["sequence"])
                sent_at = float(decoded["sent_at_monotonic"])
            except (KeyError, TypeError, ValueError):
                continue
            if sequence <= self._last_sequence or time.monotonic() - sent_at > 2.0:
                continue
            action = decoded.get("action")
            if action not in {
                "lock_target",
                "switch_next",
                "switch_prev",
                "unlock_target",
                "recording_start",
                "recording_stop",
            }:
                continue
            self._last_sequence = sequence
            track_id = decoded.get("track_id")
            if track_id is not None:
                try:
                    track_id = int(track_id)
                except (TypeError, ValueError):
                    track_id = None
            messages.append(CommandMessage(action=action, track_id=track_id))
        return messages

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
