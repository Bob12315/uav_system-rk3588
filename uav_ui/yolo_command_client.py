from __future__ import annotations

import json
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class YoloCommandConfig:
    ip: str = "127.0.0.1"
    port: int = 5006
    enabled: bool = True


class YoloCommandClient:
    def __init__(self, config: YoloCommandConfig) -> None:
        self.config = config

    def send(self, action: str, track_id: int | None = None) -> None:
        if not self.config.enabled:
            raise RuntimeError("yolo command client is disabled")
        payload: dict[str, object] = {"action": action}
        if track_id is not None:
            payload["track_id"] = int(track_id)
        data = json.dumps(payload).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(data, (self.config.ip, int(self.config.port)))

    def lock_target(self, track_id: int) -> None:
        self.send("lock_target", track_id=track_id)

    def unlock_target(self) -> None:
        self.send("unlock_target")
