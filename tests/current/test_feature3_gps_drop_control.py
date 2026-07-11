from __future__ import annotations
from typing import Any
import pytest
from missions.common.actions import gps_drop_sequence as mod
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.result import ActionResult

TARGETS = [{"valid": True, "lat": 34.1, "lon": 108.1, "class_name": "bucket", "target_id": "one"}, {"valid": True, "lat": 34.2, "lon": 108.2, "class_name": "bucket", "target_id": "two"}]
PAYLOADS = [{"payload_id": "p1", "servo_outputs": [{"channel": 8, "release_pwm": 1750, "hold_pwm": 1250}]}, {"payload_id": "p2", "servo_outputs": [{"channel": 9, "release_pwm": 1815, "hold_pwm": 1185}]}]
def params(**more: Any) -> dict[str, Any]:
    p = {"targets": TARGETS, "payloads": PAYLOADS, "release_wait_updates": 1, "goto_max_updates": 3, "yaw_align_max_updates": 3, "target_lock_max_updates": 3, "align_descend_max_updates": 3}
    p.update(more); return p
class Goto:
    starts: list[dict[str, Any]] = []
    def start(self, p): self.p = p; type(self).starts.append(p)
    def update(self, c): return ActionResult(done=True)
class Yaw:
    starts: list[dict[str, Any]] = []; failed = False
    def start(self, p): self.p = p; type(self).starts.append(p)
    def update(self, c): return ActionResult(failed=True, reason="yaw_align_timeout") if type(self).failed else ActionResult(done=True)
class Lock:
    starts: list[dict[str, Any]] = []
    def start(self, p): self.p = p; type(self).starts.append(p)
    def update(self, c): return ActionResult(done=True)
class Align:
    starts: list[dict[str, Any]] = []; missing = False
    def start(self, p): self.p = p; type(self).starts.append(p)
    def update(self, c): return ActionResult(failed=True, reason="missing_local_ned_altitude") if type(self).missing else ActionResult(done=True, reason="aligned_at_finish_altitude", detail={})
@pytest.fixture
def children(monkeypatch):
    for cls in (Goto, Yaw, Lock, Align): cls.starts = []
    Yaw.failed = Align.missing = False
    monkeypatch.setattr(mod, "GotoWaypointAction", Goto); monkeypatch.setattr(mod, "YawAlignAction", Yaw)
    monkeypatch.setattr(mod, "GpsTargetLockAction", Lock); monkeypatch.setattr(mod, "AlignDescendAction", Align)
def drive(a):
    results=[]
    for _ in range(30):
        r=a.update({}); results.append(r)
        if r.done or r.failed: return results
    raise AssertionError("not terminal")
def test_two_targets_direct_goto_with_yaw_per_target(children):
    a=GpsDropSequenceAction(); a.start(params(approach_altitude_m=2.5)); results=drive(a)
    assert results[-1].done and a.released_count == 2 and a.phase == "done"
    assert [(x["lat"],x["lon"],x["altitude_m"],x["yaw_mode"]) for x in Goto.starts] == [(34.1,108.1,2.5,"field_heading"),(34.2,108.2,2.5,"field_heading")]
    assert [x["key"] for x in Yaw.starts] == ["gps_drop_yaw_align_0", "gps_drop_yaw_align_1"]
    assert all(x["config"]["altitude_source"] == "local_ned" for x in Align.starts)
    assert all("climb" not in r.reason and r.detail["phase"] != "climb" for r in results)
    assert any(r.reason == "gps_drop_next" for r in results)
def test_yaw_failure_stops_without_release(children):
    Yaw.failed=True; a=GpsDropSequenceAction(); a.start(params()); r=drive(a)[-1]
    assert r.failed and r.reason == "yaw_align_timeout"
    assert [x["action_type"] for x in r.actions] == ["flight_command", "clear_continuous_commands"]
def test_missing_local_height_stops_without_release(children):
    Align.missing=True; a=GpsDropSequenceAction(); a.start(params()); r=drive(a)[-1]
    assert r.failed and r.reason == "missing_local_ned_altitude"
@pytest.mark.parametrize("source", ["auto", "relative_altitude"])
def test_rejects_nonlocal_source(source):
    with pytest.raises(ValueError, match="altitude_source"):
        GpsDropSequenceAction().start(params(align_descend={"config": {"altitude_source": source}}))


# The V2 SITL harness imports these test doubles.  Keep its narrow statistics
# fixture independent of the direct-flow assertions above.
def _params(**more):
    value = params()
    value["payloads"] = [
        {"payload_id": "p0", "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}]},
        {"payload_id": "p1", "servo_outputs": [{"channel": 9, "release_pwm": 1250, "hold_pwm": 1750}]},
    ]
    value.update(more)
    return value
FULL_COMMAND = {"type": "flight_command", "valid": True, "active": True,
                "enable_body": True, "vx_cmd": 0.12, "vy_cmd": -0.08,
                "vz_cmd": 0.18, "yaw_rate_cmd": 0.0, "priority": 7}
class ScriptedGoto:
    starts = []
    @classmethod
    def reset(cls): cls.starts = []
    def start(self, p): self.p = p; self.calls = 0; type(self).starts.append(p)
    def update(self, c):
        self.calls += 1
        return ActionResult(actions=[{"action_type": "global_goto", "params": {}, "once": False}]) if self.calls == 1 else ActionResult(done=True)
class ScriptedLock:
    starts = []
    @classmethod
    def reset(cls): cls.starts = []
    def start(self, p): type(self).starts.append(p)
    def update(self, c): return ActionResult(done=True)
class ScriptedAlign:
    starts = []
    @classmethod
    def reset(cls): cls.starts = []
    def start(self, p): self.calls = 0; type(self).starts.append(p)
    def update(self, c):
        self.calls += 1
        return ActionResult(detail={"command": dict(FULL_COMMAND)}) if self.calls == 1 else ActionResult(done=True, reason="aligned_at_finish_altitude", detail={})
class ScriptedYaw:
    @classmethod
    def reset(cls): pass
    def start(self, p): pass
    def update(self, c): return ActionResult(done=True)
def _drive_until_terminal(action): return drive(action)
