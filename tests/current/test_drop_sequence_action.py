"""Tests for DropSequenceAction composite state machine."""

from __future__ import annotations

from typing import Any

from missions.common.actions.drop_sequence import DropSequenceAction


# ── helpers ────────────────────────────────────────────────────────────


def _make_targets(*coords: tuple[float, float]) -> list[dict[str, Any]]:
    return [
        {
            "valid": True, "id": f"t{i}", "target_id": f"t{i}",
            "class_name": f"bucket_{(i % 3) + 1}",
            "local_x": c[0], "local_y": c[1], "x": c[0], "y": c[1],
            "score": 500 - i * 100, "seen_count": 3, "count": 3,
            "raw_count": 3, "weight": 3.0 - i * 0.5,
            "track_ids": [i + 1], "rank": i + 1,
        }
        for i, c in enumerate(coords)
    ]


def _make_payloads(n: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "payload_id": f"payload_{i + 1}",
            "servo_outputs": [{"channel": 8 + i, "release_pwm": 1750, "hold_pwm": 1250}],
            "payload_forward_m": -0.06 if i == 0 else 0.06,
            "payload_right_m": 0.0,
        }
        for i in range(n)
    ]


def _base_params(**overrides: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "targets": _make_targets((1.0, 5.0), (-1.0, 6.0)),
        "payloads": _make_payloads(2),
        "max_target_candidates": 3,
        "max_payloads": 2,
        "approach_altitude_m": 2.5,
        "finish_altitude_m": 1.5,
        "climb_after_drop_m": 3.5,
        "goto_max_updates": 10,
        "target_lock_max_updates": 10,
        "align_descend_max_updates": 10,
        "climb_max_updates": 10,
        "fallback_release_when_last_target_failed": True,
        "release_all_payloads_if_only_one_target": True,
        "continue_after_any_failure": True,
        "goto": {
            "waypoint_mode": "absolute", "yaw_mode": "hold",
            "tolerance_xy_m": 5.0, "tolerance_z_m": 5.0,
            "min_hold_updates": 1, "priority": 5,
        },
        "target_lock": {
            "max_match_distance_m": 5.0, "detection_source": "scene",
            "class_names": ["bucket_1", "bucket_2", "bucket_3", "bucket"],
            "min_confidence": 0.1,
            "camera": {"fov_x_deg": 85.0, "fov_y_deg": 69.0, "image_x_sign": 1.0, "image_y_sign": -1.0},
        },
        "align_descend": {
            "expected_dt_s": 0.1, "lost_timeout_updates": 100,
            "hold_updates_required": 1, "max_retries": 0,
            "finish_altitude_m": 1.5,
            "config": {
                "kp_vx": 0.55, "kp_vy": 0.55,
                "max_vx_mps": 0.2, "max_vy_mps": 0.2,
                "descend_speed_mps": 0.3,
                "max_ex_cam": 5.0, "max_ey_cam": 5.0,
                "deadband_ex_cam": 0.01, "deadband_ey_cam": 0.01,
                "min_altitude_m": 1.0, "require_target_locked": False,
                "payload_offset_enabled": False, "height_gain_enabled": False,
            },
        },
        "release_wait_updates": 2,
    }
    p.update(overrides)
    return p


