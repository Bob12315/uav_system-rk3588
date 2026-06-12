from __future__ import annotations

from app.action_dispatcher import ActionDispatcher


class FakeLinkManager:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def set_mode(self, mode: str, priority: int = 5) -> None:
        self.calls.append(("set_mode", mode, priority))

    def arm(self, priority: int = 1) -> None:
        self.calls.append(("arm", priority))

    def takeoff(self, altitude_m: float, priority: int = 2) -> None:
        self.calls.append(("takeoff", altitude_m, priority))

    def land(self, priority: int = 2) -> None:
        self.calls.append(("land", priority))


def _dispatcher(send_actions: bool = True) -> ActionDispatcher:
    dispatcher = ActionDispatcher()
    dispatcher.send_actions = send_actions
    return dispatcher


def _dispatch(
    action: dict[str, object],
    *,
    action_name: str,
    send_actions: bool = True,
    send_commands: bool = True,
    link_manager: object | None = None,
) -> tuple[dict[str, list[dict[str, object]]], object | None]:
    fake_link = FakeLinkManager() if link_manager is None else link_manager
    dispatcher = _dispatcher(send_actions=send_actions)
    dispatch = dispatcher.dispatch_actions(
        [action],
        action_name=action_name,
        send_commands=send_commands,
        link_manager=fake_link,
    )
    return dispatch, fake_link


def test_set_mode_dispatches_when_gates_enabled() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "set_mode",
            "params": {"mode": "GUIDED"},
            "key": "takeoff_set_mode",
            "once": True,
            "priority": 2,
        },
        action_name="takeoff",
    )

    assert dispatch["sent"][0]["action_type"] == "set_mode"
    assert fake_link.calls == [("set_mode", "GUIDED", 2)]


def test_arm_dispatches_when_gates_enabled() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "arm",
            "params": {},
            "key": "takeoff_arm",
            "once": True,
            "priority": 1,
        },
        action_name="takeoff",
    )

    assert dispatch["sent"][0]["action_type"] == "arm"
    assert fake_link.calls == [("arm", 1)]


def test_takeoff_dispatches_when_gates_enabled() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "takeoff",
            "params": {"altitude_m": 3.0},
            "key": "takeoff_command",
            "once": True,
            "priority": 2,
        },
        action_name="takeoff",
    )

    assert dispatch["sent"][0]["action_type"] == "takeoff"
    assert fake_link.calls == [("takeoff", 3.0, 2)]


def test_land_dispatches_when_gates_enabled() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "land",
            "params": {},
            "key": "land_command",
            "once": True,
            "priority": 2,
        },
        action_name="land",
    )

    assert dispatch["sent"][0]["action_type"] == "land"
    assert fake_link.calls == [("land", 2)]


def test_takeoff_dry_run_gate_skips_without_calling_link_manager() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "takeoff",
            "params": {"altitude_m": 3.0},
            "key": "takeoff_command",
            "once": True,
            "priority": 2,
        },
        action_name="takeoff",
        send_actions=False,
        send_commands=True,
    )

    assert fake_link.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["reason"] == "dry_run_only"


def test_takeoff_send_commands_false_skips_without_calling_link_manager() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "takeoff",
            "params": {"altitude_m": 3.0},
            "key": "takeoff_command",
            "once": True,
            "priority": 2,
        },
        action_name="takeoff",
        send_actions=True,
        send_commands=False,
    )

    assert fake_link.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["reason"] == "send_commands_disabled"


def test_takeoff_action_name_mismatch_is_skipped() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "takeoff",
            "params": {"altitude_m": 3.0},
            "key": "takeoff_command",
            "once": True,
            "priority": 2,
        },
        action_name="goto_waypoint",
    )

    assert fake_link.calls == []
    assert dispatch["sent"] == []
    assert dispatch["skipped"][0]["reason"] == "action_dispatch_not_enabled"


def test_takeoff_land_dispatch_errors_when_link_manager_missing() -> None:
    dispatcher = _dispatcher()
    actions = [
        {
            "action_type": "set_mode",
            "params": {"mode": "GUIDED"},
            "key": "takeoff_set_mode",
            "once": True,
            "priority": 2,
        },
        {
            "action_type": "arm",
            "params": {},
            "key": "takeoff_arm",
            "once": True,
            "priority": 1,
        },
        {
            "action_type": "takeoff",
            "params": {"altitude_m": 3.0},
            "key": "takeoff_command",
            "once": True,
            "priority": 2,
        },
    ]

    dispatch = dispatcher.dispatch_actions(
        actions,
        action_name="takeoff",
        send_commands=True,
        link_manager=None,
    )
    land_dispatch = dispatcher.dispatch_actions(
        [
            {
                "action_type": "land",
                "params": {},
                "key": "land_command",
                "once": True,
                "priority": 2,
            }
        ],
        action_name="land",
        send_commands=True,
        link_manager=None,
    )

    assert [error["error"] for error in dispatch["errors"]] == [
        "telemetry_not_connected",
        "telemetry_not_connected",
        "telemetry_not_connected",
    ]
    assert land_dispatch["errors"][0]["error"] == "telemetry_not_connected"


def test_takeoff_invalid_altitude_goes_to_errors() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "takeoff",
            "params": {"altitude_m": -1.0},
            "key": "takeoff_command",
            "once": True,
            "priority": 2,
        },
        action_name="takeoff",
    )

    assert fake_link.calls == []
    assert dispatch["sent"] == []
    assert dispatch["errors"][0]["error"] == "invalid_takeoff_altitude"
