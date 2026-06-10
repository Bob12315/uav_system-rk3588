"""Integration tests: MissionOrchestrator + SystemRunner dry-run flow.

Verifies that configure_action_mission() can sequence real Action steps
through action_mission_tick() without touching the old _control_loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.app_config import build_arg_parser, load_app_config
from app.mission_orchestrator import MissionActionStep
from app.system_runner import SystemRunner

from tests.test_action_lab_dispatch import FakeLink


# ── helpers ──────────────────────────────────────────────────────────


def _runner() -> SystemRunner:
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    runner.services.link_manager = FakeLink()
    return runner


def _basic_steps():
    return [
        MissionActionStep(
            "goto_waypoint",
            {"x": 1.0, "y": 0.0, "altitude_m": 1.5, "yaw_mode": "hold"},
        ),
        MissionActionStep(
            "payload_release",
            {
                "servo_outputs": [
                    {"channel": 8, "release_pwm": 1200, "hold_pwm": 1700},
                ],
                "payload_id": "p1",
                "target_id": "t1",
                "release_wait_updates": 1,
            },
        ),
    ]


def _at_target_snapshot():
    """A snapshot where goto_waypoint should consider itself done (drone at target)."""
    return {
        "drone": {
            "local_x": 1.0,
            "local_y": 0.0,
            "local_z": -1.5,
            "armed": True,
            "yaw": 0.0,
            "relative_altitude": 1.5,
        },
        "perception": {},
        "scene": {},
        "gimbal": {},
        "link": {},
        "health": {},
        "command": {},
        "mission_detail": {},
    }


def _set_snapshot(runner: SystemRunner, snapshot: dict):
    with runner.control_command_log_lock:
        runner.latest_snapshot = snapshot


# ── tests ────────────────────────────────────────────────────────────


def test_configure_action_mission_status_is_enabled() -> None:
    runner = _runner()
    runner.configure_action_mission(_basic_steps())

    payload = runner.action_mission_status_payload()
    assert payload["enabled"] is True
    assert payload["running"] is False
    assert payload["current_action"] == "goto_waypoint"
    assert payload["current_index"] == 0


def test_start_then_tick_advances_to_payload_release() -> None:
    runner = _runner()
    runner.configure_action_mission(_basic_steps())
    _set_snapshot(runner, _at_target_snapshot())

    orchestrator = runner.action_mission_orchestrator
    orchestrator.start()
    payload = runner.action_mission_tick()

    # After one tick with the drone at target, goto_waypoint should be done
    # and orchestrator should have advanced to payload_release.
    assert payload["current_action"] == "payload_release"
    assert payload["current_index"] == 1


def test_send_commands_false_skips_payload_release_dispatch() -> None:
    runner = _runner()
    runner.configure_action_mission(_basic_steps())
    _set_snapshot(runner, _at_target_snapshot())

    runner.action_mission_orchestrator.start()
    # first tick: goto_waypoint done, advances to payload_release
    runner.action_mission_tick()

    # second tick: payload_release, but send_commands=False
    runner.controller_switches.set_send_commands(False)
    payload = runner.action_mission_tick()

    assert runner.services.link_manager.calls == []
    assert payload["current_action"] == "payload_release"


def test_send_commands_true_dispatches_set_servo_output_pwm() -> None:
    # Fresh runner — no previous ticks.
    runner = _runner()
    runner.configure_action_mission(_basic_steps())

    # directly configure a one-step mission that only does payload_release
    runner.configure_action_mission([
        MissionActionStep(
            "payload_release",
            {
                "servo_outputs": [
                    {"channel": 8, "release_pwm": 1200, "hold_pwm": 1700},
                ],
                "payload_id": "p1",
                "target_id": "t1",
                "release_wait_updates": 1,
            },
        ),
    ])
    _set_snapshot(runner, _at_target_snapshot())

    runner.action_mission_orchestrator.start()
    runner.controller_switches.set_send_commands(True)
    runner.action_mission_tick()

    assert ("set_servo_output_pwm", (8, 1200), 3) in runner.services.link_manager.calls


def test_action_lab_still_works_alongside_mission_orchestrator() -> None:
    runner = _runner()
    runner.configure_action_mission(_basic_steps())

    # action_lab should still function normally
    result = runner.action_lab_start_action("goto_waypoint", {"x": 1.0, "y": 0.0, "altitude_m": 1.5, "yaw_mode": "hold"}, send_actions=False)
    assert result.reason == "action_started"

    status = runner.action_lab_tick()
    payload = runner.action_lab_status_payload()
    assert payload["dry_run_only"] is True
    assert payload["send_actions"] is False
