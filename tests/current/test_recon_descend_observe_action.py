from __future__ import annotations

import pytest

from missions.common.actions.action_lab import create_action_lab_registry
from missions.common.actions.recon_descend_observe import ReconDescendObserveAction


# ── helpers ─────────────────────────────────────────────────────────────


def _make_context(*, height_m: float, detections: list[dict] | None = None) -> dict:
    return {
        "drone": {"relative_altitude": height_m},
        "target_valid": True,
        "target_locked": True,
        "control_allowed": True,
        "ex_cam": 0.02,
        "ey_cam": 0.02,
        "scene": {"detections": detections or []},
    }


def _sign_detection(class_name: str, confidence: float = 0.8) -> dict:
    return {"class_name": class_name, "confidence": confidence}


def _make_params(**overrides) -> dict:
    defaults = {
        "target": {"id": "recon_0", "local_x": 0.0, "local_y": 50.0},
        "target_index": 0,
        "record_start_altitude_m": 2.0,
        "finish_altitude_m": 1.5,
        "detection_source": "scene",
        "sign_class_names": ["baozha", "shenghua", "yiran", "fangshe"],
        "min_sign_confidence": 0.35,
        "min_seen_frames": 3,
        "min_confidence_max": 0.55,
        "min_confidence_mean": 0.40,
        "min_score": 1.2,
        "min_margin_ratio": 1.4,
        "align_descend": {
            "expected_dt_s": 0.1,
            "lost_timeout_updates": 10,
            "hold_updates_required": 1,
            "max_retries": 1,
            "max_updates": 30,
            "finish_altitude_m": 1.5,
            "config": {
                "descent_gate_policy": "allow_unaligned",
                "unaligned_descend_speed_mps": 0.06,
                "min_altitude_m": 1.5,
                "require_target_locked": False,
                "payload_offset_enabled": False,
            },
        },
    }
    defaults.update(overrides)
    return defaults


def _run_until_done(action, make_ctx_fn) -> dict:
    """Run updates until done or 50 iterations, return final detail."""
    for _ in range(50):
        ctx = make_ctx_fn()
        result = action.update(ctx)
        if result.done:
            return result.detail
    raise RuntimeError("action did not finish")


# ── missing target ──────────────────────────────────────────────────────


def test_missing_target_skipped() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params(target=None))
    result = action.update(_make_context(height_m=2.5))
    assert result.done is True
    assert result.failed is False
    assert result.detail["status"] == "skipped_missing_target"
    assert result.detail["content"] == "blank"
    assert result.actions == []


def test_missing_target_no_local_x_skipped() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params(target={"id": "r0", "local_y": 50.0}))
    result = action.update(_make_context(height_m=2.5))
    assert result.detail["status"] == "skipped_missing_target"


# ── recording window ────────────────────────────────────────────────────


def test_above_record_window_no_sign_recording() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params())
    result = action.update(_make_context(height_m=3.0, detections=[_sign_detection("baozha", 0.9)]))
    assert result.detail["record_frame_count"] == 0


def test_inside_window_records_signs() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params())
    result = action.update(_make_context(height_m=1.8, detections=[_sign_detection("baozha", 0.76)]))
    assert result.detail["record_frame_count"] == 1
    assert result.detail["valid_sign_frame_count"] == 1
    assert "baozha" in result.detail["class_stats"]
    assert result.detail["class_stats"]["baozha"]["seen_frames"] == 1


def test_below_window_no_recording() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params())
    result = action.update(_make_context(height_m=1.2, detections=[_sign_detection("baozha", 0.9)]))
    assert result.detail["record_frame_count"] == 0


# ── flight_command envelope ─────────────────────────────────────────────


def test_flight_command_envelope() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params())
    result = action.update(_make_context(height_m=2.5))
    # during active descent, actions should be wrapped
    if result.actions:
        a = result.actions[0]
        assert a["action_type"] == "flight_command"
        assert "params" in a
        assert a["once"] is False
        assert "vx_cmd" in a["params"]


def test_flight_command_key_contains_target_index() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params(target_index=3))
    result = action.update(_make_context(height_m=2.5))
    if result.actions:
        assert "recon_descend_observe_3" in result.actions[0]["key"]


# ── zero on stop / finalize ─────────────────────────────────────────────


def test_zero_on_finalize() -> None:
    """Finalize returns zero-velocity action in Dispatcher envelope."""
    action = ReconDescendObserveAction()
    action.start(_make_params(finish_altitude_m=3.0, record_start_altitude_m=4.0,
                              align_descend={"expected_dt_s": 0.1, "lost_timeout_updates": 2,
                                             "hold_updates_required": 1, "max_retries": 0,
                                             "max_updates": 10, "finish_altitude_m": 1.5,
                                             "config": {"min_altitude_m": 1.5, "require_target_locked": False}}))
    # Run to completion, capturing the final ActionResult
    for _ in range(30):
        result = action.update(_make_context(height_m=1.4))
        if result.done:
            break
    assert result.done is True
    assert len(result.actions) >= 1
    a = result.actions[0]
    assert a["action_type"] == "flight_command"
    assert a["once"] is False
    assert a["params"]["vx_cmd"] == pytest.approx(0.0)
    assert a["params"]["vy_cmd"] == pytest.approx(0.0)
    assert a["params"]["vz_cmd"] == pytest.approx(0.0)
    assert a["params"]["enable_body"] is True
    assert a["params"]["active"] is True
    assert a["params"]["valid"] is True