GOTO_CTX = {
    "local_position": {"x": 1.0, "y": 5.0, "z": -2.5}, "yaw": 0.0,
}
LOCK_OK_CTX = {
    "scene": {
        "detections": [{"class_name": "bucket_1", "confidence": 0.9,
                         "bbox": [300, 200, 350, 280],
                         "cx": 325, "cy": 240,
                         "track_id": 1}],
        "image_width": 640, "image_height": 480,
    },
    "drone": {"local_x": 1.0, "local_y": 5.0, "local_z": -2.5,
              "yaw": 0.0, "relative_altitude": 2.5},
}
LOCK_FAIL_CTX = {
    "scene": {"detections": [], "image_width": 640, "image_height": 480},
    "drone": {"local_x": 1.0, "local_y": 5.0, "local_z": -2.5,
              "yaw": 0.0, "relative_altitude": 2.5},
}
ALIGN_ACTIVE_CTX = {
    "relative_altitude": 3.0, "target_valid": True,
    "ex_cam": 0.0, "ey_cam": 0.0, "target_locked": True, "control_allowed": True,
}
ALIGN_DONE_CTX = {
    "relative_altitude": 1.2, "target_valid": True,
    "ex_cam": 0.0, "ey_cam": 0.0, "target_locked": True, "control_allowed": True,
}
CLIMB_FAR_CTX = {
    "local_position": {"x": 99.0, "y": 99.0, "z": -0.5}, "yaw": 0.0,
}


def _run_to_done(a: DropSequenceAction, ctx: dict[str, Any], n: int = 200) -> None:
    for _ in range(n):
        r = a.update(ctx)
        if r.done or r.failed:
            return


def _run_n(a: DropSequenceAction, ctx: dict[str, Any], n: int) -> list[Any]:
    results = []
    for _ in range(n):
        results.append(a.update(ctx))
    return results


def _run_until_phase(a: DropSequenceAction, ctx: dict[str, Any], target_phase: str, n: int = 200) -> None:
    for _ in range(n):
        if a.phase == target_phase or a._done:
            return
        a.update(ctx)


# ── tests ──────────────────────────────────────────────────────────────


def test_no_valid_targets() -> None:
    params = _base_params(targets=[])
    a = DropSequenceAction()
    a.start(params)
    r = a.update({})
    assert r.done is True
    assert r.failed is False
    assert r.reason == "no_valid_targets"
    assert r.detail["released_count"] == 0


def test_one_target_lock_failed_release_all() -> None:
    """1 target, lock fail → fallback release both payloads (release_all=true)."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets,
        payloads=_make_payloads(2),
        target_lock_max_updates=2,
        goto_max_updates=5,
        climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    # goto → done (at target)
    _run_until_phase(a, GOTO_CTX, "lock_target")

    # lock → fail (timeout: 2 updates with no detection)
    _run_until_phase(a, LOCK_FAIL_CTX, "release_payload")

    # release payload_1 (fallback)
    _run_until_phase(a, {}, "climb_after_release")

    # climb → timeout → release payload_2 (single_target_release_all)
    _run_until_phase(a, CLIMB_FAR_CTX, "release_payload")

    # release payload_2
    _run_to_done(a, {})

    assert a._done is True
    assert a.released_count == 2
    assert a.fallback_release_count == 1
    assert a.payload_results[0]["release_reason"] == "lock_failed_fallback_release"
    assert a.payload_results[1]["release_reason"] == "single_target_release_all"


def test_three_targets_first_lock_failed_second_third_success() -> None:
    """3 targets, 2 payloads: t0 lock fail → t1 success → t2 success."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0), (0.5, 7.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        target_lock_max_updates=2, goto_max_updates=5,
        align_descend_max_updates=5, climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    # t0: goto done
    _run_until_phase(a, GOTO_CTX, "lock_target")
    # t0: lock fail
    _run_until_phase(a, LOCK_FAIL_CTX, "goto_target")
    assert a.target_index == 1

    # t1: goto done
    _run_until_phase(a, GOTO_CTX, "lock_target")
    # t1: lock success (1 update with detection)
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    # t1: align done (altitude below finish)
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")
    # t1: release payload_1
    _run_until_phase(a, {}, "climb_after_release")

    # climb → t2
    _run_until_phase(a, CLIMB_FAR_CTX, "goto_target")
    # t2: goto done
    _run_until_phase(a, GOTO_CTX, "lock_target")
    # t2: lock success
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    # t2: align done
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")
    # t2: release payload_2
    _run_to_done(a, {})

    assert a._done is True
    assert a.released_count == 2
    assert a.skipped_target_count == 1
    assert a.payload_results[0]["payload_id"] == "payload_1"
    assert a.payload_results[1]["payload_id"] == "payload_2"
    assert a.payload_results[0]["release_reason"] == "aligned_release"


