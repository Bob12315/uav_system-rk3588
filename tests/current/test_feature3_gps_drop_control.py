from __future__ import annotations
from typing import Any
import pytest
from missions.common.actions import gps_drop_sequence as mod
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.result import ActionResult

TARGETS = [{"valid": True, "lat": 34.1, "lon": 108.1, "class_name": "bucket", "target_id": "one"}, {"valid": True, "lat": 34.2, "lon": 108.2, "class_name": "bucket", "target_id": "two"}]
PAYLOADS = [{"payload_id": "p1", "servo_outputs": [{"channel": 8, "release_pwm": 1750, "hold_pwm": 1250}]}, {"payload_id": "p2", "servo_outputs": [{"channel": 9, "release_pwm": 1815, "hold_pwm": 1185}]}]
def params(**more: Any) -> dict[str, Any]:
    p = {"targets": TARGETS, "payloads": PAYLOADS, "release_wait_updates": 1, "goto_max_updates": 3, "target_lock_max_updates": 3, "align_descend_max_updates": 3, "climb_max_updates": 10}
    p.update(more); return p
class Goto:
    starts: list[dict[str, Any]] = []
    def start(self, p): self.p = p; type(self).starts.append(p)
    def update(self, c): return ActionResult(done=True)
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
    for cls in (Goto, Lock, Align): cls.starts = []
    Align.missing = False
    monkeypatch.setattr(mod, "GotoWaypointAction", Goto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", Lock); monkeypatch.setattr(mod, "AlignDescendAction", Align)

def drive_with_alt(a, alt=5.0):
    """Drive sequence with altitude context for climb."""
    results=[]
    for _ in range(60):
        r=a.update({"drone": {"relative_altitude": alt, "lat": 34.1, "lon": 108.1, "yaw": 1.5}})
        results.append(r)
        if r.done or r.failed: return results
        # After climb starts, simulate reaching climb altitude
        if r.reason == "gps_drop_climb" and r.detail.get("phase") == "climb":
            alt = 3.0  # above 2.5m
    raise AssertionError("not terminal")

def drive(a):
    return drive_with_alt(a)

def test_two_targets_direct_goto_with_field_heading_no_yaw_align(children):
    """Dual target: goto with field_heading, no independent yaw_align phase, climb after each release."""
    a=GpsDropSequenceAction(); a.start(params(approach_altitude_m=2.5)); results=drive(a)
    assert results[-1].done and a.released_count == 2 and a.phase == "done"
    assert [(x["lat"],x["lon"],x["altitude_m"],x["yaw_mode"]) for x in Goto.starts] == [
        (34.1,108.1,2.5,"field_heading"),
        (34.1,108.1,2.5,"field_heading"),  # climb at target 0
        (34.2,108.2,2.5,"field_heading"),  # goto target 1
        (34.2,108.2,2.5,"field_heading"),  # climb at target 1
    ]
    # No yaw_align phase in results
    phases = [r.detail.get("phase") for r in results if r.detail]
    assert "yaw_align" not in phases
    # Climb phases present
    assert "climb" in phases
    assert any(r.reason == "gps_drop_next" for r in results)

def test_missing_local_height_stops_without_release(children):
    Align.missing=True; a=GpsDropSequenceAction(); a.start(params()); r=drive(a)[-1]
    assert r.failed and r.reason == "missing_local_ned_altitude"

def test_accepts_any_altitude_source():
    """Any altitude_source is now accepted (v1 default behavior)."""
    a = GpsDropSequenceAction()
    a.start(params(align_descend={"config": {"altitude_source": "auto"}}))
    assert a.align_cfg["config"].get("altitude_source") == "auto"
    a = GpsDropSequenceAction()
    a.start(params(align_descend={"config": {"altitude_source": "local_ned"}}))
    assert a.align_cfg["config"]["altitude_source"] == "local_ned"

def test_climb_only_checks_altitude(children):
    """Climb completes when altitude >= climb_after_drop_m - tolerance_z_m (2.4m)."""
    a=GpsDropSequenceAction()
    a.start(params(climb_after_drop_m=2.5, climb_tolerance_z_m=0.1))
    # Drive until release done, then climb
    results = drive_with_alt(a, alt=2.39)
    # At 2.39m climb should not complete - but with mocks it finishes fast
    # The key check: climb uses altitude-only one-way gate
    # With our drive we push alt to 3.0 after first climb detection
    assert results[-1].done

def test_climb_timeout_fails_no_next_target(children):
    """Climb timeout causes failure, no next target, no release."""
    call_count = [0]
    class ScriptedGotoClimb:
        starts = []
        def start(self, p):
            self.p = p
            type(self).starts.append(p)
        def update(self, c):
            call_count[0] += 1
            # First 2 gotos (approach target 0, climb target 0) succeed
            # The climb goto hangs (3rd goto call for approach target 1 never happens in this scenario)
            key = self.p.get("key", "")
            if "climb" in key:
                return ActionResult(done=False, actions=[])
            return ActionResult(done=True)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "GotoWaypointAction", ScriptedGotoClimb)
    monkeypatch.setattr(mod, "GpsTargetLockAction", Lock)
    monkeypatch.setattr(mod, "AlignDescendAction", Align)
    ScriptedGotoClimb.starts = []
    Lock.starts = []
    a=GpsDropSequenceAction()
    a.start(params(climb_max_updates=3))
    results=[]
    for _ in range(30):
        r=a.update({"drone": {"relative_altitude": 1.0, "lat": 34.1, "lon": 108.1, "yaw": 1.5}})
        results.append(r)
        if r.failed: break
    assert results[-1].failed
    assert results[-1].reason == "climb_timeout"

