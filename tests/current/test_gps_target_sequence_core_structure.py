from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.gps_recon_sequence import GpsReconSequenceAction
from missions.common.actions.gps_target_sequence_core import GpsTargetSequenceCore


def test_wrappers_do_not_own_flight_phase_methods() -> None:
    for wrapper in (GpsDropSequenceAction, GpsReconSequenceAction):
        for name in ("_update_goto", "_update_lock", "_update_align", "_update_climb"):
            assert name not in wrapper.__dict__
    for name in ("_update_goto", "_update_lock", "_update_align", "_update_operation", "_update_climb"):
        assert name in GpsTargetSequenceCore.__dict__
