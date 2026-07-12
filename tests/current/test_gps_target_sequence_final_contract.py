from missions.common.actions.gps_recon_sequence import GpsReconSequenceAction
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.gps_target_sequence_core import GpsTargetSequenceCore


class _Core(GpsTargetSequenceCore):
    def _sequence_namespace(self): return "gps_recon"


def test_recon_transition_reason_contract() -> None:
    action = GpsReconSequenceAction()
    assert action._sequence_reason("lock_start") == "gps_recon_lock_start"
    assert action._sequence_reason("align_start") == "gps_recon_align_start"


def test_stop_detection_requires_full_zero_command_and_namespace_clear() -> None:
    core = _Core()
    bad_zero = {"action_type": "flight_command", "params": {"vx_cmd": 0.0, "vy_cmd": 0.0, "vz_cmd": 0.0, "yaw_rate_cmd": 0.5}}
    wrong_clear = {"action_type": "clear_continuous_commands", "params": {"send_stop_first": True}, "key": "gps_drop_clear_failed"}
    actions = core._ensure_stop_actions([bad_zero, wrong_clear], "failed")
    assert sum(item["action_type"] == "flight_command" for item in actions) == 2
    assert any(item.get("key") == "gps_recon_clear_failed" for item in actions)


def test_stop_detection_does_not_duplicate_full_zero_or_matching_clear() -> None:
    core = _Core()
    zero = core._zero_velocity_command()
    clear = core._clear_continuous_command("failed")
    actions = core._ensure_stop_actions([zero, clear], "failed")
    assert actions == [zero, clear]


def test_clear_namespaces_are_wrapper_specific() -> None:
    drop = GpsDropSequenceAction(); recon = GpsReconSequenceAction()
    assert drop._clear_continuous_command("aligned")["key"] == "gps_drop_clear_aligned"
    assert recon._clear_continuous_command("aligned")["key"] == "gps_recon_clear_aligned"
