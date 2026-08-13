# Archived composite-Action behavior lock; replaced by Mission subflow contracts.
from __future__ import annotations

from typing import Any

import pytest

from execution.dispatcher import ActionDispatcher
from execution.authorization import RunAuthorization
from missions.common.actions import gps_drop_sequence as sequence_module
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.result import ActionResult
from telemetry_link.frames import BODY_NED, LOCAL_NED


class FakeLinkManager:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def global_goto(
        self,
        *,
        lat: float,
        lon: float,
        alt: float,
        frame: int,
        priority: int,
        yaw_rad: float | None = None,
    ) -> None:
        self.calls.append(("global_goto", lat, lon, alt, frame, priority, yaw_rad))

    def send_body_velocity(
        self,
        *,
        vx_forward_mps: float,
        vy_right_mps: float,
        vz_down_mps: float,
        yaw_rate_rad_s: float | None = None,
    ) -> None:
        self.calls.append(("send_body_velocity", vx_forward_mps, vy_right_mps, vz_down_mps, yaw_rate_rad_s))

    def send_velocity_command(
        self,
        vx: float,
        vy: float,
        vz: float,
        *,
        frame: int,
        yaw_rad: float | None = None,
        yaw_rate_rad_s: float | None = None,
    ) -> None:
        self.calls.append(("send_velocity_command", vx, vy, vz, frame, yaw_rad, yaw_rate_rad_s))

    def stop_body_velocity_and_clear(self) -> None:
        self.calls.append(("stop_body_velocity_and_clear",))

    def clear_pending_local_position_actions(self) -> None:
        self.calls.append(("clear_pending_local_position_actions",))

    def set_servo_output_pwm(self, *, servo_output: int, pwm: int, priority: int) -> None:
        self.calls.append(("set_servo_output_pwm", servo_output, pwm, priority))


class FakeYoloClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def lock_target(self, track_id: int) -> None:
        self.calls.append(("lock_target", track_id))


def _global(key: str) -> dict[str, Any]:
    return {
        "action_type": "global_goto",
        "params": {"lat": 34.0, "lon": 108.0, "alt": 5.0, "frame": 6},
        "key": key,
        "once": False,
        "priority": 4,
    }


def _velocity(key: str, vx: float, vy: float, vz: float) -> dict[str, Any]:
    return {
        "action_type": "flight_command",
        "params": {
            "type": "flight_command",
            "valid": True,
            "active": True,
            "enable_body": True,
            "vx_cmd": vx,
            "vy_cmd": vy,
            "vz_cmd": vz,
            "yaw_rate_cmd": 0.0,
            "priority": 5,
        },
        "key": key,
        "once": False,
    }


def test_gps_action_dispatcher_sends_all_eight_required_paths() -> None:
    link = FakeLinkManager()
    yolo = FakeYoloClient()
    dispatcher = ActionDispatcher(yolo_client=yolo)

    cases = [
        ("gps_multi_view_localize", _global("scan_global")),
        ("gps_drop_sequence", _global("drop_global")),
        ("gps_drop_sequence", _velocity("align_nonzero", 0.2, -0.1, 0.15)),
        ("gps_drop_sequence", _velocity("align_zero", 0.0, 0.0, 0.0)),
        (
            "gps_drop_sequence",
            {
                "action_type": "clear_continuous_commands",
                "params": {"send_stop_first": True, "clear_pending_local_position": False},
                "key": "align_clear",
                "once": True,
            },
        ),
        ("gps_target_lock", {"action_type": "yolo_lock_target", "params": {"track_id": 41}}),
        ("gps_drop_sequence", {"action_type": "yolo_lock_target", "params": {"track_id": 42}}),
        (
            "gps_drop_sequence",
            {
                "action_type": "set_servo",
                "params": {"channel": 8, "pwm": 1200},
                "key": "payload_release",
                "once": True,
                "priority": 5,
            },
        ),
    ]
    dispatcher.set_authorization(RunAuthorization.create(
        operator="test",
        scope_type="mission",
        scope_name="gps",
        target_source="sitl",
        allowed_actions={name for name, _ in cases},
    ))

    sent: list[dict[str, Any]] = []
    for action_name, action in cases:
        result = dispatcher.dispatch_effects(
            ActionResult.typed([action]),
            action_name=action_name,
            send_commands=True,
            link_manager=link,
        )
        assert result["errors"] == []
        assert result["skipped"] == []
        assert len(result["sent"]) == 1
        sent.extend(result["sent"])

    assert len(sent) == 8
    assert [item["action_type"] for item in sent] == [
        "global_goto",
        "global_goto",
        "flight_command",
        "flight_command",
        "clear_continuous_commands",
        "yolo_lock_target",
        "yolo_lock_target",
        "set_servo",
    ]
    assert link.calls == [
        ("global_goto", 34.0, 108.0, 5.0, 6, 4, None),
        ("global_goto", 34.0, 108.0, 5.0, 6, 4, None),
        ("send_body_velocity", 0.2, -0.1, 0.15, None),
        ("send_body_velocity", 0.0, 0.0, 0.0, None),
        ("stop_body_velocity_and_clear",),
        ("set_servo_output_pwm", 8, 1200, 5),
    ]
    assert yolo.calls == [("lock_target", 41), ("lock_target", 42)]


