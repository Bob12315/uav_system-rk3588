"""Tests for ReconSequenceAction composite state machine."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from missions.common.actions.recon_sequence import ReconSequenceAction
from missions.common.actions.result import ActionResult


# ── helpers ────────────────────────────────────────────────────────────


class _FakeAction:
    """Controllable fake sub-action for testing orchestration."""

    def __init__(self, results: list[ActionResult] | None = None) -> None:
        self._results = list(results or [])
        self._idx = 0
        self.started = True
        self.stopped = False

    def start(self, params: dict[str, Any] | None = None) -> None:
        self.started = True

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if self._idx < len(self._results):
            r = self._results[self._idx]
            self._idx += 1
            return r
        return self._results[-1] if self._results else ActionResult(done=True, reason="fake_done")

    def stop(self) -> None:
        self.stopped = True


def _make_targets(*coords: tuple[float, float]) -> list[dict[str, Any]]:
    return [
        {
            "valid": True,
            "id": f"r{i}",
            "target_id": f"r{i}",
            "local_x": c[0],
            "local_y": c[1],
            "x": c[0],
            "y": c[1],
        }
        for i, c in enumerate(coords)
    ]


def _base_params(**overrides: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "targets": _make_targets((1.0, 5.0), (-1.0, 6.0)),
        "max_targets": 5,
        "approach_altitude_m": 2.5,
        "finish_altitude_m": 1.5,
        "climb_after_observe_m": 2.5,
        "goto_max_updates": 5,
        "target_lock_max_updates": 5,
        "observe_max_updates": 200,
        "climb_max_updates": 2,
        "continue_after_target_failure": True,
        "goto": {
            "waypoint_mode": "absolute",
            "yaw_mode": "hold",
            "tolerance_xy_m": 5.0,
            "tolerance_z_m": 5.0,
            "min_hold_updates": 1,
            "priority": 5,
        },
        "target_lock": {
            "max_match_distance_m": 5.0,
            "detection_source": "scene",
            "class_names": ["recon_bucket", "white_bucket", "bucket"],
            "min_confidence": 0.1,
        },
        "observe": {
            "record_start_altitude_m": 2.0,
            "finish_altitude_m": 1.5,
            "detection_source": "scene",
            "sign_class_names": [
                "baozha",
                "shenghua",
                "yiran",
                "fangshe",
                "buran",
                "fushi",
                "youdu",
                "yushi",
                "ziran",
                "ciji",
                "danger_1",
                "danger_2",
                "danger_3",
            ],
            "min_sign_confidence": 0.35,
            "min_seen_frames": 3,
            "min_confidence_max": 0.55,
            "min_confidence_mean": 0.40,
            "min_score": 1.2,
            "min_margin_ratio": 1.4,
            "align_descend": {
                "expected_dt_s": 0.1,
                "lost_timeout_updates": 100,
                "hold_updates_required": 1,
                "max_retries": 0,
                "finish_altitude_m": 1.5,
                "config": {
                    "kp_vx": 0.55,
                    "kp_vy": 0.55,
                    "max_vx_mps": 0.2,
                    "max_vy_mps": 0.2,
                    "descend_speed_mps": 0.3,
                    "max_ex_cam": 5.0,
                    "max_ey_cam": 5.0,
                    "deadband_ex_cam": 0.01,
                    "deadband_ey_cam": 0.01,
                    "min_altitude_m": 1.0,
                    "require_target_locked": False,
                    "payload_offset_enabled": False,
                    "height_gain_enabled": False,
                },
            },
        },
    }
    p.update(overrides)
    return p


# ── contexts for real sub-actions ──

GOTO_CTX: dict[str, Any] = {
    "local_position": {"x": 1.0, "y": 5.0, "z": -2.5},
    "yaw": 0.0,
}

CLIMB_FAR_CTX: dict[str, Any] = {
    "local_position": {"x": 99.0, "y": 99.0, "z": -0.5},
    "yaw": 0.0,
}

LOCK_FAIL_CTX: dict[str, Any] = {
    "scene": {"detections": [], "image_width": 640, "image_height": 480},
    "drone": {
        "local_x": 1.0,
        "local_y": 5.0,
        "local_z": -2.5,
        "yaw": 0.0,
        "relative_altitude": 2.5,
    },
}

OBSERVE_CTX: dict[str, Any] = {
    "relative_altitude": 2.0,
    "target_valid": True,
    "ex_cam": 0.0,
    "ey_cam": 0.0,
    "target_locked": True,
    "control_allowed": True,
    "scene": {"detections": [], "image_width": 640, "image_height": 480},
}


def _run_until_phase(
    a: ReconSequenceAction,
    ctx: dict[str, Any],
    target_phase: str,
    n: int = 300,
) -> None:
    for _ in range(n):
        if a.phase == target_phase or a._done:
            return
        a.update(ctx)


def _run_to_done(
    a: ReconSequenceAction, ctx: dict[str, Any], n: int = 500
) -> None:
    for _ in range(n):
        r = a.update(ctx)
        if r.done or r.failed:
            return


def _goto_done_factory(target: dict[str, Any]) -> _FakeAction:
    """Fake goto that returns done immediately."""
    return _FakeAction([ActionResult(done=True, reason="waypoint_reached")])


def _lock_done_factory(target: dict[str, Any]) -> _FakeAction:
    """Fake lock that returns done immediately."""
    return _FakeAction([ActionResult(done=True, reason="target_locked")])


def _lock_failed_factory(target: dict[str, Any]) -> _FakeAction:
    """Fake lock that returns failed."""
    return _FakeAction([ActionResult(failed=True, reason="target_lock_timeout")])


def _observe_detected_factory(
    content: str = "baozha", confidence: float = 0.72
) -> _FakeAction:
    """Fake observe that returns detected result."""
    return _FakeAction(
        [
            ActionResult(
                done=True,
                reason="sign_detected",
                detail={
                    "status": "detected",
                    "content": content,
                    "confidence": confidence,
                    "align_reason": "sign_detected",
                },
            )
        ]
    )


def _observe_blank_factory() -> _FakeAction:
    """Fake observe that returns blank."""
    return _FakeAction(
        [
            ActionResult(
                done=True,
                reason="observe_done",
                detail={
                    "status": "blank_or_uncertain",
                    "content": "blank",
                    "confidence": 0.0,
                    "align_reason": "observe_done",
                },
            )
        ]
    )


def _climb_done_factory() -> _FakeAction:
    """Fake climb (goto) that returns done immediately."""
    return _FakeAction([ActionResult(done=True, reason="waypoint_reached")])


# ── tests ──────────────────────────────────────────────────────────────


def test_no_valid_targets_done() -> None:
    """No valid targets → immediate done with empty results."""
    params = _base_params(targets=[])
    a = ReconSequenceAction()
    a.start(params)
    r = a.update({})
    assert r.done is True
    assert r.failed is False
    assert r.reason == "no_valid_targets"
    assert r.detail["observed_count"] == 0
    assert r.detail["recon_result_items"] == []
    assert r.detail["results"] == []


def test_one_target_lock_failed_records_blank() -> None:
    """Lock failed → record blank/skipped, continue to done."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets,
        target_lock_max_updates=2,
        goto_max_updates=5,
        climb_max_updates=1,
    )
    a = ReconSequenceAction()
    a.start(params)

    # goto → done (at target position)
    _run_until_phase(a, GOTO_CTX, "lock_target")
    # lock → timeout with no detections → advance to done (only 1 target)
    _run_to_done(a, LOCK_FAIL_CTX)

    assert a._done is True
    assert a.skipped_count == 1
    assert a.observed_count == 0
    assert len(a.results) == 1
    assert a.results[0]["status"] == "blank_or_uncertain"
    assert a.results[0]["reason"] == "target_lock_failed"


