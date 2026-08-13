from __future__ import annotations

import pytest

from missions.common.actions.change_speed import ChangeSpeedAction


def test_change_ground_speed_emits_once_and_completes() -> None:
    action = ChangeSpeedAction()
    action.start({"speed_mps": 1.0, "speed_type": "ground", "key": "recon_speed"})

    result = action.update({})

    assert result.done
    assert result.reason == "speed_change_sent"
    assert result.actions == [{
        "action_type": "change_speed",
        "params": {"speed_mps": 1.0, "speed_type": 1},
        "key": "recon_speed",
        "once": True,
        "priority": 4,
    }]
    assert action.update({}).actions == []


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_change_speed_rejects_invalid_speed(value: float) -> None:
    with pytest.raises(ValueError, match="speed_mps"):
        ChangeSpeedAction().start({"speed_mps": value})


def test_change_speed_rejects_invalid_type() -> None:
    with pytest.raises(ValueError, match="speed_type"):
        ChangeSpeedAction().start({"speed_mps": 1.0, "speed_type": "sideways"})
