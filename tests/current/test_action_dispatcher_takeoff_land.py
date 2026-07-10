from __future__ import annotations

import pytest
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

    def condition_yaw(
        self,
        yaw_deg: float,
        yaw_speed_deg_s: float = 20.0,
        direction: int = 0,
        relative: bool = False,
        priority: int = 4,
    ) -> None:
        self.calls.append(("condition_yaw", yaw_deg, yaw_speed_deg_s, direction, relative, priority))

    def global_goto(
        self,
        lat: float,
        lon: float,
        alt: float,
        frame: int,
        priority: int = 4,
        yaw_rad: float | None = None,
    ) -> None:
        self.calls.append(("global_goto", lat, lon, alt, frame, priority))

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


class FakeLandLinkManager(FakeLinkManager):
    def clear_continuous_commands(self) -> None:
        self.calls.append(("clear_continuous_commands",))

    def clear_pending_local_position_actions(self) -> None:
        self.calls.append(("clear_pending_local_position_actions",))


def test_land_dispatch_clears_motion_queues_before_land() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "land",
            "params": {},
            "key": "land_home_command",
            "once": True,
            "priority": 2,
        },
        action_name="land",
        link_manager=FakeLandLinkManager(),
    )

    assert dispatch["sent"][0]["action_type"] == "land"
    assert fake_link.calls == [
        ("clear_continuous_commands",),
        ("clear_pending_local_position_actions",),
        ("land", 2),
    ]


def test_condition_yaw_dispatches_for_yaw_align() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "condition_yaw",
            "params": {
                "yaw_deg": 90.0,
                "yaw_speed_deg_s": 25.0,
                "direction": 0,
                "relative": False,
            },
            "key": "yaw_align_condition_yaw",
            "once": True,
            "priority": 4,
        },
        action_name="yaw_align",
    )

    assert dispatch["sent"][0]["action_type"] == "condition_yaw"
    assert fake_link.calls == [("condition_yaw", 90.0, 25.0, 0, False, 4)]


def test_global_goto_dispatches_for_goto_waypoint() -> None:
    dispatch, fake_link = _dispatch(
        {
            "action_type": "global_goto",
            "params": {
                "lat": 34.0,
                "lon": 108.0,
                "alt": 5.0,
                "frame": 6,
            },
            "key": "goto_global",
            "once": False,
            "priority": 5,
        },
        action_name="goto_waypoint",
    )

    assert dispatch["sent"][0]["action_type"] == "global_goto"
    assert fake_link.calls == [("global_goto", 34.0, 108.0, 5.0, 6, 5)]

@pytest.mark.skip(reason="uses removed confirm_field_heading dispatch")
def test_takeoff_dispatches_when_gates_enabled() -> None:
    pass


# ── drop_sequence dispatch policy + clear_continuous_commands tests ──────────


from app.dispatch.policy import ACTION_DISPATCH_POLICY


def test_drop_sequence_dispatch_policy_allows_all_required_types() -> None:
    """drop_sequence must be in allowed_actions for these 5 action types."""
    required_types = [
        "local_position",
        "flight_command",
        "set_servo",
        "yolo_lock_target",
        "clear_continuous_commands",
    ]
    for action_type in required_types:
        rule = ACTION_DISPATCH_POLICY.get(action_type)
        assert rule is not None, f"missing policy rule for {action_type}"
        assert "drop_sequence" in rule.allowed_actions, (
            f"drop_sequence not in {action_type}.allowed_actions"
        )


