from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from execution.dispatcher import ActionDispatcher
from execution.authorization import RunAuthorization
from missions.common.actions.manual_step import ManualStepAction, body_step_to_local_target
from telemetry_link.frames import LOCAL_NED


@pytest.mark.parametrize(
    ("direction", "yaw", "expected"),
    [
        ("forward", 0.0, (11.0, 20.0, -3.0)),
        ("back", 0.0, (9.0, 20.0, -3.0)),
        ("right", 0.0, (10.0, 21.0, -3.0)),
        ("left", 0.0, (10.0, 19.0, -3.0)),
        ("up", 0.0, (10.0, 20.0, -4.0)),
        ("down", 0.0, (10.0, 20.0, -2.0)),
        ("forward", math.pi / 2, (10.0, 21.0, -3.0)),
        ("right", math.pi / 2, (9.0, 20.0, -3.0)),
    ],
)
def test_body_step_to_local_target_has_correct_signs(direction, yaw, expected) -> None:
    target = body_step_to_local_target(
        north_m=10.0, east_m=20.0, down_m=-3.0,
        yaw_rad=yaw, direction=direction, step_m=1.0,
    )
    assert (target.north_m, target.east_m, target.down_m) == pytest.approx(expected)


def _context(**overrides):
    drone = {
        "connected": True, "stale": False, "control_allowed": True,
        "local_position_valid": True, "attitude_valid": True,
        "local_x": 10.0, "local_y": 20.0, "local_z": -3.0, "yaw": 0.3,
    }
    drone.update(overrides)
    return {"drone": drone, "arm_heading_yaw_rad": 1.2}


def test_action_emits_local_ned_request_and_uses_arm_heading() -> None:
    action = ManualStepAction()
    action.start({"direction": "forward", "step_m": 1.0})
    result = action.update(_context())
    request = result.actions[0]
    assert result.done is True
    assert request["action_type"] == "local_position"
    assert request["params"]["frame"] == LOCAL_NED
    assert request["params"]["yaw"] == pytest.approx(1.2)


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"connected": False}, "telemetry_disconnected"),
        ({"stale": True}, "telemetry_stale"),
        ({"control_allowed": False}, "control_not_allowed"),
        ({"local_position_valid": False}, "local_position_unavailable"),
    ],
)
def test_action_rejects_unsafe_telemetry(override, reason) -> None:
    action = ManualStepAction()
    action.start({"direction": "forward", "step_m": 1.0})
    result = action.update(_context(**override))
    assert result.failed is True
    assert result.reason == reason
    assert result.actions == []


class _Manager:
    def __init__(self, *, source="sitl", stale=False):
        self.source = source
        self.sent = []
        self.state = SimpleNamespace(
            connected=True, stale=stale, control_allowed=True,
            local_position_valid=True, local_x=10.0, local_y=20.0, local_z=-3.0,
        )

    def get_active_source(self): return self.source
    def get_latest_drone_state(self): return self.state
    def local_position(self, *args, **kwargs): self.sent.append((args, kwargs))


def _request():
    action = ManualStepAction()
    action.start({"direction": "forward", "step_m": 1.0})
    return action.update(_context())


def test_dispatcher_requires_send_gate() -> None:
    manager = _Manager()
    dispatcher = ActionDispatcher()
    dispatcher.set_authorization(RunAuthorization.create(
        operator="test", scope_type="action", scope_name="manual_step",
        target_source="sitl", allowed_actions={"manual_step"},
    ))
    dispatch = dispatcher.dispatch_result(
        _request(), action_name="manual_step", send_commands=False, link_manager=manager,
    )
    assert manager.sent == []
    assert dispatch["skipped"][0]["reason"] == "send_commands_disabled"


def test_dispatcher_rejects_source_mismatch_and_stale() -> None:
    for manager, expected in ((_Manager(source="real"), "run_not_authorized"),
                              (_Manager(stale=True), "telemetry_stale")):
        dispatcher = ActionDispatcher()
        dispatcher.set_authorization(RunAuthorization.create(
            operator="test", scope_type="action", scope_name="manual_step",
            target_source="sitl", allowed_actions={"manual_step"},
        ))
        dispatch = dispatcher.dispatch_result(
            _request(), action_name="manual_step", send_commands=True, link_manager=manager,
        )
        assert manager.sent == []
        assert dispatch["skipped"][0]["reason"] == expected
