from __future__ import annotations

from datetime import timedelta
from threading import Thread

import pytest

from tests.fakes import FakeMavlink, FakeUdpPeer, FaultingStore, ManualClock, PausableWriter, StoreFault


def test_manual_clock_keeps_monotonic_when_wall_rolls_back() -> None:
    clock = ManualClock(monotonic_ns=10)
    initial_wall = clock.utc_now()
    clock.advance(2.0)
    clock.rollback_wall(5.0)
    assert clock.monotonic_ns() == 2_000_000_010
    assert clock.utc_now() == initial_wall - timedelta(seconds=3)


def test_pausable_writer_exposes_final_check_interleaving() -> None:
    writer = PausableWriter()
    writer.pause_at("before_final_check")
    allowed = {"value": True}
    thread = Thread(target=lambda: writer.write("command", final_check=lambda: allowed["value"]))
    thread.start()
    assert writer.wait_until("before_final_check")
    allowed["value"] = False
    writer.release("before_final_check")
    thread.join(1.0)
    assert not thread.is_alive()
    assert writer.writes == []


def test_fake_mavlink_preserves_sender_identity_and_ack_progress() -> None:
    mavlink = FakeMavlink()
    mavlink.inject_ack(22, 5, sysid=7, compid=9, progress=40)
    message = mavlink.receive(message_type="COMMAND_ACK")
    assert message is not None
    assert (message.sysid, message.compid) == (7, 9)
    assert message.fields == {"command": 22, "result": 5, "progress": 40}


def test_fake_udp_peer_faults_are_deterministic() -> None:
    peer = FakeUdpPeer()
    peer.drop_next = 1
    peer.send(b"lost")
    peer.duplicate_next = 1
    peer.send(b"twice")
    assert list(peer.outbound) == [b"twice", b"twice"]
    peer.restart("session-2")
    assert peer.session_id == "session-2"
    assert not peer.outbound


def test_faulting_store_reports_explicit_modes() -> None:
    store = FaultingStore()
    store.append({"event": 1})
    store.set_mode("full")
    with pytest.raises(StoreFault, match="storage_full"):
        store.append({"event": 2})
    assert store.records == [{"event": 1}]
