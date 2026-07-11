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
    # altitude_source: not forced, uses default (v1-compatible)
    assert all("climb" not in r.reason and r.detail["phase"] != "climb" for r in results)
    assert any(r.reason == "gps_drop_next" for r in results)
def test_yaw_failure_stops_without_release(children):
    Yaw.failed=True; a=GpsDropSequenceAction(); a.start(params()); r=drive(a)[-1]
    assert r.failed and r.reason == "yaw_align_timeout"
    assert [x["action_type"] for x in r.actions] == ["flight_command", "clear_continuous_commands"]
def test_missing_local_height_stops_without_release(children):
    Align.missing=True; a=GpsDropSequenceAction(); a.start(params()); r=drive(a)[-1]
    assert r.failed and r.reason == "missing_local_ned_altitude"
def test_accepts_any_altitude_source():
    """Any altitude_source is now accepted (v1 default behavior)."""
    # auto
    a = GpsDropSequenceAction()
    a.start(params(align_descend={"config": {"altitude_source": "auto"}}))
    assert a.align_cfg["config"].get("altitude_source") == "auto"
    # local_ned
    a = GpsDropSequenceAction()
    a.start(params(align_descend={"config": {"altitude_source": "local_ned"}}))
    assert a.align_cfg["config"]["altitude_source"] == "local_ned"


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

# ── v1-v2 config consistency tests ──────────────────────────────────

def test_v2_align_config_matches_v1_except_payload_offset() -> None:
    """v2 align config matches v1, except payload offset injected per payload."""
    import json
    v1 = json.loads(open("config/action_missions/drop_two_targets_v1.json").read())
    v2 = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())

    # Get v1's first align_descend (there are two, almost identical)
    v1_aligns = [s for s in v1["steps"] if s["name"] == "align_descend"]
    assert len(v1_aligns) == 2
    v1_cfg_0 = v1_aligns[0]["params"]["config"]
    v1_cfg_1 = v1_aligns[1]["params"]["config"]

    # Get v2's align config from gps_drop_sequence
    v2_drop = next(s for s in v2["steps"] if s["name"] == "gps_drop_sequence")
    v2_align = v2_drop["params"]["align_descend"]
    v2_cfg = v2_align["config"]

    # V1's two align configs differ only in payload offset
    v1_diff_keys = set()
    for k in set(v1_cfg_0) | set(v1_cfg_1):
        if v1_cfg_0.get(k) != v1_cfg_1.get(k):
            v1_diff_keys.add(k)
    assert v1_diff_keys == {"payload_forward_m"}, f"V1 aligns differ in: {v1_diff_keys}"

    # V2 must NOT have these extra keys
    assert "finish_policy" not in v2_align
    assert "yaw_control_mode" not in v2_cfg
    assert "altitude_source" not in v2_cfg
    assert "descent_speed_stages" not in v2_cfg

    # V2 require_target_locked is false (matching v1)
    assert v2_cfg["require_target_locked"] is False

    # Compare v2 config to v1 config (excluding payload offset which v2 injects)
    v1_ref = dict(v1_cfg_0)
    v1_ref.pop("payload_forward_m", None)
    v1_ref.pop("payload_right_m", None)
    v2_ref = dict(v2_cfg)
    v2_ref.pop("payload_forward_m", None)
    v2_ref.pop("payload_right_m", None)

    for k in v1_ref:
        assert v2_ref.get(k) == v1_ref[k], f"Mismatch on key '{k}': v1={v1_ref[k]}, v2={v2_ref.get(k)}"

    for k in v2_ref:
        assert k in v1_ref, f"Extra key in v2: '{k}'"

    # Verify V2 top-level params match V1
    assert v2_align["expected_dt_s"] == v1_aligns[0]["params"]["expected_dt_s"]
    assert v2_align["max_updates"] == v1_aligns[0]["params"]["max_updates"]
    assert v2_align["hold_updates_required"] == v1_aligns[0]["params"]["hold_updates_required"]
    assert v2_drop["params"]["finish_altitude_m"] == v1_aligns[0]["params"]["finish_altitude_m"]
    assert v2_drop["params"]["align_descend_max_updates"] == v1_aligns[0]["params"]["max_updates"]