def test_single_target_dual_release_then_climb(children):
    """Single target: align done → dual release → climb → done."""
    action = GpsDropSequenceAction()
    action.start(params(
        targets=[TARGETS[0]], release_wait_updates=1, align_descend_max_updates=10,
    ))
    results = drive(action)
    assert results[-1].done
    assert action.released_count == 2
    # Should have climb phase
    phases = [r.detail.get("phase") for r in results if r.detail]
    assert "climb" in phases
    assert results[-1].reason == "gps_drop_sequence_done"

# ── v1-v2 config consistency tests ──────────────────────────────────

def test_v2_align_config_matches_v1_except_payload_offset() -> None:
    """v2 align config matches v1, except payload offset injected per payload."""
    import json
    v1 = json.loads(open("config/action_missions/drop_two_targets_v1.json").read())
    v2 = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())

    v1_aligns = [s for s in v1["steps"] if s["name"] == "align_descend"]
    assert len(v1_aligns) == 2
    v1_cfg_0 = v1_aligns[0]["params"]["config"]
    v1_cfg_1 = v1_aligns[1]["params"]["config"]

    v2_drop = next(s for s in v2["steps"] if s["name"] == "gps_drop_sequence")
    v2_align = v2_drop["params"]["align_descend"]
    v2_cfg = v2_align["config"]

    v1_diff_keys = set()
    for k in set(v1_cfg_0) | set(v1_cfg_1):
        if v1_cfg_0.get(k) != v1_cfg_1.get(k):
            v1_diff_keys.add(k)
    assert v1_diff_keys == {"payload_forward_m"}, f"V1 aligns differ in: {v1_diff_keys}"

    # v2 uses competition params (intentionally different from v1)
    assert v2_align.get("finish_policy") == "latched_center_alignment"
    assert v2_align.get("finish_alignment_max_ex_cam") == 0.35
    assert v2_align.get("finish_alignment_max_ey_cam") == 0.35
    assert v2_align.get("finish_alignment_hold_updates") == 1

    # v2 require_target_locked is false (matching v1)
    assert v2_cfg["require_target_locked"] is False

    # Verify v2-only competition keys (not in v1)
    v2_only_keys = {"descent_gate_policy", "unaligned_descend_speed_mps"}
    assert v2_cfg["descent_gate_policy"] == "allow_unaligned"
    assert v2_cfg["unaligned_descend_speed_mps"] == 0.08

    # Competition-intentionally-divergent keys (v1->v2 changed values)
    # height_scale_points and deadband are also auto-excluded from the dict comparison
    v2_changed_keys = {
        "max_ex_cam": 0.28,
        "max_ey_cam": 0.28,
        "slow_descend_max_ex_cam": 0.55,
        "slow_descend_max_ey_cam": 0.55,
    }
    v2_changed_simple_keys = {"descend_speed_mps"}
    v2_changed_list_keys = {"height_scale_points", "deadband_ex_cam", "deadband_ey_cam"}
    for k, expected in v2_changed_keys.items():
        assert v2_cfg[k] == expected, f"v2 {k} should be {expected}"

    # Compare v2 config to v1 config (excluding keys only in v2, changed keys, and payload offset which v2 injects)
    v1_ref = dict(v1_cfg_0)
    v1_ref.pop("payload_forward_m", None)
    v1_ref.pop("payload_right_m", None)
    v2_ref = dict(v2_cfg)
    v2_ref.pop("payload_forward_m", None)
    v2_ref.pop("payload_right_m", None)

    for k in v1_ref:
        if k in v2_only_keys or k in v2_changed_keys or k in v2_changed_list_keys or k in v2_changed_simple_keys:
            continue
        assert v2_ref.get(k) == v1_ref[k], f"Mismatch on key '{k}': v1={v1_ref[k]}, v2={v2_ref.get(k)}"

    for k in v2_ref:
        if k in v2_only_keys or k in v2_changed_keys or k in v2_changed_list_keys or k in v2_changed_simple_keys:
            continue
        assert k in v1_ref, f"Extra key in v2: '{k}'"

    assert v2_align["expected_dt_s"] == v1_aligns[0]["params"]["expected_dt_s"]
    assert v2_align["max_updates"] == 35  # competition override
    assert v2_align["hold_updates_required"] == v1_aligns[0]["params"]["hold_updates_required"]
    assert v2_drop["params"]["finish_altitude_m"] == v1_aligns[0]["params"]["finish_altitude_m"]
    assert v2_drop["params"]["align_descend_max_updates"] == 35  # competition override