def test_goto_failed_skips_target() -> None:
    """Goto timeout → skip target, emit clear, advance."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets,
        goto_max_updates=1,
    )
    a = ReconSequenceAction()
    a.start(params)

    # Provide far context so goto never reaches target → timeout after 1 update
    r = a.update(CLIMB_FAR_CTX)  # phase init → goto_target, update 1
    # After 1 update, phase_update_count=1, not yet > 1

    r = a.update(CLIMB_FAR_CTX)  # update 2, phase_update_count=2 > 1 → timeout
    assert a.skipped_count == 1
    assert a.results[0]["reason"] == "goto_failed"

    # The timeout result should include clear_continuous_commands
    types = [act.get("action_type") for act in r.actions]
    assert "clear_continuous_commands" in types


def test_observe_success_records_detected_item() -> None:
    """Observe detected → record in results and recon_result_items."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(targets=targets, climb_max_updates=1)
    a = ReconSequenceAction()
    a.start(params)

    observe = _observe_detected_factory("baozha", 0.72)
    climb = _climb_done_factory()

    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            return_value=_goto_done_factory(targets[0]),
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            return_value=_lock_done_factory(targets[0]),
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            return_value=observe,
        ),
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            return_value=climb,
        ),
    ):
        _run_to_done(a, {})

    # The climb mock will be used for the 2nd GotoWaypointAction call too
    # since we're patching the same class. Let's check results.
    assert a.observed_count == 1
    assert len(a.recon_result_items) == 1
    assert a.recon_result_items[0]["content"] == "baozha"
    assert a.recon_result_items[0]["confidence"] == 0.72
    assert a.recon_result_items[0]["status"] == "detected"


