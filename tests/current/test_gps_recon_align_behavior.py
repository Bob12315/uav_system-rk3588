"""Tests verifying GpsReconSequenceAction is unaffected by drop-only changes."""
from __future__ import annotations

import pytest
from missions.common.actions import gps_recon_sequence as mod
from missions.common.actions.gps_recon_sequence import GpsReconSequenceAction
from missions.common.actions.result import ActionResult


class Recorder:
    """Record all sub-action starts and updates."""
    starts: list[dict] = []
    @classmethod
    def reset(cls): cls.starts = []


class ReconScriptedGoto(Recorder):
    def start(self, p):
        self.p = p
        type(self).starts.append(p)
    def update(self, c):
        return ActionResult(done=True)


class ReconScriptedLock(Recorder):
    def start(self, p):
        type(self).starts.append(p)
    def update(self, c):
        return ActionResult(done=True)


class ReconScriptedAlign(Recorder):
    """Returns a programmed result (done/failed)."""
    _done: bool = True
    _reason: str = "aligned_at_finish_altitude"

    @classmethod
    def reset(cls, done: bool = True, reason: str = "aligned_at_finish_altitude"):
        cls.starts = []
        cls._done = done
        cls._reason = reason

    def start(self, p):
        self.p = p
        type(self).starts.append(p)

    def update(self, c):
        if type(self)._done:
            return ActionResult(done=True, reason=type(self)._reason, detail={"command": {}})
        else:
            return ActionResult(failed=True, reason=type(self)._reason, detail={"command": {}})


@pytest.fixture
def recon_children(monkeypatch: pytest.MonkeyPatch):
    ReconScriptedGoto.reset()
    ReconScriptedLock.reset()
    ReconScriptedAlign.reset(done=True)
    monkeypatch.setattr(mod, "GotoWaypointAction", ReconScriptedGoto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ReconScriptedLock)
    monkeypatch.setattr(mod, "AlignDescendAction", ReconScriptedAlign)


TARGETS = [
    {"valid": True, "lat": 34.1, "lon": 108.1, "class_name": "bucket", "target_id": "r1"},
    {"valid": True, "lat": 34.2, "lon": 108.2, "class_name": "bucket", "target_id": "r2"},
]


def _params(**more):
    p = {
        "targets": TARGETS,
        "approach_altitude_m": 2.0,
        "finish_altitude_m": 2.2,
        "climb_after_drop_m": 2.0,
        "climb_tolerance_z_m": 0.2,
        "climb_max_updates": 10,
        "goto_max_updates": 3,
        "target_lock_max_updates": 3,
        "align_descend_max_updates": 3,
    }
    p.update(more)
    return p


def _drive_recon(action, limit=40):
    results = []
    alt = 5.0
    for _ in range(limit):
        r = action.update({"drone": {"relative_altitude": alt, "lat": 34.1, "lon": 108.1, "yaw": 1.5}})
        results.append(r)
        if r.done or r.failed:
            return results
        if r.detail.get("phase") == "climb":
            alt = 3.0
    raise AssertionError("recon sequence did not terminate")


def test_recon_align_failure_still_fails(recon_children):
    """Recon sequence: align failure still fails (does NOT force release)."""
    ReconScriptedAlign.reset(done=False, reason="target_lost_timeout")
    action = GpsReconSequenceAction()
    action.start(_params(align_descend_max_updates=10))
    results = _drive_recon(action, limit=80)

    assert results[-1].failed, f"recon should fail on align failure, got {results[-1].reason}"
    assert action.phase == "failed"


def test_recon_align_timeout_still_fails(recon_children):
    """Recon sequence: outer align timeout still fails (does NOT force release)."""
    ReconScriptedAlign.reset(done=False, reason="align_descend_timeout")
    action = GpsReconSequenceAction()
    action.start(_params(align_descend_max_updates=10))
    results = _drive_recon(action, limit=80)

    assert results[-1].failed, f"recon should fail on align timeout, got {results[-1].reason}"
    assert action.phase == "failed"
