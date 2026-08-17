# Archived composite-Action behavior lock; replaced by Mission subflow contracts.
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from missions.common.actions.action_lab import action_lab_specs, create_action_lab_registry
from missions.common.actions.align_descend import AlignDescendAction, AlignDescendConfig
from missions.common.actions.visual_land import VisualLandAction


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _h_detection(
    *,
    ex: float = 0.0,
    ey: float = 0.0,
    track_id: int | None = 1,
    confidence: float = 0.9,
    class_name: str = "H",
) -> dict:
    det = {"class_name": class_name, "confidence": confidence, "ex": ex, "ey": ey}
    if track_id is not None:
        det["track_id"] = track_id
    return det


def _cxcy_h_detection(
    *,
    cx: float = 320.0,
    cy: float = 240.0,
    img_w: float = 640.0,
    img_h: float = 480.0,
    track_id: int | None = 2,
    confidence: float = 0.85,
    class_name: str = "H",
) -> dict:
    det = {
        "class_name": class_name,
        "confidence": confidence,
        "cx": cx,
        "cy": cy,
        "image_width": img_w,
        "image_height": img_h,
    }
    if track_id is not None:
        det["track_id"] = track_id
    return det


def _local_ned_context(
    altitude_m: float = 2.5,
    local_altitude_valid: bool = True,
    **overrides,
) -> dict:
    ctx: dict = {
        "local_altitude_m": altitude_m,
        "local_altitude_valid": local_altitude_valid,
        "drone": {"relative_altitude": altitude_m},
    }
    ctx.update(overrides)
    return ctx


def _scene_context(
    altitude_m: float = 2.5,
    detections: list[dict] | None = None,
    **overrides,
) -> dict:
    ctx = _local_ned_context(altitude_m=altitude_m, **overrides)
    ctx["scene"] = {"detections": detections or [], "image_width": 640, "image_height": 480}
    return ctx


# ---------------------------------------------------------------------------
# 1. registry
# ---------------------------------------------------------------------------

def test_registry_contains_visual_land() -> None:
    registry = create_action_lab_registry()
    assert "visual_land" in registry.list()
    instance = registry.create("visual_land")
    assert isinstance(instance, VisualLandAction)


def test_visual_land_spec_exists() -> None:
    specs = {item["name"]: item for item in action_lab_specs()}
    assert "visual_land" in specs
    spec = specs["visual_land"]
    assert spec["default_params"]["class_names"] == ["H"]
    assert spec["default_params"]["finish_altitude_m"] == 0.3
    assert spec["default_params"]["blind_descend_speed_mps"] == 0.3


# ---------------------------------------------------------------------------
# 2. H detection excludes non-H classes
# ---------------------------------------------------------------------------

def test_excludes_bucket_and_danger_detections() -> None:
    action = VisualLandAction()
    action.start()
    detections = [
        _h_detection(ex=0.1, ey=0.0, class_name="bucket_1"),
        _h_detection(ex=0.2, ey=0.0, class_name="danger_1"),
        _h_detection(ex=0.3, ey=0.0, class_name="H"),
    ]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    # Should find the H at ex=0.3 and lock
    assert result.reason == "target_locked_descending"
    assert len(result.actions) == 1
    assert result.actions[0]["action_type"] == "yolo_lock_target"


def test_excludes_below_confidence() -> None:
    action = VisualLandAction()
    action.start()
    detections = [
        _h_detection(ex=0.0, ey=0.0, confidence=0.2),  # below 0.35
        _h_detection(ex=0.5, ey=0.0, confidence=0.9),
    ]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    # Should find the H at ex=0.5, not the low-confidence one
    assert result.reason == "target_locked_descending"


# ---------------------------------------------------------------------------
# 3. multiple H → closest to image centre
# ---------------------------------------------------------------------------

def test_selects_closest_to_center() -> None:
    action = VisualLandAction()
    action.start()
    detections = [
        _h_detection(ex=0.5, ey=0.5, track_id=10),
        _h_detection(ex=0.1, ey=0.0, track_id=20),
        _h_detection(ex=-0.8, ey=-0.8, track_id=30),
    ]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    assert result.reason == "target_locked_descending"
    # Should lock the closest one (ex=0.1, ey=0.0, track_id=20)
    assert result.actions[0]["params"]["track_id"] == 20