def test_two_targets_both_lock_failed_fallback_release() -> None:
    """2 targets, both lock fail → fallback release payload_1, done."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        target_lock_max_updates=2, goto_max_updates=5,
        climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    # t0: goto → lock fail
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_FAIL_CTX, "goto_target")

    # t1: goto → lock fail → fallback release
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_FAIL_CTX, "release_payload")

    # release payload_1
    _run_until_phase(a, {}, "climb_after_release")

    # climb timeout → done
    _run_to_done(a, CLIMB_FAR_CTX)

    assert a._done is True
    assert a.released_count == 1
    assert a.fallback_release_count == 1
    assert a.payload_results[0]["release_reason"] == "lock_failed_fallback_release"


def test_align_timeout_releases_payload() -> None:
    """Lock success → align timeout → release payload (align_failed_release)."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=2,
    )
    a = DropSequenceAction()
    a.start(params)

    # goto done
    _run_until_phase(a, GOTO_CTX, "lock_target")
    # lock success
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    # align timeout (altitude stays high, exceeds 2 updates)
    _run_until_phase(a, ALIGN_ACTIVE_CTX, "release_payload")

    assert a.phase == "release_payload"
    # release payload
    _run_to_done(a, {})

    assert a._done is True
    assert a.released_count == 1
    assert a.payload_results[0]["release_reason"] == "align_failed_release"


def test_payload_release_two_phase_complete() -> None:
    """PayloadRelease produces release servo, wait, hold servo actions."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, release_wait_updates=2,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    assert a.phase == "release_payload"

    # update 1: zero velocity + release servo action
    r1 = a.update({})
    action_types_1 = [act.get("action_type") for act in r1.actions]
    assert "flight_command" in action_types_1   # zero velocity
    assert "set_servo" in action_types_1
    assert r1.reason == "release_sent"

    # update 2: zero velocity + waiting
    r2 = a.update({})
    action_types_2 = [act.get("action_type") for act in r2.actions]
    assert "flight_command" in action_types_2   # zero velocity every tick
    assert r2.reason == "release_waiting"

    # update 3: zero velocity + hold servo action + sequence done
    r3 = a.update({})
    action_types_3 = [act.get("action_type") for act in r3.actions]
    assert "flight_command" in action_types_3   # zero velocity
    assert "set_servo" in action_types_3
    assert r3.done is True
    # Fix1: sequence done uses drop_sequence_done, not sub-action reason
    assert r3.reason == "drop_sequence_done"


def test_climb_timeout_does_not_fail_sequence() -> None:
    """Climb timeout → advance to next target, NOT failed."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    # t0: full cycle
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")
    _run_until_phase(a, {}, "climb_after_release")

    # climb timeout → next target
    _run_until_phase(a, CLIMB_FAR_CTX, "goto_target")
    assert a.target_index == 1

    # t1: full cycle
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")
    _run_to_done(a, {})

    assert a._done is True
    assert a.released_count == 2


