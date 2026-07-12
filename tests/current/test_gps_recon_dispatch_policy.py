from app.action_dispatcher import ActionDispatcher
from app.dispatch.policy import ACTION_DISPATCH_POLICY


def test_gps_recon_sequence_policy_allows_only_flight_lifecycle_actions() -> None:
    dispatcher = ActionDispatcher()
    dispatcher.send_actions = True
    for action_type in ("global_goto", "flight_command", "yolo_lock_target", "clear_continuous_commands"):
        allowed, reason = dispatcher.gate(send_commands=True, action_type=action_type, action_name="gps_recon_sequence")
        assert allowed, (action_type, reason)
    allowed, reason = dispatcher.gate(send_commands=True, action_type="set_servo", action_name="gps_recon_sequence")
    assert not allowed and reason == "action_dispatch_not_enabled"
    assert "gps_recon_sequence" not in ACTION_DISPATCH_POLICY["set_servo"].allowed_actions


def test_gps_recon_sequence_policy_keeps_safety_gates() -> None:
    dispatcher = ActionDispatcher()
    allowed, reason = dispatcher.gate(send_commands=True, action_type="global_goto", action_name="gps_recon_sequence")
    assert not allowed and reason == "dry_run_only"
    dispatcher.send_actions = True
    allowed, reason = dispatcher.gate(send_commands=False, action_type="global_goto", action_name="gps_recon_sequence")
    assert not allowed and reason == "send_commands_disabled"