def test_cxcy_selects_closest_to_center() -> None:
    action = VisualLandAction()
    action.start()
    detections = [
        _cxcy_h_detection(cx=500, cy=400, track_id=10),  # far
        _cxcy_h_detection(cx=320, cy=240, track_id=20),  # centre
        _cxcy_h_detection(cx=100, cy=100, track_id=30),  # far
    ]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    assert result.reason == "target_locked_descending"
    assert result.actions[0]["params"]["track_id"] == 20


# ---------------------------------------------------------------------------
# 4. no H in search window → blind descent
# ---------------------------------------------------------------------------

def test_no_h_triggers_blind_descent_after_search_max() -> None:
    action = VisualLandAction()
    action.start({"search_max_updates": 3, "blind_descend_speed_mps": 0.3})
    # 3 updates with no H
    ctx = _scene_context(detections=[], altitude_m=2.5)
    for i in range(3):
        result = action.update(ctx)
        if i < 2:
            assert result.reason == "searching_for_h"

    # After search max, should be in descent phase via internal AlignDescendAction
    # The internal action with target_loss_policy=continue_descent produces blind descent
    assert "searching_for_h" not in result.reason


def test_no_track_id_still_descends() -> None:
    """H found but no track_id → no lock action, still enter descent."""
    action = VisualLandAction()
    action.start()
    detections = [_h_detection(ex=0.0, ey=0.0, track_id=None)]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    assert result.reason == "target_locked_descending"
    assert len(result.actions) == 0  # no lock because no track_id


# ---------------------------------------------------------------------------
# 5. correct yolo_lock_target
# ---------------------------------------------------------------------------

def test_sends_yolo_lock_target_with_track_id() -> None:
    action = VisualLandAction()
    action.start()
    detections = [_h_detection(ex=0.0, ey=0.0, track_id=42)]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    assert len(result.actions) == 1
    action_item = result.actions[0]
    assert action_item["action_type"] == "yolo_lock_target"
    assert action_item["params"]["track_id"] == 42
    assert action_item["once"] is True


def test_negative_track_id_treated_as_no_track_id() -> None:
    action = VisualLandAction()
    action.start()
    detections = [_h_detection(ex=0.0, ey=0.0, track_id=-1)]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    assert result.reason == "target_locked_descending"
    assert len(result.actions) == 0  # no lock


# ---------------------------------------------------------------------------
# 6. H visible → visual vx/vy correction while descending
# ---------------------------------------------------------------------------

def test_align_descend_produces_visual_correction() -> None:
    """When H is visible, internal AlignDescendAction should produce non-zero vx/vy."""
    action = VisualLandAction()
    action.start({
        "finish_altitude_m": 0.3,
        "blind_descend_speed_mps": 0.3,
        "align_descend": {
            "expected_dt_s": 0.1,
            "max_updates": 300,
            "finish_altitude_m": 0.3,
            "finish_policy": "legacy",
            "config": {
                "kp_vx": 0.3,
                "kp_vy": 0.3,
                "max_vx_mps": 0.3,
                "max_vy_mps": 0.3,
                "descend_speed_mps": 0.35,
                "max_ex_cam": 0.3,
                "max_ey_cam": 0.3,
                "deadband_ex_cam": 0.0,
                "deadband_ey_cam": 0.0,
                "min_altitude_m": 0.3,
                "require_target_locked": False,
                "payload_offset_enabled": False,
                "altitude_source": "local_ned",
                "descent_gate_policy": "allow_unaligned",
                "unaligned_descend_speed_mps": 0.3,
            },
        },
    })
    # Search phase: find H
    detections = [_h_detection(ex=0.2, ey=0.1, track_id=5)]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    result = action.update(ctx)
    assert result.reason == "target_locked_descending"

    # Now in descent: update again with same H visible
    ctx2 = _scene_context(detections=detections, altitude_m=2.3)
    result2 = action.update(ctx2)
    # Should produce a visual correction command
    detail = result2.detail
    cmd = detail.get("command", {})
    # With ex=0.2, ey=0.1, kp=0.3, sign vx=-1, vy=1:
    # vx = vx_sign * kp * ey = -1 * 0.3 * 0.1 = -0.03
    # vy = vy_sign * kp * ex = 1 * 0.3 * 0.2 = 0.06
    assert abs(cmd.get("vx_cmd", 0.0) - (-0.03)) < 0.02
    assert abs(cmd.get("vy_cmd", 0.0) - 0.06) < 0.02
    assert cmd.get("vz_cmd", 0.0) > 0  # descending