def test_detail_contains_attempted_targets_and_payload_results() -> None:
    """Detail has all required fields for Web UI and logging."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")
    _run_until_phase(a, {}, "climb_after_release")
    _run_to_done(a, CLIMB_FAR_CTX)

    assert a._done is True
    detail = a._last_detail

    for key in ("status", "released_count", "fallback_release_count",
                "skipped_target_count", "attempted_targets", "payload_results",
                "current", "valid_target_count", "total_payload_count"):
        assert key in detail, f"missing key: {key}"

    assert detail["status"] == "done"
    assert detail["released_count"] == 1
    assert len(detail["payload_results"]) == 1
    pr = detail["payload_results"][0]
    assert pr["payload_id"] == "payload_1"
    assert pr["released"] is True
    assert pr["release_reason"] == "aligned_release"

    assert len(detail["attempted_targets"]) >= 1
    at = detail["attempted_targets"][0]
    for key in ("target_index", "target_id", "phase", "status", "consumed_payload"):
        assert key in at, f"missing attempted_targets key: {key}"


def test_invalid_targets_filtered() -> None:
    targets = [
        {"valid": False, "id": "missing", "local_x": None, "local_y": None},
        {"valid": True, "id": "good", "local_x": 1.0, "local_y": 5.0, "x": 1.0, "y": 5.0},
        {"valid": True, "id": "nan_coord", "local_x": float("nan"), "local_y": 5.0},
    ]
    params = _base_params(targets=targets, payloads=_make_payloads(1))
    a = DropSequenceAction()
    a.start(params)
    assert len(a.valid_targets) == 1
    assert a.valid_targets[0]["id"] == "good"


def test_goto_and_climb_prefer_local_xy_over_xy() -> None:
    targets = [{
        "valid": True,
        "id": "mixed",
        "target_id": "mixed",
        "class_name": "bucket",
        "local_x": 1.25,
        "local_y": 32.75,
        "x": 99.0,
        "y": -99.0,
        "score": 500,
        "seen_count": 3,
        "count": 3,
        "raw_count": 3,
        "weight": 1.0,
    }]
    params = _base_params(targets=targets, payloads=_make_payloads(1))
    action = DropSequenceAction()
    action.start(params)

    action._start_goto_target()
    assert action._current_action.target_x == 1.25
    assert action._current_action.target_y == 32.75
    goto_result = action._current_action.update(GOTO_CTX)
    assert goto_result.actions[0]["params"]["x"] == 1.25
    assert goto_result.actions[0]["params"]["y"] == 32.75
    assert goto_result.actions[0]["local_target"]["x"] == 1.25
    assert goto_result.actions[0]["local_target"]["y"] == 32.75

    action._start_climb()
    assert action._current_action.target_x == 1.25
    assert action._current_action.target_y == 32.75
    climb_result = action._current_action.update(GOTO_CTX)
    assert climb_result.actions[0]["params"]["x"] == 1.25
    assert climb_result.actions[0]["params"]["y"] == 32.75
    assert climb_result.actions[0]["local_target"]["x"] == 1.25
    assert climb_result.actions[0]["local_target"]["y"] == 32.75


def test_max_target_candidates_respected() -> None:
    targets = _make_targets((1.0, 5.0), (2.0, 5.0), (3.0, 5.0), (4.0, 5.0))
    params = _base_params(targets=targets, max_target_candidates=2, payloads=_make_payloads(1))
    a = DropSequenceAction()
    a.start(params)
    assert len(a.valid_targets) == 2


# ── Codex FAIL 修复测试 ───────────────────────────────────────────────────


def test_runner_done_not_propagated_after_first_payload() -> None:
    """First payload hold done ≠ sequence done when more payloads remain."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, release_wait_updates=2,
        climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    # run release to completion (3 ticks: release, wait, hold)
    release_done_result = None
    for _ in range(10):
        r = a.update({})
        if a.phase != "release_payload" or r.done:
            release_done_result = r
            break

    # Key: sequence NOT done after first payload
    assert a._done is False
    assert release_done_result is not None
    assert release_done_result.done is False
    assert release_done_result.reason == "payload_released_continue"

    # continue: climb → timeout → second release → sequence done
    _run_to_done(a, CLIMB_FAR_CTX)
    assert a._done is True
    assert a.released_count == 2