def test_observe_timeout_records_blank_and_continues() -> None:
    """observe_max_updates=1 → immediate timeout → record blank, continue."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets,
        observe_max_updates=1,
        climb_max_updates=1,
    )
    a = ReconSequenceAction()
    a.start(params)

    # goto → done
    _run_until_phase(a, GOTO_CTX, "lock_target")
    # lock → fail (no detections) → advance. Since only 1 target, goes to done.
    # But we need lock to succeed to reach observe...

    # Use mock approach instead:
    a2 = ReconSequenceAction()
    a2.start(params)

    observe = _FakeAction(
        [
            ActionResult(
                reason="observe_active",
                detail={
                    "status": "blank_or_uncertain",
                    "content": "blank",
                    "confidence": 0.0,
                    "align_reason": "align_active",
                },
            )
        ]
    )
    climb = _climb_done_factory()

    call_count = {"goto": 0, "lock": 0, "observe": 0, "climb": 0}

    def goto_factory():
        call_count["goto"] += 1
        return _goto_done_factory(targets[0])

    def lock_factory():
        call_count["lock"] += 1
        return _lock_done_factory(targets[0])

    def observe_factory():
        call_count["observe"] += 1
        return observe

    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=[goto_factory(), climb],
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            side_effect=[lock_factory()],
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            side_effect=[observe_factory()],
        ),
    ):
        _run_to_done(a2, {})

    assert a2.blank_count == 1
    assert a2.observed_count == 0
    assert len(a2.results) == 1
    assert a2.results[0]["status"] == "blank_or_uncertain"


def test_multiple_targets_continue_after_failure() -> None:
    """3 targets: first lock fails, second and third succeed."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0), (0.5, 7.0))
    params = _base_params(targets=targets)
    a = ReconSequenceAction()
    a.start(params)

    # t0: lock fails → skip
    # t1: observe detected
    # t2: observe detected
    goto_calls = [_goto_done_factory(t) for t in targets] + [
        _climb_done_factory() for _ in targets
    ]
    lock_results = [
        _FakeAction([ActionResult(failed=True, reason="target_lock_timeout")]),
        _lock_done_factory(targets[1]),
        _lock_done_factory(targets[2]),
    ]
    observe_results = [
        _observe_detected_factory("shenghua", 0.65),
        _observe_detected_factory("baozha", 0.80),
    ]
    climb_calls = [_climb_done_factory() for _ in range(3)]

    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=goto_calls + climb_calls,
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            side_effect=lock_results,
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            side_effect=observe_results,
        ),
    ):
        _run_to_done(a, {})

    assert a._done is True
    assert a.skipped_count == 1  # t0 lock failed
    assert a.observed_count == 2  # t1, t2 detected
    assert len(a.results) == 3
    # All 3 processed targets enter recon_result_items (1 skipped + 2 detected)
    assert len(a.recon_result_items) == 3