@pytest.mark.parametrize("authorized,send_commands", [(False, True), (True, False)])
def test_gps_motion_dispatch_still_requires_both_send_gates(
    authorized: bool, send_commands: bool
) -> None:
    link = FakeLinkManager()
    dispatcher = ActionDispatcher()
    if authorized:
        dispatcher.set_authorization(RunAuthorization.create(
            operator="test",
            scope_type="action",
            scope_name="gps_drop_sequence",
            target_source="sitl",
            allowed_actions={"gps_drop_sequence"},
        ))
    result = dispatcher.dispatch_effects(
        ActionResult.typed([_velocity("gated", 0.2, 0.0, 0.0)]),
        action_name="gps_drop_sequence",
        send_commands=send_commands,
        link_manager=link,
    )
    assert result["sent"] == []
    assert link.calls == []


class _ImmediateGoto:
    def start(self, params: dict[str, Any]) -> None:
        self.params = params

    def update(self, context: dict[str, Any]) -> ActionResult:
        return ActionResult(done=True, reason="waypoint_reached")


class _ImmediateLock:
    def start(self, params: dict[str, Any]) -> None:
        self.params = params

    def update(self, context: dict[str, Any]) -> ActionResult:
        return ActionResult(
            effects=ActionResult.typed([{"action_type": "yolo_lock_target", "params": {"track_id": 77}}]),
            done=True,
            reason="gps_target_locked",
        )


class _ImmediateYawAlign:
    def start(self, params: dict[str, Any]) -> None:
        self.params = params

    def update(self, context: dict[str, Any]) -> ActionResult:
        return ActionResult(done=True, reason="yaw_aligned")


