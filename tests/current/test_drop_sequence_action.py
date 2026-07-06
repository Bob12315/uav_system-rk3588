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

    # update 1: release servo action
    r1 = a.update({})
    servo_types_1 = [act.get("action_type") for act in r1.actions]
    assert "set_servo" in servo_types_1
    assert r1.reason == "release_sent"

    # update 2: waiting
    r2 = a.update({})
    assert r2.reason == "release_waiting"

    # update 3: hold servo action + done
    r3 = a.update({})
    servo_types_3 = [act.get("action_type") for act in r3.actions]
    assert "set_servo" in servo_types_3
    assert r3.done is True
    assert r3.reason == "payload_released"


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


def test_max_target_candidates_respected() -> None:
    targets = _make_targets((1.0, 5.0), (2.0, 5.0), (3.0, 5.0), (4.0, 5.0))
    params = _base_params(targets=targets, max_target_candidates=2, payloads=_make_payloads(1))
    a = DropSequenceAction()
    a.start(params)
    assert len(a.valid_targets) == 2
