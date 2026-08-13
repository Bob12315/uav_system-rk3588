from __future__ import annotations

import json
import socket
import time
from contracts.perception_protocol import make_perception_envelope

try:
    from .models import CurrentTarget, SceneDetections
except ImportError:
    from models import CurrentTarget, SceneDetections


class UdpPublisher:
    def __init__(self, udp_ip: str, udp_port: int) -> None:
        self.addr = (udp_ip, udp_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def publish(self, target: CurrentTarget, scene: SceneDetections | None = None) -> None:
        target_data = target.to_dict()
        data = make_perception_envelope(
            sequence=target.frame_id,
            captured_at_monotonic=time.monotonic(),
            target=target_data,
            scene=scene.to_dict() if scene is not None else {},
        ).to_dict()
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.sock.sendto(payload, self.addr)

    def close(self) -> None:
        self.sock.close()