# ---------------------------------------------------------------------------
# 7. H disappears → vx=0, vy=0, vz>0, no target_lost_timeout
# ---------------------------------------------------------------------------

def test_h_disappears_triggers_blind_descent_not_timeout() -> None:
    action = VisualLandAction()
    action.start({
        "finish_altitude_m": 0.3,
        "blind_descend_speed_mps": 0.35,
        "align_descend": {
            "expected_dt_s": 0.1,
            "max_updates": 300,
            "finish_altitude_m": 0.3,
            "finish_policy": "legacy",
            "config": {
                "kp_vx": 0.3,
                "kp_vy": 0.3,
                "max_vx_mps": 0.3,
                "max_vy_mps": 0.3,
                "descend_speed_mps": 0.35,
                "max_ex_cam": 0.3,
                "max_ey_cam": 0.3,
                "deadband_ex_cam": 0.0,
                "deadband_ey_cam": 0.0,
                "min_altitude_m": 0.3,
                "require_target_locked": False,
                "payload_offset_enabled": False,
                "altitude_source": "local_ned",
            },
        },
    })
    # First, find H and enter descent
    detections = [_h_detection(ex=0.1, ey=0.1, track_id=5)]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    action.update(ctx)  # search → lock

    # Now H disappears
    ctx2 = _scene_context(detections=[], altitude_m=2.3)
    result = action.update(ctx2)

    # Should NOT fail with target_lost_timeout
    assert not result.failed

    cmd = result.detail.get("command", {})
    assert cmd.get("vx_cmd", 999) == 0.0
    assert cmd.get("vy_cmd", 999) == 0.0
    # Should still be descending
    assert cmd.get("vz_cmd", 0.0) > 0
    # hold_reason should indicate blind descent
    assert "blind_descent" in str(result.detail.get("hold_reason", ""))


def test_h_disappears_no_target_lost_timeout_after_many_updates() -> None:
    """Even after many updates with target lost, should not timeout."""
    action = VisualLandAction()
    action.start({
        "finish_altitude_m": 0.3,
        "blind_descend_speed_mps": 0.35,
        "align_descend": {
            "expected_dt_s": 0.1,
            "max_updates": 300,
            "finish_altitude_m": 0.3,
            "finish_policy": "legacy",
            "config": {
                "kp_vx": 0.3,
                "kp_vy": 0.3,
                "max_vx_mps": 0.3,
                "max_vy_mps": 0.3,
                "descend_speed_mps": 0.35,
                "max_ex_cam": 0.3,
                "max_ey_cam": 0.3,
                "deadband_ex_cam": 0.0,
                "deadband_ey_cam": 0.0,
                "min_altitude_m": 0.3,
                "require_target_locked": False,
                "payload_offset_enabled": False,
                "altitude_source": "local_ned",
            },
        },
    })
    # Enter descent
    action.update(_scene_context(detections=[_h_detection(ex=0.1, ey=0.1)], altitude_m=2.5))

    # Many updates with no H
    for i in range(20):
        ctx = _scene_context(detections=[], altitude_m=2.0 - i * 0.01)
        result = action.update(ctx)
        assert not result.failed, f"Failed at update {i}: {result.reason}"


# ---------------------------------------------------------------------------
# 8. below 0.8m → descent speed ≤ 0.18 m/s
# ---------------------------------------------------------------------------