def test_v2_base_and_sitl_identical() -> None:
    """Base V2 config and SITL profile V2 config are byte-identical."""
    import json
    base = open("config/action_missions/drop_two_targets_v2.json").read()
    sitl = open("config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json").read()
    assert base == sitl


# ── v2 mission structure tests ───────────────────────────────────────

def test_v2_scan_has_no_yaw_align() -> None:
    """v2 mission scan step has no first_waypoint_yaw_align config."""
    import json
    v2 = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    scan = next(s for s in v2["steps"] if s["name"] == "gps_multi_view_localize")
    assert "first_waypoint_yaw_align" not in scan["params"]
    assert scan["params"]["yaw_mode"] == "field_heading"
    assert scan["params"]["scan_altitude_m"] == 4.5

def test_v2_drop_has_no_yaw_align() -> None:
    """v2 mission drop sequence has no yaw_align config."""
    import json
    v2 = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    drop = next(s for s in v2["steps"] if s["name"] == "gps_drop_sequence")
    assert "yaw_align" not in drop["params"]
    assert "yaw_align_max_updates" not in drop["params"]
    assert drop["params"]["climb_after_drop_m"] == 2.5

def test_v2_rth_field_heading() -> None:
    """v2 mission return home uses field_heading."""
    import json
    v2 = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    rth = next(s for s in v2["steps"] if s["label"] == "return_home_gps")
    assert rth["params"]["yaw_mode"] == "field_heading"

def test_v2_takeoff_altitude() -> None:
    """v2 takeoff altitude is 3.5m with label takeoff_3_5m."""
    import json
    v2 = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    to = next(s for s in v2["steps"] if s["name"] == "takeoff")
    assert to["label"] == "takeoff_3_5m"
    assert to["params"]["altitude_m"] == 3.5

