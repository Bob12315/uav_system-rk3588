from __future__ import annotations

import math

import pytest

from missions.common.actions.yaw_align import YawAlignAction


def _ctx(yaw: float, field: float = math.pi / 2) -> dict[str, object]:
    return {
        "field_heading_confirmed": True,
        "field_heading_yaw_rad": field,
        "drone": {"yaw": yaw},
    }


def test_yaw_align_sends_condition_yaw_when_not_aligned() -> None:
    action = YawAlignAction()
    action.start({"tolerance_deg": 3.0, "min_hold_updates": 2, "key": "align_test"})

    result = action.update(_ctx(math.radians(40.0)))

    assert result.reason == "yaw_align_sent"
    assert result.actions[0]["action_type"] == "condition_yaw"
    assert result.actions[0]["params"]["yaw_deg"] == pytest.approx(90.0)
    assert result.actions[0]["params"]["relative"] is False


def test_yaw_align_waits_for_consecutive_aligned_updates() -> None:
    action = YawAlignAction()
    action.start({"tolerance_deg": 3.0, "min_hold_updates": 2})

    assert action.update(_ctx(math.radians(40.0))).reason == "yaw_align_sent"
    waiting = action.update(_ctx(math.radians(89.0)))
    done = action.update(_ctx(math.radians(90.5)))

    assert waiting.reason == "yaw_align_waiting"
    assert done.done is True
    assert done.reason == "yaw_aligned"


def test_yaw_align_fails_without_confirmed_field_heading() -> None:
    action = YawAlignAction()
    action.start()

    result = action.update({"drone": {"yaw": 0.0}, "field_heading_confirmed": False})

    assert result.failed is True
    assert result.reason == "missing_target_yaw"


def test_yaw_align_times_out() -> None:
    action = YawAlignAction()
    action.start({"max_updates": 1, "min_hold_updates": 2})

    assert action.update(_ctx(math.radians(40.0))).reason == "yaw_align_sent"
    result = action.update(_ctx(math.radians(40.0)))

    assert result.failed is True
    assert result.reason == "yaw_align_timeout"
