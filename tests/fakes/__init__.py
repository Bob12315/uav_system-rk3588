"""Deterministic, dependency-free platform test doubles."""

from .fake_mavlink import FakeMavlink, FakeMavlinkMessage
from .fake_udp_peer import FakeUdpPeer
from .faulting_store import FaultingStore, StoreFault
from .manual_clock import ManualClock
from .pausable_writer import PausableWriter

__all__ = [
    "FakeMavlink",
    "FakeMavlinkMessage",
    "FakeUdpPeer",
    "FaultingStore",
    "ManualClock",
    "PausableWriter",
    "StoreFault",
]
