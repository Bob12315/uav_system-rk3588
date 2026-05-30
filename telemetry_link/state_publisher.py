from __future__ import annotations

import json
import socket
from dataclasses import asdict

try:
    from .models import DroneState, GimbalState, LinkStatus
except ImportError:  # pragma: no cover - supports direct script execution
    from models import DroneState, GimbalState, LinkStatus


class StatePublisher:
    def __init__(self, udp_ip: str, udp_port: int) -> None:
        self.addr = (udp_ip, udp_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def publish(self, drone: DroneState, gimbal: GimbalState, link: LinkStatus, active_source: str) -> None:
        payload = {
            "active_source": active_source,
            "drone": asdict(drone),
            "gimbal": asdict(gimbal),
            "link": asdict(link),
        }
        self.sock.sendto(json.dumps(payload, ensure_ascii=False).encode("utf-8"), self.addr)

    def close(self) -> None:
        self.sock.close()
