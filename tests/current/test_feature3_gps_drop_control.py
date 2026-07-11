from __future__ import annotations

from typing import Any

import pytest

from missions.common.actions import gps_drop_sequence as sequence_module
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.result import ActionResult


TARGETS = [
    {"valid": True, "lat": 34.00001, "lon": 108.00001, "class_name": "bucket", "target_id": "t0"},
    {"valid": True, "lat": 34.00021, "lon": 108.00031, "class_name": "bucket", "target_id": "t1"},
]
PAYLOADS = [
    {"payload_id": "p0", "payload_forward_m": -0.06, "payload_right_m": 0.0,
     "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}]},
    {"payload_id": "p1", "payload_forward_m": 0.06, "payload_right_m": 0.0,
     "servo_outputs": [{"channel": 9, "release_pwm": 1250, "hold_pwm": 1750}]},
]


def _params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "targets": TARGETS,
        "payloads": PAYLOADS,
        "goto_max_updates": 3,
        "target_lock_max_updates": 3,
        "align_descend_max_updates": 3,
        "climb_max_updates": 3,
        "release_wait_updates": 2,
        "goto": {
            "require_velocity_valid": True,
            "max_horizontal_speed_mps": 0.15,
            "max_vertical_speed_mps": 0.10,
        },
    }
    params.update(overrides)
    return params


def _global_action(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_type": "global_goto",
        "params": {"lat": params["lat"], "lon": params["lon"], "alt": params["altitude_m"], "frame": params["frame"]},
        "input_frame": "global",
        "key": params["key"],
        "once": False,
    }


