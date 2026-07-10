"""Tests for Feature 3.1 — complete gps drop safety control loop."""

import math
import pytest

from missions.common.actions.align_descend import AlignDescendAction
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.select_drop_targets import SelectDropTargetsAction
from missions.common.actions.gps_target_lock import GpsTargetLockAction
from missions.common.actions.action_lab import create_action_lab_registry


# =============================================================================
# Strict AlignDescend
# =============================================================================

def _align_ctx(alt=5.0, ex=0.0, ey=0.0, locked=True, target_valid=True):
    return {
        "drone": {"relative_altitude": alt, "local_x": 0.0, "local_y": 0.0, "local_z": -alt,
                  "yaw": 0.0, "local_position_valid": True},
        "ex_cam": ex, "ey_cam": ey, "target_locked": locked, "target_valid": target_valid,
        "control_allowed": True,
    }

class TestStrictAlignDescend:
    def test_finish_altitude_not_aligned_strict(self):
        a = AlignDescendAction()
        a.start({"finish_altitude_m": 3.0, "finish_policy": "require_alignment_or_timeout",
                  "max_updates": 100, "config": {"min_altitude_m": 1.0}})
        # Altitude at finish but not aligned (ex=0.5 which is > max_ex_cam=0.06)
        r = a.update(_align_ctx(alt=2.5, ex=0.5))
        assert not r.done
        assert not r.failed
        assert r.reason == "aligning_at_finish_altitude"
        # Check command has vz=0
        cmd = r.detail.get("command", {})
        assert cmd.get("vz_cmd", 0.0) == 0.0

    def test_finish_altitude_aligned_hold_strict(self):
        a = AlignDescendAction()
        a.start({"finish_altitude_m": 5.0, "finish_policy": "require_alignment_or_timeout",
                  "max_updates": 100, "config": {"min_altitude_m": 1.0, "max_ex_cam": 0.5, "max_ey_cam": 0.5}})
        # Give aligned context (ex/ey small) at finish altitude
        for _ in range(10):
            r = a.update(_align_ctx(alt=4.0, ex=0.01, ey=0.01))
            if r.done: break
        assert r.done
        assert r.reason == "aligned_at_finish_altitude"

    def test_strict_max_updates_timeout(self):
        a = AlignDescendAction()
        a.start({"finish_policy": "require_alignment_or_timeout", "max_updates": 3, "finish_altitude_m": 1.0})
        for _ in range(5):
            r = a.update(_align_ctx(alt=5.0, ex=0.5))
            if r.failed: break
        assert r.failed
        assert r.reason == "align_descend_timeout"

    def test_legacy_mode_unchanged(self):
        """Legacy mode still returns finish_altitude_reached."""
        a = AlignDescendAction()
        a.start({"finish_altitude_m": 3.0, "max_updates": 50, "config": {"min_altitude_m": 1.0}})
        r = a.update(_align_ctx(alt=2.5, ex=0.5))
        assert r.done
        assert r.reason in ("finish_altitude_reached", "min_altitude_reached")

    def test_invalid_policy_raises(self):
        with pytest.raises(ValueError):
            a = AlignDescendAction()
            a.start({"finish_policy": "invalid"})


# =============================================================================
# GpsDropSequence
# =============================================================================

def _gps_target(idx, lat=34.0, lon=108.0):
    return {"valid": True, "lat": lat, "lon": lon, "class_name": "bucket",
            "target_id": f"t{idx}", "id": f"t{idx}"}

def _payload(idx):
    return {"servo_outputs": [{"servo_output": 8, "release_pwm": 1200, "hold_pwm": 1700}],
            "payload_id": f"p{idx}"}

class TestGpsDropSequence:
    def test_requires_two_targets(self):
        a = GpsDropSequenceAction()
        with pytest.raises(ValueError, match="2 valid GPS targets"):
            a.start({"targets": [_gps_target(1)], "payloads": [_payload(1), _payload(2)]})

    def test_requires_two_payloads(self):
        a = GpsDropSequenceAction()
        with pytest.raises(ValueError, match="2 payloads"):
            a.start({"targets": [_gps_target(1), _gps_target(2)], "payloads": [_payload(1)]})

    def test_duplicate_target_id_skipped(self):
        a = GpsDropSequenceAction()
        with pytest.raises(ValueError, match="2 valid GPS targets"):
            a.start({"targets": [_gps_target(1), _gps_target(1)], "payloads": [_payload(1), _payload(2)]})

    def test_goto_produces_global_action(self):
        a = GpsDropSequenceAction()
        a.start({"targets": [_gps_target(0), _gps_target(1, lon=108.001)],
                  "payloads": [_payload(1), _payload(2)]})
        ctx = {"drone": {"lat": 34.0, "lon": 108.0, "yaw": 0.0, "relative_altitude": 5.0,
                         "global_position_valid": True}}
        r = a.update(ctx)
        assert r.reason == "gps_drop_goto"
        assert len(r.actions) > 0
        assert r.actions[0]["action_type"] == "global_goto"

    def test_altitude_validation(self):
        with pytest.raises(ValueError, match="must be finite and > 0"):
            a = GpsDropSequenceAction()
            a.start({"targets": [_gps_target(0), _gps_target(1)],
                      "payloads": [_payload(1), _payload(2)],
                      "approach_altitude_m": -1.0})


# =============================================================================
# Lock failure
# =============================================================================

class TestLockFailure:
    def test_lock_failure_no_payload_consumed(self):
        a = GpsDropSequenceAction()
        a.start({
            "targets": [_gps_target(0), _gps_target(1, lon=108.001)],
            "payloads": [_payload(1), _payload(2)],
            "goto_max_updates": 200,
        })
        ctx = {"drone": {"lat": 34.0, "lon": 108.0, "yaw": 0.0, "relative_altitude": 5.0,
                         "global_position_valid": True}}
        # Goto
        for _ in range(5): a.update(ctx)
        # Lock - will likely fail without detections
        for _ in range(300):
            r = a.update(ctx)
            if r.failed: break
        assert r.failed
        assert a.released_count == 0
        assert a.payload_index == 0


# =============================================================================
# Registry
# =============================================================================

class TestRegistry:
    def test_actions_registered(self):
        r = create_action_lab_registry()
        assert r.create("gps_target_lock") is not None
        assert r.create("gps_drop_sequence") is not None