def test_zero_on_stop() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params())
    action.update(_make_context(height_m=2.5))
    action.stop()
    result = action.update(_make_context(height_m=2.5))
    assert result.done is True
    assert len(result.actions) == 1
    a = result.actions[0]
    assert a["action_type"] == "flight_command"
    assert a["params"]["vz_cmd"] == pytest.approx(0.0)
    assert a["params"]["active"] is True
    assert "zero" in a["key"]


# ── frame-level dedup ───────────────────────────────────────────────────


def test_same_frame_two_detections_same_class_counts_once() -> None:
    """Two baozha boxes in one frame → baozha.seen_frames += 1, conf_max = max."""
    action = ReconDescendObserveAction()
    action.start(_make_params())
    result = action.update(_make_context(height_m=1.8, detections=[
        _sign_detection("baozha", 0.70),
        _sign_detection("baozha", 0.90),
    ]))
    cs = result.detail["class_stats"]
    assert cs["baozha"]["seen_frames"] == 1
    assert cs["baozha"]["conf_max"] == pytest.approx(0.90)


def test_valid_sign_frame_once_per_frame() -> None:
    """Multiple classes in one frame → valid_sign_frame_count += 1."""
    action = ReconDescendObserveAction()
    action.start(_make_params())
    result = action.update(_make_context(height_m=1.8, detections=[
        _sign_detection("baozha", 0.80),
        _sign_detection("shenghua", 0.70),
    ]))
    assert result.detail["valid_sign_frame_count"] == 1
    assert result.detail["class_stats"]["baozha"]["seen_frames"] == 1
    assert result.detail["class_stats"]["shenghua"]["seen_frames"] == 1


# ── finite validation ───────────────────────────────────────────────────


def test_finite_reject_nan_speed() -> None:
    action = ReconDescendObserveAction()
    with pytest.raises(ValueError):
        action.start(_make_params(align_descend={
            "expected_dt_s": 0.1, "finish_altitude_m": 1.5,
            "config": {"unaligned_descend_speed_mps": float("nan"), "descent_gate_policy": "allow_unaligned",
                       "min_altitude_m": 1.5, "require_target_locked": False},
        }))


def test_finite_reject_inf_altitude() -> None:
    action = ReconDescendObserveAction()
    with pytest.raises(ValueError, match="finite"):
        action.start(_make_params(record_start_altitude_m=float("inf")))


def test_finite_reject_nan_score() -> None:
    action = ReconDescendObserveAction()
    with pytest.raises(ValueError, match="finite"):
        action.start(_make_params(min_score=float("nan")))


# ── consecutive start clears ────────────────────────────────────────────


def test_consecutive_start_clears_stats() -> None:
    """start() twice without reset() → second start has independent stats."""
    action = ReconDescendObserveAction()
    action.start(_make_params(finish_altitude_m=3.0, record_start_altitude_m=4.0))
    for _ in range(3):
        action.update(_make_context(height_m=3.5, detections=[_sign_detection("baozha", 0.80)]))

    # start again without reset
    action.start(_make_params(finish_altitude_m=3.0, record_start_altitude_m=4.0))
    result = action.update(_make_context(height_m=3.5, detections=[_sign_detection("shenghua", 0.70)]))
    cs = result.detail["class_stats"]
    assert "baozha" not in cs
    assert "shenghua" in cs
    assert cs["shenghua"]["seen_frames"] == 1


# ── detected / blank asserts ────────────────────────────────────────────


def test_detected_asserts_status() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params(
        finish_altitude_m=3.0, record_start_altitude_m=4.0,
        min_seen_frames=2, min_confidence_max=0.5, min_confidence_mean=0.5, min_score=1.0, min_margin_ratio=1.1,
    ))
    # record baozha strongly enough
    for _ in range(5):
        action.update(_make_context(height_m=3.5, detections=[_sign_detection("baozha", 0.82)]))
    # drive to finish
    detail = _run_until_done(action, lambda: _make_context(height_m=3.0, detections=[_sign_detection("baozha", 0.82)]))
    assert detail["status"] == "detected"
    assert detail["content"] == "baozha"
    assert detail["sign_class"] == "baozha"
    assert detail["confidence"] == pytest.approx(0.82)