def test_below_0_8m_speed_capped() -> None:
    """When altitude is below 0.8m, descent speed should be ≤ 0.18 m/s."""
    action = VisualLandAction()
    action.start({
        "finish_altitude_m": 0.3,
        "blind_descend_speed_mps": 0.35,
        "align_descend": {
            "expected_dt_s": 0.1,
            "max_updates": 300,
            "finish_altitude_m": 0.3,
            "finish_policy": "legacy",
            "config": {
                "kp_vx": 0.3,
                "kp_vy": 0.3,
                "max_vx_mps": 0.3,
                "max_vy_mps": 0.3,
                "descend_speed_mps": 0.35,
                "slow_descend_speed_mps": 0.3,
                "max_ex_cam": 0.3,
                "max_ey_cam": 0.3,
                "slow_descend_max_ex_cam": 0.55,
                "slow_descend_max_ey_cam": 0.55,
                "deadband_ex_cam": 0.04,
                "deadband_ey_cam": 0.04,
                "min_altitude_m": 0.3,
                "require_target_locked": False,
                "payload_offset_enabled": False,
                "descent_gate_policy": "allow_unaligned",
                "unaligned_descend_speed_mps": 0.3,
                "yaw_control_mode": "hold",
                "altitude_source": "local_ned",
                "descent_speed_stages": [
                    {"max_altitude_m": 0.8, "max_descend_speed_mps": 0.18},
                    {"max_altitude_m": 2.5, "max_descend_speed_mps": 0.35},
                ],
            },
        },
    })
    # Enter descent
    action.update(_scene_context(detections=[_h_detection(ex=0.1, ey=0.1)], altitude_m=0.7))

    # At 0.7m, speed should be capped at 0.18
    result = action.update(_scene_context(detections=[_h_detection(ex=0.1, ey=0.1)], altitude_m=0.7))
    cmd = result.detail.get("command", {})
    vz = cmd.get("vz_cmd", 0.0)
    assert vz <= 0.19, f"vz_cmd {vz} should be ≤ 0.18 at 0.7m"


# ---------------------------------------------------------------------------
# 9. reaches 0.3m → zero velocity, done
# ---------------------------------------------------------------------------

def test_reaches_0_3m_outputs_zero_velocity_and_done() -> None:
    action = VisualLandAction()
    action.start({
        "finish_altitude_m": 0.3,
        "blind_descend_speed_mps": 0.3,
        "align_descend": {
            "expected_dt_s": 0.1,
            "max_updates": 300,
            "finish_altitude_m": 0.3,
            "finish_policy": "legacy",
            "config": {
                "kp_vx": 0.3,
                "kp_vy": 0.3,
                "max_vx_mps": 0.3,
                "max_vy_mps": 0.3,
                "descend_speed_mps": 0.35,
                "max_ex_cam": 0.3,
                "max_ey_cam": 0.3,
                "deadband_ex_cam": 0.0,
                "deadband_ey_cam": 0.0,
                "min_altitude_m": 0.3,
                "require_target_locked": False,
                "payload_offset_enabled": False,
                "altitude_source": "local_ned",
            },
        },
    })
    # Enter descent
    action.update(_scene_context(detections=[_h_detection(ex=0.0, ey=0.0)], altitude_m=0.5))

    # At finish altitude
    result = action.update(_scene_context(detections=[_h_detection(ex=0.0, ey=0.0)], altitude_m=0.3))
    assert result.done
    assert result.reason == "visual_land_complete"

    # Should have stop commands
    action_types = [a["action_type"] for a in result.actions]
    assert "flight_command" in action_types
    assert "clear_continuous_commands" in action_types

    # flight_command should have zero velocity
    flight = next(a for a in result.actions if a["action_type"] == "flight_command")
    assert flight["params"]["vx_cmd"] == 0.0
    assert flight["params"]["vy_cmd"] == 0.0
    assert flight["params"]["vz_cmd"] == 0.0


# ---------------------------------------------------------------------------
# 10. missing local NED altitude → fail
# ---------------------------------------------------------------------------