def test_release_phase_emits_zero_velocity_every_tick() -> None:
    """release/wait/hold each emit action_type=flight_command zero velocity."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, release_wait_updates=2,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    # 3 release ticks: release / wait / hold
    for tick_idx in range(3):
        r = a.update({})
        types = [act.get("action_type") for act in r.actions]
        assert "flight_command" in types, f"tick {tick_idx} missing flight_command"


def test_align_to_release_transition_emits_zero_velocity() -> None:
    """align done/failed → release transition tick includes zero flight_command."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")

    # align done → transition to release_payload
    # We need to catch the transition result
    transition_result = None
    for _ in range(20):
        r = a.update(ALIGN_DONE_CTX)
        if a.phase == "release_payload":
            transition_result = r
            break

    assert transition_result is not None
    types = [act.get("action_type") for act in transition_result.actions]
    assert "flight_command" in types, "align→release transition missing zero velocity"


def test_gps_drop_sequence_v2_uses_composite_absolute_navigation() -> None:
    """Both V2 templates use the GPS composite, which owns absolute GLOBAL goto."""
    import json
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    paths = [
        repo_root / "config" / "action_missions" / "drop_two_targets_v2.json",
        repo_root / "config" / "profiles" / "rk3588-sitl" / "action_missions" / "drop_two_targets_v2.json",
    ]
    for path in paths:
        data = json.loads(path.read_text())
        drop_steps = [step for step in data["steps"] if step.get("name") == "gps_drop_sequence"]
        assert len(drop_steps) == 1
        assert not any(step.get("name") == "drop_sequence" for step in data["steps"])
        assert drop_steps[0]["params"]["targets"] == "$drop_targets.target_slots"


def test_payload_release_failed_returns_failed() -> None:
    """If PayloadReleaseAction fails internally, sequence returns failed=True."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    # Simulate PayloadReleaseAction internal failure
    a._current_action.state = "invalid_force_fail"
    a._current_action.failed = True

    r = a.update({})
    assert r.failed is True
    assert r.reason == "payload_release_failed"
    # Must include zero velocity even on failure
    types = [act.get("action_type") for act in r.actions]
    assert "flight_command" in types
    # Sequence must not hang — _done is set
    assert a._done is True


# ── Phase2 二次修复测试：clear_continuous_commands ────────────────────────────


def test_release_to_climb_emits_clear_continuous() -> None:
    """payload_release hold done → climb: clear must have send_stop_first=True."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, release_wait_updates=2,
        climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    # Run release to completion (3 ticks: release, wait, hold)
    release_done_result = None
    for _ in range(10):
        r = a.update({})
        if a.phase != "release_payload" or r.done:
            release_done_result = r
            break

    assert release_done_result is not None
    assert release_done_result.done is False  # not done yet, 2nd payload remains
    types = [act.get("action_type") for act in release_done_result.actions]
    assert "set_servo" in types, "release→climb missing hold servo"
    assert "clear_continuous_commands" in types, (
        "release→climb missing clear_continuous_commands"
    )
    clear_act = [act for act in release_done_result.actions if act.get("action_type") == "clear_continuous_commands"][0]
    assert clear_act["params"].get("send_stop_first") is True, (
        "release→climb clear must have send_stop_first=True"
    )


def test_climb_to_goto_emits_clear_continuous() -> None:
    """climb timeout → next goto: clear does NOT need send_stop_first (just cleanup)."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    # t0: full cycle to climb
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")
    _run_until_phase(a, {}, "climb_after_release")

    # climb timeout → transition to goto_target
    transition_result = None
    for _ in range(20):
        r = a.update(CLIMB_FAR_CTX)
        if a.phase == "goto_target":
            transition_result = r
            break

    assert transition_result is not None
    types = [act.get("action_type") for act in transition_result.actions]
    assert "clear_continuous_commands" in types, (
        "climb→goto missing clear_continuous_commands"
    )
    clear_act = [act for act in transition_result.actions if act.get("action_type") == "clear_continuous_commands"][0]
    assert clear_act["params"].get("send_stop_first") is False, (
        "climb→goto clear should use send_stop_first=False (no BODY_NED to stop)"
    )


def test_zero_command_values_are_all_zero() -> None:
    """flight_command zero velocity must have vx=vy=vz=yaw_rate=0, once=False."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, release_wait_updates=2,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    r = a.update({})
    flight_cmds = [
        act for act in r.actions
        if act.get("action_type") == "flight_command"
    ]
    assert len(flight_cmds) >= 1, "no flight_command in release tick"
    cmd = flight_cmds[0]
    p = cmd.get("params") or {}
    # All velocity components must be zero
    for key in ("vx_body_mps", "vy_body_mps", "vz_body_mps", "yaw_rate_cmd",
                "vx_cmd", "vy_cmd", "vz_cmd"):
        val = p.get(key)
        if val is not None:
            assert float(val) == 0.0, f"zero command {key}={val}, expected 0"
    # Must be continuous (once=False) to keep refreshing
    assert cmd.get("once") is False, "zero velocity must be continuous (once=False)"