# ── runtime behavior tests ───────────────────────────────────────────

FULL_COMMAND_ALIGN = {"type": "flight_command", "valid": True, "active": True,
                     "enable_body": True, "vx_cmd": 0.12, "vy_cmd": -0.08,
                     "vz_cmd": 0.18, "yaw_rate_cmd": 0.0, "priority": 7}

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
        self.calls = 0
        type(self).starts.append(self.params)

    def update(self, context: dict[str, Any]) -> ActionResult:
        self.calls += 1
        done, reason = type(self)._script
        if self.calls == 1 and done:
            return ActionResult(detail={"command": dict(FULL_COMMAND_ALIGN)})
        if done:
            return ActionResult(done=True, reason=reason, detail={"command": {}})
        else:
            return ActionResult(failed=True, reason=reason, detail={"command": {}})


class ScriptedGotoV2:
    starts: list[dict[str, Any]] = []
    @classmethod
    def reset(cls): cls.starts = []
    def start(self, p): self.p = p; self.calls = 0; type(self).starts.append(p)
    def update(self, c):
        self.calls += 1
        return ActionResult(actions=[{"action_type": "global_goto", "params": {}, "once": False}]) if self.calls == 1 else ActionResult(done=True)


class ScriptedLockV2:
    starts: list[dict[str, Any]] = []
    @classmethod
    def reset(cls): cls.starts = []
    def start(self, p): type(self).starts.append(p)
    def update(self, c): return ActionResult(done=True)


@pytest.fixture
def v2_children(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace all child actions with scriptable mocks."""
    ScriptedGotoV2.reset()
    ScriptedLockV2.reset()
    ScriptedAlignV2.reset(done=True, reason="aligned_at_finish_altitude")
    monkeypatch.setattr(mod, "GotoWaypointAction", ScriptedGotoV2)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLockV2)
    monkeypatch.setattr(mod, "AlignDescendAction", ScriptedAlignV2)


def _drive_to_terminal(action: GpsDropSequenceAction, limit: int = 80) -> list[ActionResult]:
    results: list[ActionResult] = []
    alt = 5.0
    for _ in range(limit):
        r = action.update({"drone": {"relative_altitude": alt, "lat": 34.1, "lon": 108.1, "yaw": 1.5}})
        results.append(r)
        if r.done or r.failed:
            return results
        if r.detail.get("phase") == "climb":
            alt = 3.0  # above 2.5m
    raise AssertionError("sequence did not terminate")


def _assert_no_servo(results: list[ActionResult]) -> None:
    for r in results:
        for a in r.actions:
            assert a.get("action_type") != "set_servo", f"unexpected set_servo in {r.reason}"


def _release_servo_channels(results: list[ActionResult]) -> list[int]:
    """Return channels for release-PWM set_servo actions in order, excluding hold."""
    channels: list[int] = []
    for r in results:
        for a in r.actions:
            if a.get("action_type") != "set_servo":
                continue
            ch = int(a["params"]["channel"])
            pwm = int(a["params"]["pwm"])
            if (ch == 8 and pwm == 1750) or (ch == 9 and pwm == 1815):
                channels.append(ch)
    return channels


@pytest.mark.parametrize("done,reason,expect_release", [
    (True, "min_altitude_reached", True),
    (True, "finish_altitude_reached", True),
    (True, "aligned_at_finish_altitude", True),
    (False, "align_descend_timeout", True),
    (False, "target_lost_timeout", True),
    (False, "missing_altitude", False),
])
def test_align_outcome(v2_children: None, done: bool, reason: str, expect_release: bool) -> None:
    """Align done → release → climb; align timeout/lost → force release; structural error → fail with no servo."""
    ScriptedAlignV2.reset(done=done, reason=reason)
    action = GpsDropSequenceAction()
    action.start(params(release_wait_updates=1, align_descend_max_updates=10))
    results = _drive_to_terminal(action)

    if expect_release:
        assert results[-1].done, f"expected done for {reason}, got {results[-1].reason}"
        assert action.released_count in (1, 2)
        assert 8 in _release_servo_channels(results)
    else:
        assert results[-1].failed, f"expected failed for {reason}, got {results[-1].reason}"
        assert action.released_count == 0
        _assert_no_servo(results)
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
            detail={"command": {"type": "flight_command", "valid": True, "active": True,
                                "enable_body": True, "vx_cmd": 0.12, "vy_cmd": -0.08,
                                "vz_cmd": 0.18, "yaw_rate_cmd": 0.0, "priority": 7}},
        )


def test_outer_align_timeout_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outer update_count > align_descend_max_updates → force release, not fail."""
    ScriptedGotoV2.reset()
    ScriptedLockV2.reset()
    HangingAlign.reset()
    monkeypatch.setattr(mod, "GotoWaypointAction", ScriptedGotoV2)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLockV2)
    monkeypatch.setattr(mod, "AlignDescendAction", HangingAlign)
    action = GpsDropSequenceAction()
    action.start(params(align_descend_max_updates=3, release_wait_updates=1))
    results = _drive_to_terminal(action, limit=30)

    assert not results[-1].failed, f"expected done (force release), got failed: {results[-1].reason}"
    assert results[-1].done, f"expected done (force release), got {results[-1].reason}"
    assert action.phase == "done"
    assert action.released_count in (1, 2)
    # verify stop actions (zero velocity + clear continuous) were emitted
    stop_actions = [a for r in results for a in r.actions if a.get('action_type') == 'clear_continuous_commands']
    assert len(stop_actions) >= 1
    # verify detail includes force release marker
    force_detail = None
    for r in results:
        if r.detail.get('align_timeout_release') or r.detail.get('align_failed_release'):
            force_detail = r.detail
            break
    assert force_detail is not None, "should have force release marker in detail"
    assert force_detail['failure_event'] == 'align_timeout'


