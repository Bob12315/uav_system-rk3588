from __future__ import annotations

import threading

from application.state_store import ApplicationStateStore


def test_read_is_defensive_copy() -> None:
    store = ApplicationStateStore()
    original = {"drone": {"x": 1}}
    store.replace(original)
    original["drone"]["x"] = 2
    first = store.read()
    first["drone"]["x"] = 3
    assert store.read()["drone"]["x"] == 1


def test_concurrent_read_write_keeps_complete_snapshots() -> None:
    store = ApplicationStateStore()
    errors: list[str] = []
    def writer() -> None:
        for value in range(200):
            store.replace({"value": value, "mirror": value})
    thread = threading.Thread(target=writer)
    thread.start()
    while thread.is_alive():
        snapshot = store.read()
        if snapshot and snapshot["value"] != snapshot["mirror"]:
            errors.append("torn snapshot")
    thread.join()
    assert errors == []
