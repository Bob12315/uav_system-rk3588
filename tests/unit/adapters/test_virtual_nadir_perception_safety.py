from __future__ import annotations

from types import SimpleNamespace

from yolo_app.models import Track
from yolo_app.target_manager import TargetManager


def test_target_manager_invalidate_immediately_clears_lock_and_lost_grace() -> None:
    cfg = SimpleNamespace(
        selection_mode="center",
        target_class="",
        max_lost_frames=10,
    )
    manager = TargetManager(cfg)
    track = Track(7, 0, "Target", 0.9, 10, 10, 30, 30)
    manager.update([track], 100, 100, 1, 1.0)
    assert manager.locked_track_id == 7

    manager.invalidate()
    current = manager.update([], 100, 100, 2, 2.0)

    assert manager.locked_track_id is None
    assert current.target_valid is False
    assert current.tracking_state == "invalid"
    assert current.lost_count == 0