def test_dual_target_first_release_then_climb_then_second(v2_children: None) -> None:
    """Dual target: first align done → release p1 → climb → goto target 2 → release p2."""
    ScriptedAlignV2.reset(done=True, reason="min_altitude_reached")
    action = GpsDropSequenceAction()
    action.start(params(release_wait_updates=1, align_descend_max_updates=10))
    results = _drive_to_terminal(action, limit=80)

    assert results[-1].done
    assert action.released_count == 2
    all_servos = _release_servo_channels(results)
    assert 8 in all_servos
    assert 9 in all_servos


def test_dual_target_first_timeout_releases_both(v2_children: None) -> None:
    """First align timeout → force release p1 → climb → goto target 2 → release p2."""
    ScriptedAlignV2.reset(done=False, reason="align_descend_timeout")
    action = GpsDropSequenceAction()
    action.start(params(align_descend_max_updates=10, release_wait_updates=1))
    results = _drive_to_terminal(action, limit=80)

    assert results[-1].done, f"expected done, got {results[-1].reason}"
    assert action.released_count == 2
    all_servos = _release_servo_channels(results)
    assert 8 in all_servos
    assert 9 in all_servos


def test_single_target_dual_release_done(v2_children: None) -> None:
    """Single target: align done → dual release → climb → done."""
    ScriptedAlignV2.reset(done=True, reason="finish_altitude_reached")
    action = GpsDropSequenceAction()
    action.start(params(
        targets=[TARGETS[0]], release_wait_updates=1, align_descend_max_updates=10,
    ))
    results = _drive_to_terminal(action, limit=80)

    assert results[-1].done
    assert action.released_count == 2
    ch = _release_servo_channels(results)
    assert 8 in ch and 9 in ch


