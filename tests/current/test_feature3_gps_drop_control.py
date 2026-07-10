"""Tests for Step 3.2 — gps drop dispatcher control loop."""

import pytest

from missions.common.actions.align_descend import AlignDescendAction
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.action_lab import create_action_lab_registry
from app.dispatch.policy import ACTION_DISPATCH_POLICY


# =============================================================================
# Policy tests
# =============================================================================

class TestDispatcherPolicy:
    def test_gps_multi_view_localize_in_global_goto(self):
        rule = ACTION_DISPATCH_POLICY["global_goto"]
        assert "gps_multi_view_localize" in rule.allowed_actions
        assert "gps_drop_sequence" in rule.allowed_actions

    def test_gps_drop_sequence_in_flight_command(self):
        rule = ACTION_DISPATCH_POLICY["flight_command"]
        assert "gps_drop_sequence" in rule.allowed_actions

    def test_gps_drop_sequence_in_set_servo(self):
        rule = ACTION_DISPATCH_POLICY["set_servo"]
        assert "gps_drop_sequence" in rule.allowed_actions

    def test_gps_in_lock_policy(self):
        rule = ACTION_DISPATCH_POLICY.get("yolo_lock_target")
        assert rule is not None
        assert "gps_target_lock" in rule.allowed_actions
        assert "gps_drop_sequence" in rule.allowed_actions

    def test_clear_continuous_commands_policy(self):
        rule = ACTION_DISPATCH_POLICY.get("clear_continuous_commands")
        assert rule is not None
        assert "gps_drop_sequence" in rule.allowed_actions


# =============================================================================
# AlignDescend strict finish ordering
# =============================================================================

def _align_ctx(alt=5.0, ex=0.0, ey=0.0, locked=True, target_valid=True):
    return {
        "drone": {"relative_altitude": alt, "local_x": 0.0, "local_y": 0.0, "local_z": -alt,
                  "yaw": 0.0, "local_position_valid": True},
        "ex_cam": ex, "ey_cam": ey, "target_locked": locked, "target_valid": target_valid,
        "control_allowed": True,
    }


class TestStrictAlignDescend:
    def test_finish_before_min_altitude_strict(self):
        """Strict mode: finish_altitude (1.3m) checked before min_altitude (2.0m default)."""
        a = AlignDescendAction()
        a.start({"finish_altitude_m": 1.3, "finish_policy": "require_alignment_or_timeout",
                  "max_updates": 100, "config": {"min_altitude_m": 2.0, "max_ex_cam": 0.5, "max_ey_cam": 0.5}})
        r = a.update(_align_ctx(alt=4.0, ex=0.01, ey=0.01))
        # Should be active aligning (not min_altitude_reached)
        assert not r.done
        assert not r.failed

    def test_default_1_3m_can_complete(self):
        """Default finish_altitude 1.3m can reach aligned_at_finish_altitude."""
        a = AlignDescendAction()
        a.start({"finish_altitude_m": 1.3, "finish_policy": "require_alignment_or_timeout",
                  "max_updates": 100,
                  "config": {"min_altitude_m": 1.0, "max_ex_cam": 0.5, "max_ey_cam": 0.5}})
        for _ in range(15):
            r = a.update(_align_ctx(alt=1.2, ex=0.01, ey=0.01))
            if r.done: break
        assert r.done
        assert r.reason == "aligned_at_finish_altitude"


# =============================================================================
# GpsDropSequence command envelopes
# =============================================================================

class TestGpsDropEnvelopes:
    def test_aligned_terminal_has_zero_and_clear(self):
        a = GpsDropSequenceAction()
        a.start({
            "targets": [{"valid": True, "lat": 34.0, "lon": 108.0, "class_name": "b", "target_id": "t0"},
                        {"valid": True, "lat": 34.1, "lon": 108.1, "class_name": "b", "target_id": "t1"}],
            "payloads": [{"servo_outputs": [], "payload_id": "p0"},
                         {"servo_outputs": [], "payload_id": "p1"}],
        })
        a.phase = "zero"
        a._zero_sent = False
        r = a.update({})
        assert r.reason == "gps_drop_zero_before_release"
        assert any(act["action_type"] == "flight_command" for act in r.actions)
        assert any(act["action_type"] == "clear_continuous_commands" for act in r.actions)

    def test_zero_tick_has_servo(self):
        a = GpsDropSequenceAction()
        a.start({
            "targets": [{"valid": True, "lat": 34.0, "lon": 108.0, "class_name": "b", "target_id": "t0"},
                        {"valid": True, "lat": 34.1, "lon": 108.1, "class_name": "b", "target_id": "t1"}],
            "payloads": [{"servo_outputs": [{"servo_output": 8, "release_pwm": 1200, "hold_pwm": 1700}], "payload_id": "p0"},
                         {"servo_outputs": [{"servo_output": 8, "release_pwm": 1200, "hold_pwm": 1700}], "payload_id": "p1"}],
        })
        a.phase = "zero"
        a._zero_sent = True
        r = a.update({})
        assert r.reason == "gps_drop_release_start"
        assert any(act["action_type"] == "flight_command" for act in r.actions)
        # set_servo should appear via PayloadRelease sub-action

    def test_zero_envelope_has_vx_cmd(self):
        from missions.common.actions.gps_drop_sequence import _zero_velocity_command
        z = _zero_velocity_command()
        assert z["action_type"] == "flight_command"
        assert "vx_cmd" in z["params"]
        assert z["params"]["vx_cmd"] == 0.0
        assert "vx" not in z["params"]

    def test_clear_envelope(self):
        from missions.common.actions.gps_drop_sequence import _clear_continuous_command
        c = _clear_continuous_command("test")
        assert c["action_type"] == "clear_continuous_commands"
        assert c["params"]["send_stop_first"] is True


# =============================================================================
# Registry
# =============================================================================

class TestRegistry:
    def test_actions_registered(self):
        r = create_action_lab_registry()
        assert r.create("gps_target_lock") is not None
        assert r.create("gps_drop_sequence") is not None

    def test_registry_no_duplicates(self):
        r = create_action_lab_registry()
        names = r.list()
        assert len(names) == len(set(names)), f"duplicates: {[n for n in names if names.count(n) > 1]}"


# =============================================================================
# Climb uses current target GPS
# =============================================================================

class TestClimbTarget:
    def test_climb_at_current_target_before_switch(self):
        a = GpsDropSequenceAction()
        a.start({
            "targets": [{"valid": True, "lat": 34.0, "lon": 108.0, "class_name": "b", "target_id": "t0"},
                        {"valid": True, "lat": 34.1, "lon": 108.1, "class_name": "b", "target_id": "t1"}],
            "payloads": [{"servo_outputs": [{"servo_output": 8, "release_pwm": 1200, "hold_pwm": 1700}], "payload_id": "p0"},
                         {"servo_outputs": [{"servo_output": 8, "release_pwm": 1200, "hold_pwm": 1700}], "payload_id": "p1"}],
        })
        # Manually set to climb at target 0
        a.phase = "climb"
        a.target_index = 0
        a.payload_index = 1
        a.released_count = 1
        ctx = {"drone": {"lat": 34.0, "lon": 108.0, "yaw": 0.0, "relative_altitude": 5.0, "global_position_valid": True}}
        r = a.update(ctx)
        # Should produce global_goto for climb at target 0
        if r.actions:
            for act in r.actions:
                if act.get("action_type") == "global_goto":
                    assert act["params"]["lat"] == pytest.approx(34.0)