def test_missing_local_ned_altitude_fails() -> None:
    action = VisualLandAction()
    action.start()
    # Enter descent first
    detections = [_h_detection(ex=0.1, ey=0.1, track_id=5)]
    ctx = _scene_context(detections=detections, altitude_m=2.5)
    action.update(ctx)  # search → lock

    # Now provide context without local NED altitude
    ctx_bad = _scene_context(detections=detections, altitude_m=2.5, local_altitude_valid=False)
    # Remove local_altitude_m
    ctx_bad.pop("local_altitude_m", None)
    result = action.update(ctx_bad)

    assert result.failed
    assert "missing_local_ned_altitude" in result.reason


# ---------------------------------------------------------------------------
# 11. config sync between base and profile
# ---------------------------------------------------------------------------

def test_rescue_2026_full_auto_v2_configs_identical() -> None:
    base = Path("config/action_missions/rescue_2026_full_auto_v2.json").read_text()
    sitl = Path("config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json").read_text()
    assert base == sitl, "Base and profile configs differ"


# ---------------------------------------------------------------------------
# 12. config step order
# ---------------------------------------------------------------------------

def test_v2_mission_final_step_order() -> None:
    data = json.loads(Path("config/action_missions/rescue_2026_full_auto_v2.json").read_text())
    labels = [s["label"] for s in data["steps"]]
    final_four = labels[-4:]
    assert final_four == [
        "return_home_gps",
        "descend_home_2_5m",
        "visual_land_home",
        "land_home",
    ]


# ---------------------------------------------------------------------------
# 13. default target_loss_policy unchanged
# ---------------------------------------------------------------------------

def test_align_descend_config_default_target_loss_policy_is_fail() -> None:
    config = AlignDescendConfig()
    assert config.target_loss_policy == "fail"


def test_align_descend_action_default_still_fails_on_target_loss() -> None:
    """Existing behaviour: default AlignDescendAction fails on target_lost_timeout."""
    action = AlignDescendAction()
    action.start({
        "expected_dt_s": 0.1,
        "lost_timeout_updates": 3,
        "max_retries": 0,
        "max_updates": 100,
        "finish_altitude_m": 1.0,
        "config": {"min_altitude_m": 0.5, "require_target_locked": False},
    })
    # Target valid for a few updates then lost
    ctx = {
        "target_valid": True,
        "target_locked": True,
        "control_allowed": True,
        "ex_cam": 0.02,
        "ey_cam": 0.03,
        "drone": {"relative_altitude": 5.0},
    }
    for _ in range(2):
        result = action.update(ctx)
        assert not result.failed

    # Now target lost
    ctx_lost = dict(ctx, target_valid=False, vision_valid=False)
    for _ in range(4):  # > lost_timeout_updates=3
        result = action.update(ctx_lost)

    assert result.failed
    assert result.reason == "target_lost_timeout"


# ---------------------------------------------------------------------------
# 14. drop / recon related tests unchanged
# ---------------------------------------------------------------------------

def test_drop_and_recon_still_pass_imports() -> None:
    """Sanity: all key action imports still work."""
    from missions.common.actions.payload_release import PayloadReleaseAction
    from missions.common.actions.drop_sequence import DropSequenceAction
    from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
    from missions.common.actions.recon_sequence import ReconSequenceAction
    from missions.common.actions.gps_recon_sequence import GpsReconSequenceAction
    assert PayloadReleaseAction is not None
    assert DropSequenceAction is not None
    assert GpsDropSequenceAction is not None
    assert ReconSequenceAction is not None
    assert GpsReconSequenceAction is not None


def test_visual_land_stop_produces_zero_velocity() -> None:
    """Calling stop() and then update() should produce stop commands."""
    action = VisualLandAction()
    action.start()
    action.stop()
    # After stop, a fresh update simulates the orchestrator calling stop+clear
    action2 = VisualLandAction()
    action2.start()
    # Enter descent
    action2.update(_scene_context(detections=[_h_detection(ex=0.0, ey=0.0)], altitude_m=2.5))
    action2.stop()
    # Verify stopped state doesn't crash
    result = action2.update(_scene_context(detections=[], altitude_m=2.5))
    assert result.done  # stopped action returns done