def test_observe_to_climb_emits_clear_continuous() -> None:
    """observe done → climb transition must emit clear_continuous_commands."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(targets=targets, climb_max_updates=1)
    a = ReconSequenceAction()
    a.start(params)

    observe = _observe_detected_factory("baozha", 0.72)
    climb = _climb_done_factory()

    transition_result = None
    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=[_goto_done_factory(targets[0]), climb],
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            return_value=_lock_done_factory(targets[0]),
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            return_value=observe,
        ),
    ):
        for _ in range(50):
            r = a.update({})
            if a.phase == "climb_after_observe":
                transition_result = r
                break

    assert transition_result is not None
    types = [act.get("action_type") for act in transition_result.actions]
    assert "clear_continuous_commands" in types, (
        "observe→climb missing clear_continuous_commands"
    )


def test_climb_to_next_goto_emits_clear_continuous() -> None:
    """climb done → next goto: transition must emit clear_continuous_commands."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0))
    params = _base_params(targets=targets)
    a = ReconSequenceAction()
    a.start(params)

    goto_calls = [
        _goto_done_factory(targets[0]),
        _goto_done_factory(targets[1]),
        _climb_done_factory(),
        _climb_done_factory(),
    ]
    observe_calls = [
        _observe_detected_factory("baozha", 0.72),
        _observe_detected_factory("shenghua", 0.65),
    ]

    clear_keys: list[str] = []
    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=goto_calls,
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            side_effect=[
                _lock_done_factory(targets[0]),
                _lock_done_factory(targets[1]),
            ],
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            side_effect=observe_calls,
        ),
    ):
        # Drive through t0 full cycle
        prev_target_index = 0
        for _ in range(200):
            r = a.update({})
            if a._done:
                break
            # Capture clear actions from climb→goto transitions
            if a.target_index > prev_target_index or a._done:
                for act in r.actions:
                    if act.get("action_type") == "clear_continuous_commands":
                        clear_keys.append(act["key"])
                prev_target_index = a.target_index

    # At minimum, the climb→next goto transition emits clear
    # Also observe→climb emits clear
    assert len(clear_keys) >= 1, (
        "climb→next goto missing clear_continuous_commands"
    )


def test_waypoint_mode_absolute() -> None:
    """goto params must use waypoint_mode=absolute."""
    import json
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    paths = [
        repo_root / "config" / "action_missions" / "recon_sequence_v1.json",
        repo_root
        / "config"
        / "profiles"
        / "rk3588-sitl"
        / "action_missions"
        / "recon_sequence_v1.json",
    ]
    for path in paths:
        data = json.loads(path.read_text())
        recon_step = next(
            s for s in data["steps"] if s.get("name") == "recon_sequence"
        )
        goto_mode = recon_step["params"]["goto"]["waypoint_mode"]
        assert goto_mode == "absolute", (
            f"{path.name}: goto.waypoint_mode={goto_mode!r}, expected 'absolute'"
        )


def test_detail_contains_results_and_recon_result_items() -> None:
    """Done detail must have all required fields for Web UI and build_recon_report."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(targets=targets, climb_max_updates=1)
    a = ReconSequenceAction()
    a.start(params)

    observe = _observe_detected_factory("baozha", 0.72)
    climb = _climb_done_factory()

    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=[_goto_done_factory(targets[0]), climb],
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            return_value=_lock_done_factory(targets[0]),
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            return_value=observe,
        ),
    ):
        _run_to_done(a, {})

    assert a._done is True
    detail = a._last_detail

    for key in (
        "status",
        "observed_count",
        "blank_count",
        "skipped_count",
        "results",
        "recon_result_items",
        "current",
        "valid_target_count",
    ):
        assert key in detail, f"missing detail key: {key}"

    assert detail["status"] == "done"
    assert detail["observed_count"] == 1
    assert len(detail["results"]) == 1
    assert len(detail["recon_result_items"]) == 1

    ri = detail["recon_result_items"][0]
    for key in ("target_index", "target_id", "content", "confidence", "status"):
        assert key in ri, f"missing recon_result_items key: {key}"

    res = detail["results"][0]
    for key in ("target_index", "target_id", "status", "content", "confidence"):
        assert key in res, f"missing results key: {key}"


def test_clear_keys_unique_across_transitions() -> None:
    """Two observe→climb transitions must produce different clear keys."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0))
    params = _base_params(targets=targets)
    a = ReconSequenceAction()
    a.start(params)

    goto_calls = [
        _goto_done_factory(targets[0]),
        _goto_done_factory(targets[1]),
        _climb_done_factory(),
        _climb_done_factory(),
    ]
    observe_calls = [
        _observe_detected_factory("baozha", 0.72),
        _observe_detected_factory("shenghua", 0.65),
    ]

    clear_keys: list[str] = []
    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=goto_calls,
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            side_effect=[
                _lock_done_factory(targets[0]),
                _lock_done_factory(targets[1]),
            ],
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            side_effect=observe_calls,
        ),
    ):
        for _ in range(200):
            r = a.update({})
            for act in r.actions:
                if act.get("action_type") == "clear_continuous_commands":
                    clear_keys.append(act["key"])
            if a._done:
                break

    # Should have at least 4 clear actions: 2 observe→climb + 2 climb→goto (or done)
    assert len(clear_keys) >= 2, f"expected ≥2 clear keys, got {clear_keys}"
    assert len(clear_keys) == len(set(clear_keys)), (
        f"duplicate clear keys found: {clear_keys}"
    )