def test_payload_release_failed_emits_clear_continuous() -> None:
    """PayloadRelease failure must also emit clear_continuous_commands."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    # Simulate PayloadReleaseAction internal failure
    a._current_action.state = "invalid_force_fail"
    a._current_action.failed = True

    r = a.update({})
    assert r.failed is True
    types = [act.get("action_type") for act in r.actions]
    assert "clear_continuous_commands" in types, (
        "payload_release_failed missing clear_continuous_commands"
    )


def test_two_release_to_climb_transitions_have_unique_keys() -> None:
    """Two separate release→climb transitions must produce different clear keys."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, release_wait_updates=2,
        climb_max_updates=1,
    )
    a = DropSequenceAction()
    a.start(params)

    # t0: full cycle to first release done
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    clear_keys: list[str] = []
    for _ in range(10):
        r = a.update({})
        if a.phase != "release_payload":
            # capture clear_continuous_commands key from transition
            for act in r.actions:
                if act.get("action_type") == "clear_continuous_commands":
                    clear_keys.append(act["key"])
            break

    # climb timeout → t1 goto → lock → align → second release
    _run_until_phase(a, CLIMB_FAR_CTX, "goto_target")
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    for _ in range(10):
        r = a.update({})
        if a.phase != "release_payload" or r.done:
            for act in r.actions:
                if act.get("action_type") == "clear_continuous_commands":
                    clear_keys.append(act["key"])
            break

    assert len(clear_keys) == 2, f"expected 2 clear keys, got {clear_keys}"
    assert clear_keys[0] != clear_keys[1], (
        f"duplicate clear keys: {clear_keys[0]}"
    )