class FakeLinkManagerWithClear:
    """FakeLinkManager that tracks clear_continuous_commands calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def clear_continuous_commands(self) -> None:
        self.calls.append("clear_continuous_commands")

    def clear_pending_local_position_actions(self) -> None:
        self.calls.append("clear_pending_local_position_actions")

    def stop_body_velocity(self) -> None:
        self.calls.append("stop_body_velocity")

    def stop_body_velocity_and_clear(self) -> None:
        self.calls.append("stop_body_velocity_and_clear")


def test_clear_continuous_commands_dispatch_calls_clear() -> None:
    """clear_continuous_commands action calls link_manager.clear_continuous_commands."""
    fake_link = FakeLinkManagerWithClear()
    dispatcher = _dispatcher(send_actions=True)
    dispatch = dispatcher.dispatch_actions(
        [{
            "action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": False},
            "key": "test_clear",
            "once": True,
            "priority": 10,
        }],
        action_name="drop_sequence",
        send_commands=True,
        link_manager=fake_link,
    )
    assert len(dispatch["sent"]) == 1
    assert dispatch["sent"][0]["action_type"] == "clear_continuous_commands"
    assert "clear_continuous_commands" in fake_link.calls
    # Must NOT call stop_body_velocity (that would create a new continuous zero)
    assert "stop_body_velocity" not in fake_link.calls
    # clear_pending_local_position=False → must not clear nav
    assert "clear_pending_local_position_actions" not in fake_link.calls


# ── SITL 前安全修复：zero+clear 连续队列无残留 ──────────────────────────


def test_zero_clear_dispatches_without_stop_body_velocity() -> None:
    """clear_continuous_commands dispatches without calling stop_body_velocity."""
    fake_link = FakeLinkManagerWithClear()
    dispatcher = _dispatcher(send_actions=True)

    clear = {
        "action_type": "clear_continuous_commands",
        "params": {"clear_pending_local_position": False},
        "key": "drop_sequence_clear_continuous_align_inactive_t0_p0_u5",
        "once": True,
        "priority": 10,
    }
    dispatch = dispatcher.dispatch_actions(
        [clear],
        action_name="drop_sequence",
        send_commands=True,
        link_manager=fake_link,
    )
    assert len(dispatch["sent"]) == 1
    assert dispatch["sent"][0]["action_type"] == "clear_continuous_commands"
    assert "clear_continuous_commands" in fake_link.calls
    # Must NOT call stop_body_velocity (that would create a new continuous zero)
    assert "stop_body_velocity" not in fake_link.calls


def test_clear_continuous_commands_with_pending_local_position() -> None:
    """clear_pending_local_position=True also clears navigation queue."""
    fake_link = FakeLinkManagerWithClear()
    dispatcher = _dispatcher(send_actions=True)
    dispatch = dispatcher.dispatch_actions(
        [{
            "action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": True},
            "key": "test_clear_nav",
            "once": True,
            "priority": 10,
        }],
        action_name="drop_sequence",
        send_commands=True,
        link_manager=fake_link,
    )
    assert len(dispatch["sent"]) == 1
    assert "clear_continuous_commands" in fake_link.calls
    assert "clear_pending_local_position_actions" in fake_link.calls


def test_clear_continuous_commands_no_link_manager_skipped() -> None:
    """clear_continuous_commands with None link_manager is skipped."""
    dispatcher = _dispatcher(send_actions=True)
    dispatch = dispatcher.dispatch_actions(
        [{
            "action_type": "clear_continuous_commands",
            "params": {},
            "key": "test_no_link",
            "once": True,
            "priority": 10,
        }],
        action_name="drop_sequence",
        send_commands=True,
        link_manager=None,
    )
    assert len(dispatch["skipped"]) == 1


def test_two_clear_actions_with_unique_keys_both_dispatch() -> None:
    """Two clear_continuous_commands with different keys must both be sent.

    This guards against the once=True dedup bug: if keys were identical,
    the second action would be skipped with once_already_dispatched.
    """
    fake_link = FakeLinkManagerWithClear()
    dispatcher = _dispatcher(send_actions=True)
    dispatch = dispatcher.dispatch_actions(
        [
            {
                "action_type": "clear_continuous_commands",
                "params": {"clear_pending_local_position": False},
                "key": "drop_sequence_clear_continuous_before_climb_t0_p1_u3",
                "once": True,
                "priority": 10,
            },
            {
                "action_type": "clear_continuous_commands",
                "params": {"clear_pending_local_position": False},
                "key": "drop_sequence_clear_continuous_before_goto_t1_p1_u0",
                "once": True,
                "priority": 10,
            },
        ],
        action_name="drop_sequence",
        send_commands=True,
        link_manager=fake_link,
    )
    assert len(dispatch["sent"]) == 2, (
        f"expected 2 sent, got {len(dispatch['sent'])}; "
        f"skipped={dispatch['skipped']}"
    )
    assert fake_link.calls.count("clear_continuous_commands") == 2


# ── recon_sequence dispatch policy tests ───────────────────────────────


def test_recon_sequence_dispatch_policy_allows_all_required_types() -> None:
    """recon_sequence must be in allowed_actions for these 4 action types."""
    required_types = [
        "local_position",
        "flight_command",
        "yolo_lock_target",
        "clear_continuous_commands",
    ]
    for action_type in required_types:
        rule = ACTION_DISPATCH_POLICY.get(action_type)
        assert rule is not None, f"missing policy rule for {action_type}"
        assert "recon_sequence" in rule.allowed_actions, (
            f"recon_sequence not in {action_type}.allowed_actions"
        )


def test_recon_sequence_clear_continuous_dispatch() -> None:
    """recon_sequence can dispatch clear_continuous_commands."""
    fake_link = FakeLinkManagerWithClear()
    dispatcher = _dispatcher(send_actions=True)
    dispatch = dispatcher.dispatch_actions(
        [{
            "action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": False},
            "key": "recon_sequence_clear_before_climb_t0_u1",
            "once": True,
            "priority": 10,
        }],
        action_name="recon_sequence",
        send_commands=True,
        link_manager=fake_link,
    )
    assert len(dispatch["sent"]) == 1
    assert dispatch["sent"][0]["action_type"] == "clear_continuous_commands"
    assert "clear_continuous_commands" in fake_link.calls


# ── SITL 前安全修复：send_stop_first 原子 stop-and-clear ──────────────


def test_clear_continuous_send_stop_first_calls_stop_and_clear() -> None:
    """send_stop_first=True → stop_body_velocity_and_clear, NOT clear_continuous_commands."""
    fake_link = FakeLinkManagerWithClear()
    dispatcher = _dispatcher(send_actions=True)
    dispatch = dispatcher.dispatch_actions(
        [{
            "action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": False, "send_stop_first": True},
            "key": "test_send_stop_first",
            "once": True,
            "priority": 10,
        }],
        action_name="recon_descend_observe",
        send_commands=True,
        link_manager=fake_link,
    )
    assert len(dispatch["sent"]) == 1
    assert dispatch["sent"][0]["action_type"] == "clear_continuous_commands"
    # Must call stop_body_velocity_and_clear, NOT clear_continuous_commands
    assert "stop_body_velocity_and_clear" in fake_link.calls
    assert "clear_continuous_commands" not in fake_link.calls


def test_recon_descend_observe_clear_continuous_policy_allowed() -> None:
    """recon_descend_observe must be allowed to dispatch clear_continuous_commands."""
    rule = ACTION_DISPATCH_POLICY.get("clear_continuous_commands")
    assert rule is not None
    assert "recon_descend_observe" in rule.allowed_actions, (
        "recon_descend_observe must have clear_continuous_commands permission"
    )