def test_real_gps_sequence_align_matches_v1_yaw_hold_local_ned_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sequence_module, "GotoWaypointAction", _ImmediateGoto)
    monkeypatch.setattr(sequence_module, "GpsTargetLockAction", _ImmediateLock)
    # yaw_align no longer part of gps_drop_sequence
    sequence = GpsDropSequenceAction()
    sequence.start(
        {
            "targets": [
                {"valid": True, "target_id": "t0", "lat": 34.0, "lon": 108.0},
                {"valid": True, "target_id": "t1", "lat": 34.001, "lon": 108.001},
            ],
            "payloads": [
                {"payload_id": "p0", "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}]},
                {"payload_id": "p1", "servo_outputs": [{"channel": 9, "release_pwm": 1250, "hold_pwm": 1750}]},
            ],
        }
    )
    context = {
        "relative_altitude": 5.0,
        "target_valid": True,
        "target_locked": True,
        "control_allowed": True,
        "ex_cam": 0.03,
        "ey_cam": 0.04,
        "local_altitude_m": 5.0,
        "local_altitude_valid": True,
        "drone": {"relative_altitude": 5.0, "attitude_valid": True, "yaw": 0.9},
    }

    sequence.update(context)  # goto -> yaw_align
    sequence.update(context)  # yaw_align -> lock
    sequence.update(context)  # lock -> align
    align_result = sequence.update(context)
    assert len(align_result.actions) == 1
    actual_action = align_result.actions[0]
    command = actual_action["params"]
    assert actual_action["action_type"] == "flight_command"
    # default hold mode: yaw_hold_rad from attitude
    assert abs(command.get("yaw_hold_rad", 0) - 0.9) < 0.01  # approx drone.yaw
    assert command.get("yaw_rate_cmd", 0) == pytest.approx(0.0)
    assert command["vx_cmd"] != 0.0
    assert command["vy_cmd"] != 0.0
    assert command["vz_cmd"] != 0.0

    link = FakeLinkManager()
    dispatcher = ActionDispatcher()
    dispatcher.set_authorization(RunAuthorization.create(
        operator="test",
        scope_type="action",
        scope_name="gps_drop_sequence",
        target_source="sitl",
        allowed_actions={"gps_drop_sequence"},
    ))
    dispatch = dispatcher.dispatch_effects(
        ActionResult.typed([actual_action]),
        action_name="gps_drop_sequence",
        send_commands=True,
        link_manager=link,
    )

    assert dispatch["errors"] == []
    assert dispatch["skipped"] == []
    assert len(dispatch["sent"]) == 1
    sent_detail = dispatch["sent"][0]
    assert sent_detail["frame"] == LOCAL_NED
    assert sent_detail["vx_cmd"] == pytest.approx(command["vx_cmd"])
    assert sent_detail["vy_cmd"] == pytest.approx(command["vy_cmd"])
    assert sent_detail["vz_cmd"] == pytest.approx(command["vz_cmd"])
    # Default hold mode: yaw_hold_rad present → dispatcher uses send_velocity_command(LOCAL_NED)
    assert link.calls[0][0] == "send_velocity_command"
    assert link.calls[0][1] != 0.0  # vx
    assert link.calls[0][2] != 0.0  # vy
    assert link.calls[0][3] != 0.0  # vz
    assert link.calls[0][4] == LOCAL_NED  # frame
    assert any(call[0] == "send_velocity_command" for call in link.calls)


def test_gps_sequence_invalid_target_stops_and_clears_with_zero_yaw_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sequence_module, "GotoWaypointAction", _ImmediateGoto)
    monkeypatch.setattr(sequence_module, "GpsTargetLockAction", _ImmediateLock)
    # yaw_align no longer part of gps_drop_sequence
    sequence = GpsDropSequenceAction()
    sequence.start(
        {
            "targets": [
                {"valid": True, "target_id": "t0", "lat": 34.0, "lon": 108.0},
                {"valid": True, "target_id": "t1", "lat": 34.001, "lon": 108.001},
            ],
            "payloads": [
                {"payload_id": "p0", "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}]},
                {"payload_id": "p1", "servo_outputs": [{"channel": 9, "release_pwm": 1250, "hold_pwm": 1750}]},
            ],
        }
    )
    context = {"relative_altitude": 5.0, "target_valid": True, "target_locked": True,
               "control_allowed": True, "ex_cam": 0.03, "ey_cam": 0.04,
               "local_altitude_m": 5.0, "local_altitude_valid": True,
               "drone": {"relative_altitude": 5.0}, "control_allowed": False}
    sequence.update(context)
    sequence.update(context)
    sequence.update(context)
    waiting = sequence.update(context)

    assert waiting.reason == "gps_drop_align_inactive"
    assert [action["action_type"] for action in waiting.actions] == [
        "flight_command", "clear_continuous_commands"
    ]
    assert waiting.actions[0]["params"]["vx_cmd"] == pytest.approx(0.0)
    assert waiting.actions[0]["params"]["vy_cmd"] == pytest.approx(0.0)
    assert waiting.actions[0]["params"]["vz_cmd"] == pytest.approx(0.0)
    assert waiting.actions[0]["params"]["yaw_rate_rad_s"] == pytest.approx(0.0)


def test_gps_sequence_align_default_yaw_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    """With default hold yaw mode, align commands include yaw_hold_rad from attitude."""
    monkeypatch.setattr(sequence_module, "GotoWaypointAction", _ImmediateGoto)
    monkeypatch.setattr(sequence_module, "GpsTargetLockAction", _ImmediateLock)
    # yaw_align no longer part of gps_drop_sequence
    sequence = GpsDropSequenceAction()
    sequence.start({
        "targets": [{"valid": True, "target_id": "t0", "lat": 34.0, "lon": 108.0}],
        "payloads": [
            {"payload_id": "p0", "servo_outputs": [{"channel": 8, "release_pwm": 1200, "hold_pwm": 1700}]},
            {"payload_id": "p1", "servo_outputs": [{"channel": 9, "release_pwm": 1250, "hold_pwm": 1750}]},
        ],
    })
    ctx = {"target_valid": True, "target_locked": True, "control_allowed": True,
           "ex_cam": 0.0, "ey_cam": 0.0, "relative_altitude": 5.0,
           "drone": {"relative_altitude": 5.0, "attitude_valid": True, "yaw": 1.2}}
    sequence.update(ctx)  # goto
    sequence.update(ctx)  # yaw_align
    sequence.update(ctx)  # lock
    result = sequence.update(ctx)  # align
    assert result.reason == "gps_drop_align"
    command = result.actions[0]["params"]
    assert command.get("yaw_rate_cmd", 0) == pytest.approx(0.0)
    # default hold mode: yaw_hold_rad from drone attitude
    assert abs(command.get("yaw_hold_rad", 999) - 1.2) < 0.1