def test_two_climb_to_goto_transitions_have_unique_keys() -> None:
    """Two separate climb→goto transitions must produce different clear keys."""
    targets = _make_targets((1.0, 5.0), (-1.0, 6.0), (0.5, 7.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(3),
        max_payloads=3, max_target_candidates=3,
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=5, climb_max_updates=1,
        release_wait_updates=2,
    )
    a = DropSequenceAction()
    a.start(params)

    clear_keys: list[str] = []

    for cycle in range(2):
        _run_until_phase(a, GOTO_CTX, "lock_target")
        _run_until_phase(a, LOCK_OK_CTX, "align_descend")
        _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")
        _run_until_phase(a, {}, "climb_after_release")

        # climb timeout → transition
        for _ in range(20):
            r = a.update(CLIMB_FAR_CTX)
            if a.phase == "goto_target":
                for act in r.actions:
                    if act.get("action_type") == "clear_continuous_commands":
                        clear_keys.append(act["key"])
                break

    assert len(clear_keys) == 2, f"expected 2 clear keys, got {clear_keys}"
    assert clear_keys[0] != clear_keys[1], (
        f"duplicate clear keys: {clear_keys[0]}"
    )


# ── SITL 前安全修复：旧 BODY_NED 停止测试 ────────────────────────────────

CTX_CONTROL_FALSE = {
    "relative_altitude": 2.5, "target_valid": True,
    "ex_cam": 0.0, "ey_cam": 0.0, "target_locked": True, "control_allowed": False,
}
CTX_TARGET_INVALID = {
    "relative_altitude": 2.5, "target_valid": False,
    "ex_cam": 0.0, "ey_cam": 0.0, "target_locked": False, "control_allowed": True,
}


def test_align_control_allowed_false_emits_zero_and_clear() -> None:
    """control_allowed true→false: next tick returns send_stop_first clear, NO flight_command."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=50,
    )
    a = DropSequenceAction()
    a.start(params)

    # goto → lock → align
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")

    # Tick 1: active control (non-zero velocities possible)
    r1 = a.update(ALIGN_ACTIVE_CTX)
    types1 = [act.get("action_type") for act in r1.actions]
    assert "flight_command" in types1, "first active tick should emit flight_command"

    # Tick 2: control_allowed=False → clear with send_stop_first=True (NO flight_command)
    r2 = a.update(CTX_CONTROL_FALSE)
    types2 = [act.get("action_type") for act in r2.actions]
    assert "flight_command" not in types2, (
        "inactive tick must NOT emit flight_command; use send_stop_first clear instead"
    )
    assert "clear_continuous_commands" in types2, (
        "inactive tick must emit clear_continuous_commands with send_stop_first"
    )
    clear_act = [act for act in r2.actions if act.get("action_type") == "clear_continuous_commands"][0]
    assert clear_act["params"].get("send_stop_first") is True, (
        "inactive clear must have send_stop_first=True"
    )


def test_align_target_invalid_emits_zero_and_clear() -> None:
    """target_valid true→false: next tick returns send_stop_first clear, NO flight_command."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=50,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")

    # Tick 1: active control
    a.update(ALIGN_ACTIVE_CTX)

    # Tick 2: target lost
    r2 = a.update(CTX_TARGET_INVALID)
    types2 = [act.get("action_type") for act in r2.actions]
    assert "flight_command" not in types2, (
        "target lost tick must NOT emit flight_command; use send_stop_first clear instead"
    )
    assert "clear_continuous_commands" in types2, (
        "target lost tick must emit clear_continuous_commands"
    )
    clear_act = [act for act in r2.actions if act.get("action_type") == "clear_continuous_commands"][0]
    assert clear_act["params"].get("send_stop_first") is True, (
        "target lost clear must have send_stop_first=True"
    )


def test_align_to_release_transition_emits_clear() -> None:
    """align done → release transition emits clear_continuous_commands with send_stop_first."""
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(1),
        goto_max_updates=5, target_lock_max_updates=5,
        align_descend_max_updates=50,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")

    # align done → transition
    transition_result = None
    for _ in range(20):
        r = a.update(ALIGN_DONE_CTX)
        if a.phase == "release_payload":
            transition_result = r
            break

    assert transition_result is not None
    types = [act.get("action_type") for act in transition_result.actions]
    assert "clear_continuous_commands" in types, (
        "align→release transition missing clear_continuous_commands"
    )
    # clear must have send_stop_first=True
    clear_act = [act for act in transition_result.actions if act.get("action_type") == "clear_continuous_commands"][0]
    assert clear_act["params"].get("send_stop_first") is True, (
        "align→release clear must have send_stop_first=True"
    )


# ── GPS-to-local v2: single-target rejection ───────────────────────────