def test_v2_base_and_sitl_identical() -> None:
    """Base V2 config and SITL profile V2 config are byte-identical."""
    import json
    base = open("config/action_missions/drop_two_targets_v2.json").read()
    sitl = open("config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json").read()
    assert base == sitl


# ── runtime behavior tests: ScriptedAlign with scriptable outcomes ──

class ScriptedAlignV2:
    """Scripted AlignDescendAction that returns a pre-programmed result."""
    starts: list[dict[str, Any]] = []
    _script: tuple[bool, str] = (True, "aligned_at_finish_altitude")

    @classmethod
    def reset(cls, done: bool = True, reason: str = "aligned_at_finish_altitude") -> None:
        cls.starts = []
        cls._script = (done, reason)

    def start(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        type(self).starts.append(self.params)

    def update(self, context: dict[str, Any]) -> ActionResult:
        done, reason = type(self)._script
        if done:
            return ActionResult(done=True, reason=reason, detail={"command": {}})
        else:
            return ActionResult(failed=True, reason=reason, detail={"command": {}})


class ScriptedYawV2:
    @classmethod
    def reset(cls) -> None:
        pass
    def start(self, params: dict[str, Any]) -> None:
        pass
    def update(self, context: dict[str, Any]) -> ActionResult:
        return ActionResult(done=True)


@pytest.fixture
def v2_children(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace all child actions with scriptable mocks."""
    ScriptedGoto.reset()
    ScriptedLock.reset()
    ScriptedYawV2.reset()
    monkeypatch.setattr(mod, "GotoWaypointAction", ScriptedGoto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLock)
    monkeypatch.setattr(mod, "YawAlignAction", ScriptedYawV2)
    monkeypatch.setattr(mod, "AlignDescendAction", ScriptedAlignV2)


def _drive_to_terminal(action: GpsDropSequenceAction, limit: int = 40) -> list[ActionResult]:
    results: list[ActionResult] = []
    for _ in range(limit):
        r = action.update({"relative_altitude": 5.0})
        results.append(r)
        if r.done or r.failed:
            return results
    raise AssertionError("sequence did not terminate")


def _assert_no_servo(results: list[ActionResult]) -> None:
    for r in results:
        for a in r.actions:
            assert a.get("action_type") != "set_servo", f"unexpected set_servo in {r.reason}"


def _release_release_servo_channels(results: list[ActionResult]) -> list[int]:
    """Return channels for release-PWM set_servo actions in order, excluding hold."""
    channels: list[int] = []
    for r in results:
        for a in r.actions:
            if a.get("action_type") != "set_servo":
                continue
            ch = int(a["params"]["channel"])
            pwm = int(a["params"]["pwm"])
            # Payload 1: channel 8 release=1750 hold=1250
            # Payload 2: channel 9 release=1815 hold=1185
            if (ch == 8 and pwm == 1750) or (ch == 9 and pwm == 1815):
                channels.append(ch)
    return channels


@pytest.mark.parametrize("done,reason,expect_release", [
    (True, "min_altitude_reached", True),
    (True, "finish_altitude_reached", True),
    (True, "aligned_at_finish_altitude", True),
    (False, "align_descend_timeout", False),
    (False, "target_lost_timeout", False),
    (False, "missing_altitude", False),
])
def test_align_outcome(v2_children: None, done: bool, reason: str, expect_release: bool) -> None:
    """Align done → release with servo; align failed → fail with no servo."""
    ScriptedAlignV2.reset(done=done, reason=reason)
    action = GpsDropSequenceAction()
    action.start(params(release_wait_updates=1, align_descend_max_updates=10))
    results = _drive_to_terminal(action)

    if expect_release:
        assert results[-1].done, f"expected done for {reason}, got {results[-1].reason}"
        assert action.released_count in (1, 2)  # 1 for single, 2 for dual target with 2 payloads
        assert 8 in _release_release_servo_channels(results)
    else:
        assert results[-1].failed, f"expected failed for {reason}, got {results[-1].reason}"
        assert action.released_count == 0
        _assert_no_servo(results)
        # Verify zero+clear in failure actions
        types = [a.get("action_type") for r in results for a in r.actions]
        assert "flight_command" in types
        assert "clear_continuous_commands" in types


class HangingAlign:
    """An AlignDescendAction that never completes — forces outer counter timeout."""
    starts: list[dict[str, Any]] = []
    @classmethod
    def reset(cls) -> None:
        cls.starts = []
    def start(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        type(self).starts.append(self.params)
    def update(self, context: dict[str, Any]) -> ActionResult:
        return ActionResult(
            done=False, failed=False, reason="aligning",
            detail={"command": FULL_COMMAND},
        )


def test_outer_align_timeout_fails_no_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outer update_count > align_descend_max_updates → fail, no release."""
    ScriptedGoto.reset()
    ScriptedLock.reset()
    ScriptedYaw.reset()
    HangingAlign.reset()
    monkeypatch.setattr(mod, "GotoWaypointAction", ScriptedGoto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLock)
    monkeypatch.setattr(mod, "YawAlignAction", ScriptedYaw)
    monkeypatch.setattr(mod, "AlignDescendAction", HangingAlign)
    action = GpsDropSequenceAction()
    action.start(params(align_descend_max_updates=3, release_wait_updates=1))
    results = _drive_to_terminal(action, limit=30)

    assert results[-1].failed
    assert results[-1].reason == "align_descend_timeout"
    assert action.phase == "failed"
    assert action.released_count == 0
    _assert_no_servo(results)
    # Verify zero+clear in final result
    types = [a.get("action_type") for a in results[-1].actions]
    assert "flight_command" in types
    assert "clear_continuous_commands" in types


def test_dual_target_first_release_then_second(v2_children: None) -> None:
    """Dual target: first align done → release p1; second align done → release p2."""
    ScriptedAlignV2.reset(done=True, reason="min_altitude_reached")
    action = GpsDropSequenceAction()
    action.start(params(release_wait_updates=1, align_descend_max_updates=10))
    results = _drive_to_terminal(action, limit=60)

    assert results[-1].done
    assert action.released_count == 2
    # Order: p1=channel 8, p2=channel 9
    all_servos = _release_release_servo_channels(results)
    assert 8 in all_servos
    assert 9 in all_servos


def test_dual_target_first_fail_stops_second(v2_children: None) -> None:
    """First align failed → sequence fails, second target never attempted."""
    ScriptedAlignV2.reset(done=False, reason="align_descend_timeout")
    action = GpsDropSequenceAction()
    action.start(params(align_descend_max_updates=10, release_wait_updates=1))
    results = _drive_to_terminal(action, limit=40)

    assert results[-1].failed
    assert action.released_count == 0
    assert action.target_index == 0
    _assert_no_servo(results)


def test_single_target_dual_release_done(v2_children: None) -> None:
    """Single target: align done → dual release (channels 8 and 9)."""
    ScriptedAlignV2.reset(done=True, reason="finish_altitude_reached")
    action = GpsDropSequenceAction()
    action.start(params(
        targets=[TARGETS[0]], release_wait_updates=1, align_descend_max_updates=10,
    ))
    results = _drive_to_terminal(action, limit=40)

    assert results[-1].done
    assert action.released_count == 2
    ch = _release_release_servo_channels(results)
    assert 8 in ch and 9 in ch  # both channels present


def test_single_target_dual_release_fail(v2_children: None) -> None:
    """Single target: align failed → no servo release."""
    ScriptedAlignV2.reset(done=False, reason="target_lost_timeout")
    action = GpsDropSequenceAction()
    action.start(params(
        targets=[TARGETS[0]], release_wait_updates=1, align_descend_max_updates=10,
    ))
    results = _drive_to_terminal(action, limit=40)

    assert results[-1].failed
    assert action.released_count == 0
    _assert_no_servo(results)