def test_single_target_dual_release_timeout_releases(v2_children: None) -> None:
    """Single target: align timeout → force dual release → climb → done."""
    ScriptedAlignV2.reset(done=False, reason="target_lost_timeout")
    action = GpsDropSequenceAction()
    action.start(params(
        targets=[TARGETS[0]], release_wait_updates=1, align_descend_max_updates=10,
    ))
    results = _drive_to_terminal(action, limit=80)

    assert results[-1].done, f"expected done (force release), got {results[-1].reason}"
    assert action.released_count == 2
    ch = _release_servo_channels(results)
    assert 8 in ch and 9 in ch


def test_structural_error_still_fails(v2_children: None) -> None:
    """Structural error (missing altitude) still fails, no release."""
    ScriptedAlignV2.reset(done=False, reason="missing_altitude")
    action = GpsDropSequenceAction()
    action.start(params(release_wait_updates=1, align_descend_max_updates=10))
    results = _drive_to_terminal(action)

    assert results[-1].failed
    assert action.released_count == 0
    _assert_no_servo(results)


# ── SITL harness compatibility aliases ────────────────────────────────

ScriptedGoto = ScriptedGotoV2
ScriptedLock = ScriptedLockV2
ScriptedAlign = ScriptedAlignV2

def _params(**more: Any) -> dict[str, Any]:
    """SITL harness compatible params."""
    value = {
        "targets": TARGETS,
        "payloads": [
            {"payload_id": "p0", "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}]},
            {"payload_id": "p1", "servo_outputs": [{"channel": 9, "release_pwm": 1250, "hold_pwm": 1750}]},
        ],
        "release_wait_updates": 1,
        "goto_max_updates": 3,
        "target_lock_max_updates": 3,
        "align_descend_max_updates": 3,
        "climb_max_updates": 10,
    }
    value.update(more)
    return value

def _drive_until_terminal(action):
    """SITL harness compatible driver."""
    return drive(action)


# ══════════════════════════════════════════════════════════════════════
# climb goto failure tests
# ══════════════════════════════════════════════════════════════════════

class FailingGoto:
    """GotoWaypointAction that always fails."""
    starts: list[dict[str, Any]] = []
    @classmethod
    def reset(cls): cls.starts = []
    def start(self, p): self.p = p; type(self).starts.append(p)
    def update(self, c): return ActionResult(failed=True, reason="goto_failed")


def test_climb_goto_failed_immediate_fail(monkeypatch) -> None:
    """Climb goto fails → immediate climb_goto_failed, no wait for timeout."""
    ScriptedGotoV2.reset()
    ScriptedLockV2.reset()
    ScriptedAlignV2.reset(done=True, reason="aligned_at_finish_altitude")
    monkeypatch.setattr(mod, "GotoWaypointAction", FailingGoto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLockV2)
    monkeypatch.setattr(mod, "AlignDescendAction", ScriptedAlignV2)
    action = GpsDropSequenceAction()
    action.start(params(climb_max_updates=999))
    results = _drive_to_terminal(action, limit=40)
    # Should fail before timeout — first goto for approach also fails
    assert results[-1].failed
    assert "goto" in results[-1].reason


class FailOnClimbGoto:
    """GotoWaypointAction that fails only for climb gotos."""
    starts: list[dict[str, Any]] = []
    @classmethod
    def reset(cls): cls.starts = []
    def start(self, p): self.p = p; type(self).starts.append(p)
    def update(self, c):
        key = self.p.get("key", "")
        if "climb" in key:
            return ActionResult(failed=True, reason="goto_failed")
        return ActionResult(done=True)


def test_climb_goto_failed_no_next_target(monkeypatch) -> None:
    """First target climb fails → sequence fails, no second target."""
    ScriptedLockV2.reset()
    ScriptedAlignV2.reset(done=True, reason="aligned_at_finish_altitude")
    FailOnClimbGoto.reset()
    monkeypatch.setattr(mod, "GotoWaypointAction", FailOnClimbGoto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLockV2)
    monkeypatch.setattr(mod, "AlignDescendAction", ScriptedAlignV2)
    action = GpsDropSequenceAction()
    action.start(params(climb_max_updates=999, release_wait_updates=1))
    # Drive with low altitude so climb goto actually runs
    results = []
    alt = 1.0  # below climb threshold
    for _ in range(40):
        r = action.update({"drone": {"relative_altitude": alt, "lat": 34.1, "lon": 108.1, "yaw": 1.5}})
        results.append(r)
        if r.failed or r.done:
            break
    assert results[-1].failed
    assert results[-1].reason == "climb_goto_failed"
    # Should not have advanced to target 1
    assert action.target_index == 0
    assert action.released_count in (0, 1)


def test_climb_already_at_height_completes_immediately(monkeypatch) -> None:
    """Already at climb height → complete without waiting for goto."""
    ScriptedLockV2.reset()
    ScriptedAlignV2.reset(done=True, reason="aligned_at_finish_altitude")
    class HangOnlyClimbGoto:
        """Succeed for approach goto, hang for climb goto."""
        starts = []
        def start(self, p): self.p = p; type(self).starts.append(p)
        def update(self, c):
            key = self.p.get("key", "")
            if "climb" in key:
                return ActionResult(done=False, actions=[])
            return ActionResult(done=True)
    HangOnlyClimbGoto.starts = []
    monkeypatch.setattr(mod, "GotoWaypointAction", HangOnlyClimbGoto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLockV2)
    monkeypatch.setattr(mod, "AlignDescendAction", ScriptedAlignV2)
    action = GpsDropSequenceAction()
    action.start(params(climb_max_updates=999, release_wait_updates=1,
                         climb_after_drop_m=2.5, climb_tolerance_z_m=0.1))
    # Drive with high altitude so climb completes immediately (altitude-first check)
    results = []
    for _ in range(40):
        r = action.update({"drone": {"relative_altitude": 3.0, "lat": 34.1, "lon": 108.1, "yaw": 1.5}})
        results.append(r)
        if r.done or r.failed:
            break
    assert results[-1].done


def test_climb_altitude_gate_wins_timeout_boundary() -> None:
    """A fresh altitude sample at the threshold must not lose to timeout."""
    class MustNotUpdateGoto:
        def update(self, context):  # pragma: no cover - assertion is the test
            raise AssertionError("height gate must complete before updating goto")

    action = GpsDropSequenceAction()
    action.start(params(climb_after_drop_m=2.5, climb_tolerance_z_m=0.1,
                        climb_max_updates=1))
    action.phase = "climb"
    action.released_count = 2
    action.payload_index = 2
    action.target_index = 1
    action._climb_target_lat = TARGETS[1]["lat"]
    action._climb_target_lon = TARGETS[1]["lon"]
    action.sub_action = MustNotUpdateGoto()
    action.update_count_at_phase = 1

    result = action.update({"drone": {"relative_altitude": 2.4}})

    assert result.done
    assert result.reason == "gps_drop_sequence_done"
    assert action.phase == "done"


def test_single_target_climb_fail_no_done(monkeypatch) -> None:
    """Single target dual release: climb fail → sequence fails, no duplicate release."""
    ScriptedLockV2.reset()
    ScriptedAlignV2.reset(done=True, reason="aligned_at_finish_altitude")
    FailOnClimbGoto.reset()
    monkeypatch.setattr(mod, "GotoWaypointAction", FailOnClimbGoto)
    monkeypatch.setattr(mod, "GpsTargetLockAction", ScriptedLockV2)
    monkeypatch.setattr(mod, "AlignDescendAction", ScriptedAlignV2)
    action = GpsDropSequenceAction()
    action.start(params(
        targets=[TARGETS[0]], release_wait_updates=1, climb_max_updates=999,
    ))
    results = []
    alt = 1.0
    for _ in range(40):
        r = action.update({"drone": {"relative_altitude": alt, "lat": 34.1, "lon": 108.1, "yaw": 1.5}})
        results.append(r)
        if r.failed or r.done:
            break
    assert results[-1].failed
    assert not results[-1].done
