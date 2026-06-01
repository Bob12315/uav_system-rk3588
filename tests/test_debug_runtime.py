from app.debug_runtime import DebugRuntime
from missions.base import MissionOutput
from missions.common.control.debug_config import StageDebugConfig


def test_force_mode_returns_overridden_copy_of_mission_output() -> None:
    original = MissionOutput(
        active_mode="APPROACH_TRACK",
        stage="DROP_ALIGN",
        hold_reason="aligning_drop",
        detail={"target_error_offset": {"ex_cam": 0.1}},
    )

    overridden = DebugRuntime(
        StageDebugConfig(force_mode="OVERHEAD_HOLD")
    ).apply_mission_override(original)

    assert overridden is not original
    assert overridden.active_mode == "OVERHEAD_HOLD"
    assert overridden.previous_stage == "APPROACH_TRACK"
    assert overridden.stage == "DROP_ALIGN"
    assert overridden.hold_reason == "debug_force_mode"
    assert overridden.detail == original.detail
    assert overridden.detail is not original.detail
    assert original.active_mode == "APPROACH_TRACK"