class ScriptedGoto:
    fail_keys: set[str] = set()
    hang_keys: set[str] = set()
    starts: list[dict[str, Any]] = []

    @classmethod
    def reset(cls) -> None:
        cls.fail_keys = set()
        cls.hang_keys = set()
        cls.starts = []

    def start(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        self.calls = 0
        type(self).starts.append(self.params)

    def update(self, context: dict[str, Any]) -> ActionResult:
        self.calls += 1
        key = self.params["key"]
        if key in type(self).fail_keys:
            return ActionResult(failed=True, reason="waypoint_failed")
        if key in type(self).hang_keys or self.calls == 1:
            return ActionResult(actions=[_global_action(self.params)], reason="goto_active")
        return ActionResult(done=True, reason="waypoint_reached")


class ScriptedLock:
    fail_target_ids: set[str] = set()
    starts: list[dict[str, Any]] = []

    @classmethod
    def reset(cls) -> None:
        cls.fail_target_ids = set()
        cls.starts = []

    def start(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        type(self).starts.append(self.params)

    def update(self, context: dict[str, Any]) -> ActionResult:
        target_id = self.params["target"]["id"]
        if target_id in type(self).fail_target_ids:
            return ActionResult(failed=True, reason="gps_target_lock_timeout")
        track_id = 100 + len(type(self).starts) - 1
        return ActionResult(
            actions=[{"action_type": "yolo_lock_target", "params": {"track_id": track_id}}],
            done=True,
            reason="gps_target_locked",
        )


FULL_COMMAND = {
    "type": "flight_command",
    "valid": True,
    "active": True,
    "enable_body": True,
    "vx_cmd": 0.12,
    "vy_cmd": -0.08,
    "vz_cmd": 0.18,
    "yaw_rate_cmd": 0.0,
    "priority": 7,
}


class ScriptedAlign:
    scripts: list[str] = []
    starts: list[dict[str, Any]] = []

    @classmethod
    def reset(cls, scripts: list[str] | None = None) -> None:
        cls.scripts = list(scripts or ["aligned", "aligned"])
        cls.starts = []

    def start(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        self.calls = 0
        self.script = type(self).scripts.pop(0)
        type(self).starts.append(self.params)

    def update(self, context: dict[str, Any]) -> ActionResult:
        self.calls += 1
        if self.script == "active_forever":
            return ActionResult(detail={"command": dict(FULL_COMMAND)}, reason="align_descending")
        if self.script == "child_timeout":
            return ActionResult(failed=True, reason="align_descend_timeout")
        if self.script in {"missing_altitude", "target_lost_timeout"}:
            return ActionResult(failed=True, reason=self.script)
        if self.script == "unexpected_done":
            return ActionResult(done=True, reason="min_altitude_reached")
        if self.calls == 1:
            return ActionResult(detail={"command": dict(FULL_COMMAND)}, reason="align_descending")
        return ActionResult(done=True, reason="aligned_at_finish_altitude", detail={"command": {}})


class FailingPayloadRelease:
    def start(self, params: dict[str, Any]) -> None:
        self.params = params

    def update(self, context: dict[str, Any]) -> ActionResult:
        return ActionResult(failed=True, reason="servo_failed")


@pytest.fixture
def scripted_children(monkeypatch: pytest.MonkeyPatch) -> None:
    ScriptedGoto.reset()
    ScriptedLock.reset()
    ScriptedAlign.reset()
    monkeypatch.setattr(sequence_module, "GotoWaypointAction", ScriptedGoto)
    monkeypatch.setattr(sequence_module, "GpsTargetLockAction", ScriptedLock)
    monkeypatch.setattr(sequence_module, "AlignDescendAction", ScriptedAlign)


def _types(result: ActionResult) -> list[str]:
    return [action["action_type"] for action in result.actions]


def _servo_pwms(result: ActionResult) -> list[int]:
    return [action["params"]["pwm"] for action in result.actions if action["action_type"] == "set_servo"]


def _drive_until_terminal(action: GpsDropSequenceAction, limit: int = 80) -> list[ActionResult]:
    results: list[ActionResult] = []
    for _ in range(limit):
        result = action.update({})
        results.append(result)
        if result.done or result.failed:
            return results
    raise AssertionError("sequence did not reach a terminal state")


def test_dual_target_happy_path_from_start(scripted_children: None) -> None:
    action = GpsDropSequenceAction()
    action.start(_params())
    results = _drive_until_terminal(action)

    assert results[-1].done
    assert results[-1].reason == "gps_drop_sequence_done"
    assert (action.released_count, action.payload_index, action.target_index) == (2, 2, 1)

    action_types = [_types(result) for result in results]
    # Verify both releases produce climb phase (not immediately done)
    assert "gps_drop_climb_start" in [r.reason for r in results]
    # Verify sequence ends correctly
    assert results[-1].done
    assert results[-1].reason == "gps_drop_sequence_done"
    assert (action.released_count, action.payload_index, action.target_index) == (2, 2, 1)
    # Verify climb phases were entered twice (once per release)
    climb_results = [r for r in results if r.reason == "gps_drop_climb_start"]
    assert len(climb_results) == 2
    assert results[3].actions[0]["params"] == FULL_COMMAND
    for active_index in (3, 14):
        command = results[active_index].actions[0]["params"]
        assert "yaw_hold_rad" not in command
        assert "velocity_yaw_rad" not in command
    for terminal_index in (4, 14):
        assert _servo_pwms(results[terminal_index]) == []
        assert results[terminal_index].detail["release_reason"] == "aligned_release"
    assert _servo_pwms(results[5]) == [1200]
    assert _servo_pwms(results[7]) == [1700]
    assert _servo_pwms(results[15]) == [1250]
    assert _servo_pwms(results[17]) == [1750]

    goto_starts = ScriptedGoto.starts
    assert [(item["lat"], item["lon"], item["altitude_m"]) for item in goto_starts] == [
        (TARGETS[0]["lat"], TARGETS[0]["lon"], 3.0),
        (TARGETS[0]["lat"], TARGETS[0]["lon"], 5.0),
        (TARGETS[1]["lat"], TARGETS[1]["lon"], 3.0),
        (TARGETS[1]["lat"], TARGETS[1]["lon"], 5.0),
    ]
    assert all(item["target_frame"] == "global" for item in goto_starts)
    assert all(item["waypoint_mode"] == "absolute" for item in goto_starts)
    assert all(item["yaw_mode"] == "hold" for item in goto_starts)
    assert all(item["require_velocity_valid"] is True for item in goto_starts)
    assert all(item["max_horizontal_speed_mps"] == 0.15 for item in goto_starts)
    assert all(item["max_vertical_speed_mps"] == 0.10 for item in goto_starts)
    assert [item["target"]["id"] for item in ScriptedLock.starts] == ["t0", "t1"]
    for align_start in ScriptedAlign.starts:
        assert align_start["finish_policy"] == "require_alignment_or_timeout"
        assert align_start["config"]["yaw_control_mode"] == "hold_entry_attitude"
        assert align_start["config"]["require_target_locked"] is True
    assert [item["config"]["payload_forward_m"] for item in ScriptedAlign.starts] == [-0.06, 0.06]
    assert [item["config"]["payload_right_m"] for item in ScriptedAlign.starts] == [0.0, 0.0]
    assert "payload_forward_m" not in action.align_cfg["config"]
    assert "payload_right_m" not in action.align_cfg["config"]
    assert not any(kind == "local_position" for kinds in action_types for kind in kinds)
    assert sum(pwm in {1200, 1250} for result in results for pwm in _servo_pwms(result)) == 2
    assert sum(pwm in {1700, 1750} for result in results for pwm in _servo_pwms(result)) == 2


@pytest.mark.parametrize("timeout_kind", ["sequence", "child"])
def test_align_timeout_stops_then_releases_next_tick(
    scripted_children: None, timeout_kind: str
) -> None:
    ScriptedAlign.reset(["active_forever" if timeout_kind == "sequence" else "child_timeout"])
    action = GpsDropSequenceAction()
    action.start(_params(align_descend_max_updates=1))

    results: list[ActionResult] = []
    while action.phase != "release":
        results.append(action.update({}))
    terminal = results[-1]
    assert _types(terminal) == ["flight_command", "clear_continuous_commands"]
    assert _servo_pwms(terminal) == []
    assert terminal.detail["release_reason"] == "align_timeout_release"

    release = action.update({})
    assert _types(release) == ["flight_command", "set_servo"]
    assert _servo_pwms(release) == [1200]
    assert release.detail["release_reason"] == "align_timeout_release"


@pytest.mark.parametrize(
    ("scenario", "expected_reason"),
    [
        ("goto_timeout", "goto_timeout"),
        ("goto_failed", "goto_failed"),
        ("lock", "no_lockable_drop_targets"),
        ("missing_altitude", "missing_altitude"),
        ("target_lost_timeout", "target_lost_timeout"),
        ("unexpected_done", "align_unexpected_done"),
        ("payload", "payload_release_failed"),
        ("climb_timeout", "climb_timeout"),
        ("climb_failed", "climb_failed"),
    ],
)
def test_failures_are_stably_latched(
    scripted_children: None,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_reason: str,
) -> None:
    if scenario == "goto_timeout":
        ScriptedGoto.hang_keys = {"gps_drop_goto_0"}
    elif scenario == "goto_failed":
        ScriptedGoto.fail_keys = {"gps_drop_goto_0"}
    elif scenario == "lock":
        ScriptedLock.fail_target_ids = {"t0"}
    elif scenario in {"missing_altitude", "target_lost_timeout", "unexpected_done"}:
        ScriptedAlign.reset([scenario])
    elif scenario == "payload":
        monkeypatch.setattr(sequence_module, "PayloadReleaseAction", FailingPayloadRelease)
    elif scenario == "climb_timeout":
        ScriptedGoto.hang_keys = {"gps_drop_climb_0"}
    elif scenario == "climb_failed":
        ScriptedGoto.fail_keys = {"gps_drop_climb_0"}

    action = GpsDropSequenceAction()
    action.start(_params(goto_max_updates=1, climb_max_updates=1))
    results = _drive_until_terminal(action)
    failure = results[-1]
    assert failure.failed and failure.reason == expected_reason
    assert _types(failure) == ["flight_command", "clear_continuous_commands"]
    snapshot = (action.phase, action.target_index, action.payload_index, action.released_count)

    for _ in range(2):
        repeated = action.update({})
        assert repeated.failed and repeated.reason == expected_reason
        assert repeated.actions == []
        assert (action.phase, action.target_index, action.payload_index, action.released_count) == snapshot


def test_strict_min_altitude_is_nested_and_rejects_above_finish(scripted_children: None) -> None:
    action = GpsDropSequenceAction()
    action.start(_params())
    assert action.align_cfg["finish_policy"] == "require_alignment_or_timeout"
    assert action.align_cfg["config"]["min_altitude_m"] == 1.3
    assert action.align_cfg["config"]["yaw_control_mode"] == "hold_entry_attitude"
    assert action.align_cfg["config"]["require_target_locked"] is True

    with pytest.raises(ValueError, match="min_altitude_m must be <= finish_altitude_m"):
        GpsDropSequenceAction().start(
            _params(align_descend={"config": {"min_altitude_m": 2.0}})
        )


@pytest.mark.parametrize(
    "config",
    [
        {"yaw_control_mode": "hold"},
        {"yaw_control_mode": "ignore"},
        {"require_target_locked": False},
    ],
)
def test_gps_sequence_rejects_unsafe_align_overrides(config: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        GpsDropSequenceAction().start(_params(align_descend={"config": config}))


def test_gps_sequence_rejects_legacy_finish_policy() -> None:
    with pytest.raises(ValueError, match="finish_policy"):
        GpsDropSequenceAction().start(
            _params(align_descend={"finish_policy": "legacy"})
        )


@pytest.mark.parametrize("field", ["payload_forward_m", "payload_right_m"])
def test_gps_sequence_rejects_nonfinite_payload_offsets(field: str) -> None:
    payloads = [dict(PAYLOADS[0]), dict(PAYLOADS[1])]
    payloads[0][field] = float("nan")
    with pytest.raises(ValueError, match=field):
        GpsDropSequenceAction().start(_params(payloads=payloads))


def test_target_unlocked_never_descends_or_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ScriptedGoto.reset()
    ScriptedLock.reset()
    monkeypatch.setattr(sequence_module, "GotoWaypointAction", ScriptedGoto)
    monkeypatch.setattr(sequence_module, "GpsTargetLockAction", ScriptedLock)
    action = GpsDropSequenceAction()
    action.start(
        _params(
            align_descend_max_updates=20,
            align_descend={"lost_timeout_updates": 1, "max_retries": 0},
        )
    )
    context = {
        "relative_altitude": 5.0,
        "target_valid": True,
        "target_locked": False,
        "control_allowed": True,
        "ex_cam": 0.0,
        "ey_cam": 0.0,
        "drone": {"relative_altitude": 5.0, "attitude_valid": True, "yaw": 0.7},
    }

    results = _drive_until_terminal_with_context(action, context)

    assert results[-1].failed is True
    assert results[-1].reason == "target_lost_timeout"
    assert _types(results[-1]) == ["flight_command", "clear_continuous_commands"]
    assert not any("set_servo" in _types(result) for result in results)
    for result in results:
        for emitted in result.actions:
            if emitted["action_type"] != "flight_command":
                continue
            command = emitted["params"]
            assert command["vx_cmd"] == pytest.approx(0.0)
            assert command["vy_cmd"] == pytest.approx(0.0)
            assert command["vz_cmd"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "targets",
    [
        [TARGETS[0], {**TARGETS[1], "lat": TARGETS[0]["lat"], "lon": TARGETS[0]["lon"]}],
    ],
)
def test_start_rejects_non_distinct_targets(targets: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        GpsDropSequenceAction().start(_params(targets=targets))


def test_start_accepts_one_target() -> None:
    """With a single valid GPS target, start succeeds in single_target_dual_release mode."""
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    assert action.execution_mode == "single_target_dual_release"
    assert len(action.targets) == 1
    assert action.target_index == 0
    assert action.payload_index == 0
    assert action.released_count == 0


def test_start_rejects_zero_targets() -> None:
    """Zero valid GPS targets must raise ValueError."""
    with pytest.raises(ValueError, match="targets must contain 1 or 2 entries"):
        GpsDropSequenceAction().start(_params(targets=[]))
    # Also test: all invalid targets (e.g., all valid=False)
    invalid_two = [
        {**TARGETS[0], "valid": False},
        {**TARGETS[1], "valid": False},
    ]
    with pytest.raises(ValueError, match="at least 1 valid GPS target required"):
        GpsDropSequenceAction().start(_params(targets=invalid_two))


def _drive_until_terminal_with_context(
    action: GpsDropSequenceAction,
    context: dict[str, Any],
    limit: int = 40,
) -> list[ActionResult]:
    results: list[ActionResult] = []
    for _ in range(limit):
        result = action.update(context)
        results.append(result)
        if result.done or result.failed:
            return results
    raise AssertionError("sequence did not reach a terminal state")


# ── single-target dual-release tests ──────────────────────────────────


def test_single_target_dual_release_happy_path(scripted_children: None) -> None:
    """Single target: goto→lock→align→dual release→terminal climb→done."""
    ScriptedAlign.reset(["aligned"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    assert action.execution_mode == "single_target_dual_release"

    results = _drive_until_terminal(action)

    # Terminal done after climb
    assert results[-1].done
    assert results[-1].reason == "gps_drop_sequence_done"
    # Final detail
    assert results[-1].detail["dual_release"] is True
    assert results[-1].detail["execution_mode"] == "single_target_dual_release"
    assert results[-1].detail["climb_is_terminal"] is True

    # State after completion
    assert action.released_count == 2
    assert action.payload_index == 2
    assert action.target_index == 0
    assert action.execution_mode == "single_target_dual_release"
    assert action.phase == "done"

    # Two gotos: approach + terminal climb
    goto_starts = ScriptedGoto.starts
    assert len(goto_starts) == 2
    assert goto_starts[0]["lat"] == TARGETS[0]["lat"]
    assert goto_starts[0]["lon"] == TARGETS[0]["lon"]
    assert goto_starts[0]["altitude_m"] == 3.0  # approach
    assert goto_starts[1]["altitude_m"] == 5.0  # climb

    # One lock, one align
    assert len(ScriptedLock.starts) == 1
    assert ScriptedLock.starts[0]["target"]["id"] == "t0"
    assert len(ScriptedAlign.starts) == 1

    # One terminal climb
    climb_results = [r for r in results if r.reason == "gps_drop_climb_start"]
    assert len(climb_results) == 1

    # release tick has both set_servo
    release_results = [r for r in results if r.reason == "gps_drop_releasing"]
    assert len(release_results) >= 2
    release_tick = release_results[0]
    servos_release = [
        a for a in release_tick.actions if a["action_type"] == "set_servo"
    ]
    assert len(servos_release) == 2
    channels = sorted(a["params"]["channel"] for a in servos_release)
    pwms_release = sorted(a["params"]["pwm"] for a in servos_release)
    assert channels == [8, 9]
    assert pwms_release == [1200, 1250]

    # hold tick has both set_servo (in climb_start transition, NOT terminal)
    climb_start = climb_results[0]
    servos_hold = [
        a for a in climb_start.actions if a["action_type"] == "set_servo"
    ]
    assert len(servos_hold) == 2
    channels_hold = sorted(a["params"]["channel"] for a in servos_hold)
    pwms_hold = sorted(a["params"]["pwm"] for a in servos_hold)
    assert channels_hold == [8, 9]
    assert pwms_hold == [1700, 1750]

    # climb_start is NOT done=True (climb must complete first)
    assert climb_start.done is False


def test_single_target_align_timeout_dual_release(
    scripted_children: None,
) -> None:
    """Single target align timeout (child) → zero→clear→dual release→climb→done."""
    ScriptedAlign.reset(["child_timeout"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    assert action.execution_mode == "single_target_dual_release"

    results = _drive_until_terminal(action)
    assert results[-1].done
    assert results[-1].reason == "gps_drop_sequence_done"
    assert action.released_count == 2
    assert action.payload_index == 2

    # Verify zero velocity + clear before release
    timeout_transition = None
    for r in results:
        if r.reason == "gps_drop_align_timeout_release":
            timeout_transition = r
            break
    assert timeout_transition is not None
    types = _types(timeout_transition)
    assert "flight_command" in types
    assert "clear_continuous_commands" in types
    assert timeout_transition.detail["release_reason"] == "align_timeout_release"

    # Verify dual release + terminal climb happened
    servos = []
    for r in results:
        for a in r.actions:
            if a["action_type"] == "set_servo":
                servos.append(a)
    assert len(servos) == 4  # 2 release + 2 hold

    # Verify terminal climb occurred
    climb_results = [r for r in results if r.reason == "gps_drop_climb_start"]
    assert len(climb_results) == 1


def test_single_target_sequence_align_timeout_dual_release(
    scripted_children: None,
) -> None:
    """Single target parent align_descend_max_updates → dual release→climb→done."""
    ScriptedAlign.reset(["active_forever"])
    action = GpsDropSequenceAction()
    action.start(
        _params(targets=[TARGETS[0]], align_descend_max_updates=1)
    )
    assert action.execution_mode == "single_target_dual_release"

    results = _drive_until_terminal(action)
    assert results[-1].done
    assert results[-1].reason == "gps_drop_sequence_done"
    assert action.released_count == 2

    # Verify zero velocity + clear before release
    timeout_transition = None
    for r in results:
        if r.reason == "gps_drop_align_timeout_release":
            timeout_transition = r
            break
    assert timeout_transition is not None
    types = _types(timeout_transition)
    assert "clear_continuous_commands" in types

    # Verify terminal climb occurred
    climb_results = [r for r in results if r.reason == "gps_drop_climb_start"]
    assert len(climb_results) == 1


def test_single_target_missing_altitude_no_release(
    scripted_children: None,
) -> None:
    """Single target missing_altitude → failed, no servo release, no climb."""
    ScriptedAlign.reset(["missing_altitude"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    assert action.execution_mode == "single_target_dual_release"

    results = _drive_until_terminal(action)
    assert results[-1].failed
    assert results[-1].reason == "missing_altitude"
    assert action.released_count == 0

    # No set_servo, no climb
    servos = []
    for r in results:
        for a in r.actions:
            if a["action_type"] == "set_servo":
                servos.append(a)
    assert len(servos) == 0
    assert action.phase == "failed"


def test_single_target_lost_timeout_no_release(
    scripted_children: None,
) -> None:
    """Single target target_lost_timeout → failed, no servo release, no climb."""
    ScriptedAlign.reset(["target_lost_timeout"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    assert action.execution_mode == "single_target_dual_release"

    results = _drive_until_terminal(action)
    assert results[-1].failed
    assert results[-1].reason == "target_lost_timeout"
    assert action.released_count == 0

    servos = []
    for r in results:
        for a in r.actions:
            if a["action_type"] == "set_servo":
                servos.append(a)
    assert len(servos) == 0
    assert action.phase == "failed"


def test_single_target_detail_fields(scripted_children: None) -> None:
    """Detail includes execution_mode, dual_release, climb info."""
    ScriptedAlign.reset(["aligned"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    results = _drive_until_terminal(action)

    final_detail = results[-1].detail
    assert final_detail["done"] is True
    assert final_detail["execution_mode"] == "single_target_dual_release"
    assert final_detail["dual_release"] is True
    assert final_detail["target_count"] == 1
    assert final_detail["payload_count"] == 2
    assert final_detail["released_count"] == 2
    assert final_detail["target_index"] == 0
    assert final_detail["payload_index"] == 2
    assert final_detail["climb_is_terminal"] is True
    assert final_detail["next_after_climb"] == "sequence_done"
    assert "phase" in final_detail
    assert "release_reason" in final_detail
    assert "climb_after_drop_m" in final_detail


def test_payload_release_multi_channel_regression(
    scripted_children: None,
) -> None:
    """PayloadReleaseAction with multi-channel servo_outputs works with climb."""
    ScriptedAlign.reset(["aligned"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    results = _drive_until_terminal(action)

    # Collect all set_servo actions
    all_servos = []
    for r in results:
        for a in r.actions:
            if a["action_type"] == "set_servo":
                all_servos.append(a["params"])

    assert len(all_servos) == 4
    release_pwms = [s["pwm"] for s in all_servos[:2]]
    hold_pwms = [s["pwm"] for s in all_servos[2:]]
    assert sorted(release_pwms) == [1200, 1250]
    assert sorted(hold_pwms) == [1700, 1750]


def test_single_target_no_yaw_in_align_commands(
    scripted_children: None,
) -> None:
    """V2 align commands must not contain yaw_hold_rad or velocity_yaw_rad."""
    ScriptedAlign.reset(["aligned"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    results = _drive_until_terminal(action)

    for r in results:
        for a in r.actions:
            if a["action_type"] == "flight_command":
                params_param = a["params"]
                assert "yaw_hold_rad" not in params_param
                assert "velocity_yaw_rad" not in params_param

    assert ScriptedAlign.starts[0]["config"]["yaw_control_mode"] == "hold_entry_attitude"


def test_dual_target_still_sequential(scripted_children: None) -> None:
    """Two targets should still run dual_target_sequential with climb between."""
    action = GpsDropSequenceAction()
    action.start(_params(targets=TARGETS))
    assert action.execution_mode == "dual_target_sequential"
    assert action.target_index == 0

    results = _drive_until_terminal(action)
    assert results[-1].done
    assert results[-1].reason == "gps_drop_sequence_done"
    assert action.released_count == 2
    assert action.payload_index == 2
    assert action.target_index == 1

    assert results[-1].detail["dual_release"] is False
    assert results[-1].detail["execution_mode"] == "dual_target_sequential"

    climb_results = [r for r in results if r.reason == "gps_drop_climb_start"]
    assert len(climb_results) == 2

    assert len(ScriptedGoto.starts) == 4
    assert len(ScriptedLock.starts) == 2
    assert len(ScriptedAlign.starts) == 2


# ── offset / priority / pre-validation tests ─────────────────────────


def test_single_target_uses_first_payload_offset(
    scripted_children: None,
) -> None:
    """Single-target align must use payload_1 offset, not average."""
    ScriptedAlign.reset(["aligned"])
    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]]))
    _drive_until_terminal(action)

    assert len(ScriptedAlign.starts) == 1
    align_start = ScriptedAlign.starts[0]
    assert align_start["config"]["payload_forward_m"] == -0.06
    assert align_start["config"]["payload_right_m"] == 0.0


def test_duplicate_servo_channel_rejected_in_start() -> None:
    """Duplicate servo channels across payloads must raise ValueError in start()."""
    dup_payloads = [
        {"payload_id": "p0", "payload_forward_m": -0.06, "payload_right_m": 0.0,
         "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}]},
        {"payload_id": "p1", "payload_forward_m": 0.06, "payload_right_m": 0.0,
         "servo_outputs": [{"channel": 8, "release_pwm": 1250, "hold_pwm": 1750}]},
    ]
    with pytest.raises(ValueError, match="duplicate servo channel"):
        GpsDropSequenceAction().start(
            _params(targets=[TARGETS[0]], payloads=dup_payloads)
        )


def test_single_target_priority_min_servo_actions(
    scripted_children: None,
) -> None:
    """Both set_servo in joint release use min(p1, p2) priority."""
    payloads = [
        {"payload_id": "p0", "payload_forward_m": -0.06, "payload_right_m": 0.0,
         "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}],
         "priority": 2},
        {"payload_id": "p1", "payload_forward_m": 0.06, "payload_right_m": 0.0,
         "servo_outputs": [{"channel": 9, "release_pwm": 1250, "hold_pwm": 1750}],
         "priority": 5},
    ]
    ScriptedAlign.reset(["aligned"])
    ScriptedGoto.reset()
    ScriptedLock.reset()
    ScriptedAlign.reset()

    action = GpsDropSequenceAction()
    action.start(_params(targets=[TARGETS[0]], payloads=payloads))
    results = _drive_until_terminal(action)

    # Collect all set_servo actions
    servos = [
        a for r in results for a in r.actions
        if a["action_type"] == "set_servo"
    ]
    assert len(servos) == 4
    for s in servos:
        assert s["priority"] == 2  # min(2, 5)


# ── dual target regression ───────────────────────────────────────────


def test_dual_target_regression_full_flow(scripted_children: None) -> None:
    """Dual target: 2 approach gotos, 2 climbs, 2 locks, 2 aligns, 2 releases."""
    action = GpsDropSequenceAction()
    action.start(_params(targets=TARGETS))
    results = _drive_until_terminal(action)

    assert results[-1].done
    assert action.released_count == 2
    assert action.target_index == 1
    assert action.payload_index == 2

    # 2 approach gotos + 2 climbs = 4
    assert len(ScriptedGoto.starts) == 4
    assert len(ScriptedLock.starts) == 2
    assert len(ScriptedAlign.starts) == 2

    # No dual_release flag
    assert results[-1].detail["dual_release"] is False
    assert results[-1].detail["execution_mode"] == "dual_target_sequential"