def test_single_target_release_all_disabled_no_fallback() -> None:
    """With release_all_payloads_if_only_one_target=False and
    fallback_release_when_last_target_failed=False, a single valid target
    should consume exactly one payload and stop — no dual-drop on same target.
    """
    targets = _make_targets((1.0, 5.0))
    params = _base_params(
        targets=targets, payloads=_make_payloads(2),
        target_lock_max_updates=5, goto_max_updates=5,
        align_descend_max_updates=5, climb_max_updates=1,
        release_wait_updates=2,
        release_all_payloads_if_only_one_target=False,
        fallback_release_when_last_target_failed=False,
    )
    a = DropSequenceAction()
    a.start(params)

    assert a._only_one_target is True
    assert len(a.valid_targets) == 1
    assert a.release_all_payloads_if_only_one_target is False
    assert a.fallback_release_when_last_target_failed is False

    # t0: goto done → lock success → align done → release payload_1
    _run_until_phase(a, GOTO_CTX, "lock_target")
    _run_until_phase(a, LOCK_OK_CTX, "align_descend")
    _run_until_phase(a, ALIGN_DONE_CTX, "release_payload")

    # Run release to completion
    _run_to_done(a, {})

    assert a._done is True
    # Only one payload released (not both on same target)
    assert a.released_count == 1, (
        f"expected 1 release on single target, got {a.released_count}"
    )
    assert a.fallback_release_count == 0
    # Verify payload_2 was NOT released
    payload_ids = [pr.get("payload_id") for pr in a.payload_results]
    assert "payload_2" not in payload_ids, (
        f"payload_2 should not be released when release_all is disabled; released: {payload_ids}"
    )


# ── aggressive scoring: no-target in-place release ────────────────────


def test_no_valid_targets_release_all_in_place() -> None:
    """release_all_payloads_if_no_valid_targets=true + empty targets
    → both payloads released in-place, released_count=2, done.
    """
    params = _base_params(
        targets=[], payloads=_make_payloads(2),
        release_wait_updates=2,
        release_all_payloads_if_no_valid_targets=True,
    )
    a = DropSequenceAction()
    a.start(params)

    assert a.release_all_payloads_if_no_valid_targets is True
    assert len(a.valid_targets) == 0
    assert len(a.payloads) == 2

    # init → release_no_target
    r0 = a.update({})
    assert a.phase == "release_no_target"
    assert r0.done is False

    # Run both payloads to completion
    _run_to_done(a, {})

    assert a._done is True
    assert a.released_count == 2
    assert a.fallback_release_count == 0
    assert a._last_reason == "drop_sequence_done"

    assert len(a.payload_results) == 2
    assert a.payload_results[0]["payload_id"] == "payload_1"
    assert a.payload_results[0]["released"] is True
    assert a.payload_results[0]["release_reason"] == "no_target_release_all_in_place"
    assert a.payload_results[0]["target_id"] is None
    assert a.payload_results[0]["target_index"] == -1
    assert a.payload_results[1]["payload_id"] == "payload_2"
    assert a.payload_results[1]["release_reason"] == "no_target_release_all_in_place"


def test_no_valid_targets_no_release_when_flag_false() -> None:
    """flag=false + empty targets → done with released_count=0 (backward compat)."""
    params = _base_params(
        targets=[], payloads=_make_payloads(2),
        release_all_payloads_if_no_valid_targets=False,
    )
    a = DropSequenceAction()
    a.start(params)

    assert a.release_all_payloads_if_no_valid_targets is False

    r = a.update({})
    assert r.done is True
    assert r.failed is False
    assert r.reason == "no_valid_targets"
    assert r.detail["released_count"] == 0
    assert a.released_count == 0


def test_no_valid_targets_release_all_default_off() -> None:
    """Default (no param) → flag=false → no release."""
    params = _base_params(targets=[], payloads=_make_payloads(2))
    a = DropSequenceAction()
    a.start(params)

    assert a.release_all_payloads_if_no_valid_targets is False

    r = a.update({})
    assert r.done is True
    assert r.reason == "no_valid_targets"
    assert a.released_count == 0


def test_no_valid_targets_release_one_payload() -> None:
    """1 payload, no targets, flag=true → release 1 payload in-place."""
    params = _base_params(
        targets=[], payloads=_make_payloads(1),
        release_wait_updates=2,
        release_all_payloads_if_no_valid_targets=True,
    )
    a = DropSequenceAction()
    a.start(params)

    _run_to_done(a, {})

    assert a._done is True
    assert a.released_count == 1
    assert a.payload_results[0]["release_reason"] == "no_target_release_all_in_place"
