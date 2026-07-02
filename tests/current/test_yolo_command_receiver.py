from __future__ import annotations

import json
import socket

from yolo_app.command_receiver import CommandReceiver


def test_command_receiver_accepts_recording_commands() -> None:
    receiver = CommandReceiver("127.0.0.1", 0, enabled=True)
    assert receiver.sock is not None
    host, port = receiver.sock.getsockname()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(json.dumps({"action": "recording_start"}).encode("utf-8"), (host, port))
        sock.sendto(json.dumps({"action": "recording_stop"}).encode("utf-8"), (host, port))

    messages = receiver.poll()
    receiver.close()

    assert [message.action for message in messages] == ["recording_start", "recording_stop"]