def test_margin_insufficient_outputs_blank() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params(
        finish_altitude_m=3.0, record_start_altitude_m=4.0,
        min_seen_frames=2, min_confidence_max=0.5, min_confidence_mean=0.5, min_score=1.0, min_margin_ratio=1.4,
    ))
    for _ in range(3):
        action.update(_make_context(height_m=3.5, detections=[
            _sign_detection("baozha", 0.80), _sign_detection("shenghua", 0.90),
        ]))
    detail = _run_until_done(action, lambda: _make_context(height_m=3.0, detections=[
        _sign_detection("baozha", 0.80), _sign_detection("shenghua", 0.90),
    ]))
    assert detail["content"] == "blank"
    assert detail["sign_class"] == ""
    assert detail["status"] in ("blank_or_uncertain", "align_failed")
    assert detail["margin_ratio"] > 0
    assert detail["margin_ratio"] < 1.4  # test's min_margin_ratio


def test_low_score_outputs_blank() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params(
        finish_altitude_m=3.0, record_start_altitude_m=4.0,
        min_seen_frames=5, min_confidence_max=0.5, min_confidence_mean=0.5, min_score=1.0,
    ))
    # only 3 frames → below min_seen_frames
    for _ in range(3):
        action.update(_make_context(height_m=3.5, detections=[_sign_detection("baozha", 0.80)]))
    detail = _run_until_done(action, lambda: _make_context(height_m=3.0, detections=[]))
    assert detail["content"] == "blank"
    assert detail["status"] in ("blank_or_uncertain", "align_failed")


# ── align failed yields blank + zero ────────────────────────────────────


def test_align_failed_yields_blank_and_zero() -> None:
    action = ReconDescendObserveAction()
    action.start(_make_params(
        align_descend={
            "expected_dt_s": 0.1,
            "lost_timeout_updates": 2,
            "hold_updates_required": 1,
            "max_retries": 0,
            "max_updates": 10,
            "finish_altitude_m": 1.5,
            "config": {"min_altitude_m": 1.5, "require_target_locked": False},
        },
    ))
    # trigger lost_timeout — fail after 3 frames (lost_timeout_updates=2, max_retries=0)
    for _ in range(5):
        ctx = {
            "drone": {"relative_altitude": 2.5},
            "target_valid": False,
            "vision_valid": False,
        }
        result = action.update(ctx)
        if result.done:
            break
    assert result.done is True
    assert result.failed is False
    assert result.detail["status"] in ("blank_or_uncertain", "align_failed")
    assert result.detail["align_failed"] is True
    assert result.detail["content"] == "blank"
    # must have zero action
    assert len(result.actions) >= 1
    z = result.actions[0]
    assert z["action_type"] == "flight_command"
    assert z["params"]["vz_cmd"] == pytest.approx(0.0)


# ── registry ────────────────────────────────────────────────────────────


def test_action_lab_registry_creates() -> None:
    registry = create_action_lab_registry()
    action = registry.create("recon_descend_observe")
    assert isinstance(action, ReconDescendObserveAction)


# ── invalid params ──────────────────────────────────────────────────────


def test_invalid_params_raise() -> None:
    action = ReconDescendObserveAction()
    with pytest.raises(ValueError):
        action.start(_make_params(record_start_altitude_m=1.0, finish_altitude_m=2.0))

    action.reset()
    with pytest.raises(ValueError):
        action.start(_make_params(finish_altitude_m=0.0))

    action.reset()
    with pytest.raises(ValueError):
        action.start(_make_params(sign_class_names=[]))

    action.reset()
    with pytest.raises(ValueError):
        action.start(_make_params(min_sign_confidence=1.5))

    action.reset()
    with pytest.raises(ValueError):
        action.start(_make_params(detection_source="invalid"))


# ── dispatcher policy ───────────────────────────────────────────────────


def test_dispatcher_policy_allows_flight_command() -> None:
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    fc_policy = ACTION_DISPATCH_POLICY.get("flight_command")
    assert fc_policy is not None
    assert "recon_descend_observe" in fc_policy.allowed_actions


def test_dispatcher_policy_no_set_servo() -> None:
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    ss_policy = ACTION_DISPATCH_POLICY.get("set_servo")
    assert ss_policy is not None
    assert "recon_descend_observe" not in ss_policy.allowed_actions


def test_dispatcher_policy_no_local_position() -> None:
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    lp_policy = ACTION_DISPATCH_POLICY.get("local_position")
    assert lp_policy is not None
    assert "recon_descend_observe" not in lp_policy.allowed_actions


def test_dispatcher_policy_no_arm() -> None:
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    arm_policy = ACTION_DISPATCH_POLICY.get("arm")
    assert arm_policy is not None
    assert "recon_descend_observe" not in arm_policy.allowed_actions


def test_dispatcher_policy_no_takeoff() -> None:
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    to_policy = ACTION_DISPATCH_POLICY.get("takeoff")
    assert to_policy is not None
    assert "recon_descend_observe" not in to_policy.allowed_actions


def test_dispatcher_policy_no_body_velocity() -> None:
    from app.dispatch.policy import ACTION_DISPATCH_POLICY
    bv_policy = ACTION_DISPATCH_POLICY.get("body_velocity")
    assert bv_policy is not None
    assert "recon_descend_observe" not in bv_policy.allowed_actions
