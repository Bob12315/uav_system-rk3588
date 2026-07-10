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
    assert action_types == [
        ["global_goto"], [], ["yolo_lock_target"], ["flight_command"],
        ["flight_command", "clear_continuous_commands"],
        ["flight_command", "set_servo"], ["flight_command"],
        ["flight_command", "set_servo", "clear_continuous_commands"],
        ["global_goto"], [], ["global_goto"], [], ["yolo_lock_target"],
        ["flight_command"], ["flight_command", "clear_continuous_commands"],
        ["flight_command", "set_servo"], ["flight_command"],
        ["flight_command", "set_servo", "clear_continuous_commands"],
    ]
    assert results[3].actions[0]["params"] == FULL_COMMAND
    for active_index in (3, 13):
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
        assert align_start["config"]["yaw_control_mode"] == "ignore"
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
    assert action.align_cfg["config"]["yaw_control_mode"] == "ignore"
    assert action.align_cfg["config"]["require_target_locked"] is True

    with pytest.raises(ValueError, match="min_altitude_m must be <= finish_altitude_m"):
        GpsDropSequenceAction().start(
            _params(align_descend={"config": {"min_altitude_m": 2.0}})
        )


@pytest.mark.parametrize(
    "config",
    [
        {"yaw_control_mode": "hold"},
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
        [TARGETS[0], {**TARGETS[1], "target_id": "t0"}],
        [TARGETS[0], {**TARGETS[1], "lat": TARGETS[0]["lat"], "lon": TARGETS[0]["lon"]}],
        [TARGETS[0], {**TARGETS[1], "target_id": ""}],
    ],
)
def test_start_rejects_non_distinct_targets(targets: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        GpsDropSequenceAction().start(_params(targets=targets))


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