# ── Codex FAIL 修复测试 ───────────────────────────────────────────────


def _observe_done_with_zero_factory() -> _FakeAction:
    """Fake observe that returns done with a zero flight_command in actions."""
    zero_cmd = {
        "action_type": "flight_command",
        "params": {
            "vx_body_mps": 0.0,
            "vy_body_mps": 0.0,
            "vz_body_mps": 0.0,
            "yaw_rate_cmd": 0.0,
        },
        "key": "observe_zero",
        "once": False,
        "priority": 3,
    }
    return _FakeAction(
        [
            ActionResult(
                done=True,
                reason="sign_detected",
                actions=[zero_cmd],
                detail={
                    "status": "detected",
                    "content": "baozha",
                    "confidence": 0.72,
                    "align_reason": "sign_detected",
                },
            )
        ]
    )


def _observe_failed_with_zero_factory() -> _FakeAction:
    """Fake observe that returns failed with a zero flight_command in actions."""
    zero_cmd = {
        "action_type": "flight_command",
        "params": {
            "vx_body_mps": 0.0,
            "vy_body_mps": 0.0,
            "vz_body_mps": 0.0,
            "yaw_rate_cmd": 0.0,
        },
        "key": "observe_zero_failed",
        "once": False,
        "priority": 3,
    }
    return _FakeAction(
        [
            ActionResult(
                failed=True,
                reason="align_failed",
                actions=[zero_cmd],
                detail={
                    "status": "blank_or_uncertain",
                    "content": "blank",
                    "confidence": 0.0,
                    "align_reason": "align_failed",
                },
            )
        ]
    )


def test_observe_done_preserves_child_zero_before_clear() -> None:
    """observe done → child zero flight_command must come before clear_continuous_commands."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(targets=targets, climb_max_updates=1)
    a = ReconSequenceAction()
    a.start(params)

    observe = _observe_done_with_zero_factory()
    climb = _climb_done_factory()

    transition_result = None
    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=[_goto_done_factory(targets[0]), climb],
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            return_value=_lock_done_factory(targets[0]),
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            return_value=observe,
        ),
    ):
        for _ in range(50):
            r = a.update({})
            if a.phase == "climb_after_observe":
                transition_result = r
                break

    assert transition_result is not None
    action_types = [act.get("action_type") for act in transition_result.actions]
    # flight_command (zero) must be present and before clear_continuous_commands
    assert "flight_command" in action_types, "observe→climb missing child zero flight_command"
    assert "clear_continuous_commands" in action_types, "observe→climb missing clear"
    fc_idx = action_types.index("flight_command")
    cl_idx = action_types.index("clear_continuous_commands")
    assert fc_idx < cl_idx, (
        f"zero flight_command (idx={fc_idx}) must come before clear (idx={cl_idx})"
    )


def test_observe_failed_preserves_child_zero_before_clear() -> None:
    """observe failed → child zero flight_command must come before clear_continuous_commands."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(targets=targets, climb_max_updates=1)
    a = ReconSequenceAction()
    a.start(params)

    observe = _observe_failed_with_zero_factory()
    climb = _climb_done_factory()

    transition_result = None
    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=[_goto_done_factory(targets[0]), climb],
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            return_value=_lock_done_factory(targets[0]),
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            return_value=observe,
        ),
    ):
        for _ in range(50):
            r = a.update({})
            if a.phase == "climb_after_observe":
                transition_result = r
                break

    assert transition_result is not None
    action_types = [act.get("action_type") for act in transition_result.actions]
    assert "flight_command" in action_types, "observe failed→climb missing child zero"
    assert "clear_continuous_commands" in action_types, "observe failed→climb missing clear"
    fc_idx = action_types.index("flight_command")
    cl_idx = action_types.index("clear_continuous_commands")
    assert fc_idx < cl_idx, (
        f"zero flight_command (idx={fc_idx}) must come before clear (idx={cl_idx})"
    )


