from __future__ import annotations

from telemetry_link.mavlink_state_adapter import MavlinkVehicleStateAdapter
from telemetry_link.state_cache import StateCache


def test_atomic_snapshot_has_one_session_sequence_and_no_invalid_zero_pose() -> None:
    cache = StateCache(3.0, 2.0)
    cache.begin_receiver_generation()
    cache.update_drone_state(connected=True, stale=False, mode="GUIDED", control_allowed=True)
    adapter = MavlinkVehicleStateAdapter(lambda _: cache, lambda: "sitl")
    snapshot = adapter.snapshot("sitl")
    assert snapshot.link_session_id
    assert snapshot.sequence > 0
    assert snapshot.local_valid is False
    assert snapshot.local_north_m is None


def test_old_receiver_generation_cannot_overwrite_new_session() -> None:
    cache = StateCache(3.0, 2.0)
    old = cache.begin_receiver_generation()
    old_session = cache.atomic_publication(1.0)["session_id"]
    new = cache.begin_receiver_generation()
    cache.update_drone_state(receiver_generation=new, mode="GUIDED")
    cache.update_drone_state(receiver_generation=old, mode="OLD")
    publication = cache.atomic_publication(1.0)
    assert publication["session_id"] != old_session
    assert cache.get_latest_drone_state_raw().mode == "GUIDED"


def test_wait_next_returns_immediately_across_session() -> None:
    cache = StateCache(3.0, 2.0)
    cache.begin_receiver_generation()
    current = cache.atomic_publication(1.0)
    result = cache.wait_publication("old-session", 9999, 0.0)
    assert result is not None
    assert result["session_id"] == current["session_id"]
