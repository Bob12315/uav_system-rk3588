from __future__ import annotations

import json
import socket
import time

from yolo_app.command_receiver import CommandReceiver


def test_command_receiver_accepts_recording_commands() -> None:
    receiver = CommandReceiver("127.0.0.1", 0, enabled=True)
    assert receiver.sock is not None
    host, port = receiver.sock.getsockname()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        now = time.monotonic()
        sock.sendto(json.dumps({"schema_version": 1, "sequence": 1, "sent_at_monotonic": now,
                                "action": "recording_start"}).encode("utf-8"), (host, port))
        sock.sendto(json.dumps({"schema_version": 1, "sequence": 2, "sent_at_monotonic": now,
                                "action": "recording_stop"}).encode("utf-8"), (host, port))

    messages = receiver.poll()
    receiver.close()

    assert [message.action for message in messages] == ["recording_start", "recording_stop"]


def test_command_receiver_rejects_legacy_and_out_of_order_messages() -> None:
    receiver = CommandReceiver("127.0.0.1", 0, enabled=True)
    assert receiver.sock is not None
    host, port = receiver.sock.getsockname()
    now = time.monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(json.dumps({"action": "recording_start"}).encode(), (host, port))
        message = {"schema_version": 1, "sequence": 3, "sent_at_monotonic": now,
                   "action": "recording_stop"}
        sock.sendto(json.dumps(message).encode(), (host, port))
        sock.sendto(json.dumps(message).encode(), (host, port))
    assert [item.action for item in receiver.poll()] == ["recording_stop"]
    receiver.close()