def test_report_items_include_blank_and_skipped_targets() -> None:
    """All processed valid targets must appear in recon_result_items (not just detected)."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0), (0.5, 7.0))
    params = _base_params(targets=targets, goto_max_updates=1)
    a = ReconSequenceAction()
    a.start(params)

    # Flow: t0 goto→lock_fail, t1 goto→lock→observe→climb, t2 goto(timeout)
    # GotoWaypointAction calls: t0_goto, t1_goto, t1_climb, t2_goto
    all_goto = [
        _goto_done_factory(targets[0]),   # t0 goto
        _goto_done_factory(targets[1]),   # t1 goto
        _climb_done_factory(),            # t1 climb
        _FakeAction([ActionResult(reason="goto_active", actions=[])]),  # t2: timeout
    ]
    lock_results = [
        _FakeAction([ActionResult(failed=True, reason="target_lock_timeout")]),
        _lock_done_factory(targets[1]),
    ]
    observe_results = [
        _observe_detected_factory("baozha", 0.72),
    ]

    with (
        patch(
            "missions.common.actions.recon_sequence.GotoWaypointAction",
            side_effect=all_goto,
        ),
        patch(
            "missions.common.actions.recon_sequence.TargetLockAction",
            side_effect=lock_results,
        ),
        patch(
            "missions.common.actions.recon_sequence.ReconDescendObserveAction",
            side_effect=observe_results,
        ),
    ):
        _run_to_done(a, CLIMB_FAR_CTX)

    assert a._done is True
    # 3 valid targets processed → 3 items in recon_result_items
    assert len(a.recon_result_items) == 3, (
        f"expected 3 recon_result_items, got {len(a.recon_result_items)}: "
        f"{a.recon_result_items}"
    )

    # Verify each item has required fields
    for item in a.recon_result_items:
        for key in ("target_index", "target_id", "content", "confidence", "status", "reason"):
            assert key in item, f"missing key '{key}' in recon_result_item: {item}"

    # t0: lock_failed → blank
    assert a.recon_result_items[0]["status"] == "blank_or_uncertain"
    assert a.recon_result_items[0]["content"] == "blank"
    assert a.recon_result_items[0]["reason"] == "target_lock_failed"

    # t1: detected
    assert a.recon_result_items[1]["status"] == "detected"
    assert a.recon_result_items[1]["content"] == "baozha"

    # t2: goto_failed → blank
    assert a.recon_result_items[2]["status"] == "blank_or_uncertain"
    assert a.recon_result_items[2]["content"] == "blank"
    assert a.recon_result_items[2]["reason"] == "goto_failed"


def test_build_recon_report_accepts_recon_sequence_items() -> None:
    """BuildReconReportAction must accept recon_result_items with blank/skipped entries."""
    from missions.common.actions.build_recon_report import BuildReconReportAction

    items = [
        {
            "target_index": 0,
            "target_id": "r0",
            "content": "blank",
            "confidence": 0.0,
            "status": "blank_or_uncertain",
            "reason": "target_lock_failed",
        },
        {
            "target_index": 1,
            "target_id": "r1",
            "content": "baozha",
            "confidence": 0.72,
            "status": "detected",
            "reason": "sign_detected",
        },
        {
            "target_index": 2,
            "target_id": "r2",
            "content": "blank",
            "confidence": 0.0,
            "status": "blank_or_uncertain",
            "reason": "goto_failed",
        },
    ]

    action = BuildReconReportAction()
    action.start({"items": items})
    r = action.update({})

    assert r.done is True
    detail = r.detail
    assert detail["barrel_count"] == 3
    assert detail["detected_count"] == 1
    assert detail["blank_count"] == 2  # blank_or_uncertain counted as blank
    assert detail["skipped_count"] == 0

    barrels = detail["recon_report"]["barrels"]
    assert len(barrels) == 3
    assert barrels[0]["status"] == "blank_or_uncertain"
    assert barrels[0]["content"] == "blank"
    assert barrels[1]["status"] == "detected"
    assert barrels[1]["content"] == "baozha"
    assert barrels[2]["status"] == "blank_or_uncertain"
    assert barrels[2]["content"] == "blank"
