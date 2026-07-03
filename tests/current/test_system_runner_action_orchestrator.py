"""Integration tests: MissionOrchestrator + SystemRunner dry-run flow.

Verifies that configure_action_mission() can sequence real Action steps
through action_mission_tick() without touching the old _control_loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.app_config import build_arg_parser, load_app_config
from app.mission_orchestrator import MissionActionStep
from app.system_runner import SystemRunner

from tests.integration.test_action_lab_dispatch import FakeLink


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


def _field_steps():
    return [
        MissionActionStep(
            "goto_waypoint",
            {
                "x": 1.0,
                "y": 2.0,
                "altitude_m": 1.5,
                "waypoint_mode": "field",
                "yaw_mode": "field_heading",
            },
        )
    ]


def _confirm_and_sync_field_reference(runner: SystemRunner) -> None:
    service = runner.field_reference_service
    assert service.mark_local_origin(10.0, 20.0)["ok"] is True
    assert service.set_manual_heading(0.5)["ok"] is True
    assert service.confirm()["ok"] is True
    reference = service.reference
    assert runner.runtime_context_builder.confirm_field_reference(
        field_heading_yaw_rad=reference.field_heading_yaw_rad,
        origin_local_x=reference.origin_local_n_m,
        origin_local_y=reference.origin_local_e_m,
        origin_local_z=reference.origin_local_z_m,
        source="field_reference:test",
    ) is True


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


def test_field_mission_start_rejects_unconfirmed_reference() -> None:
    runner = _runner()
    runner.configure_action_mission(_field_steps())

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["failed"] is True
    assert payload["reason"] == "field_reference_not_confirmed"
    assert runner.action_runtime.runner.action_name is None


def test_explicit_field_waypoint_mode_is_conservatively_gated() -> None:
    runner = _runner()
    runner.configure_action_mission(
        [MissionActionStep("survey_area", {"waypoint_mode": "field"})]
    )

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_not_confirmed"


def test_field_mission_start_rejects_unsynced_reference() -> None:
    runner = _runner()
    runner.configure_action_mission(_field_steps())
    service = runner.field_reference_service
    assert service.mark_local_origin(10.0, 20.0)["ok"] is True
    assert service.set_manual_heading(0.5)["ok"] is True
    assert service.confirm()["ok"] is True

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_not_synced"
    assert service.reference.is_frozen is False


def test_field_mission_start_rejects_confirmed_but_not_ready_reference() -> None:
    runner = _runner()
    runner.configure_action_mission(_field_steps())
    service = runner.field_reference_service
    assert service.set_manual_origin(30.0, 120.0)["ok"] is True
    assert service.set_manual_heading(0.5)["ok"] is True
    assert service.confirm()["ok"] is True
    assert service.reference.is_ready() is False

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_not_ready"
    assert service.reference.is_frozen is False


def test_field_mission_start_rejects_mismatched_runtime_reference() -> None:
    runner = _runner()
    runner.configure_action_mission(_field_steps())
    _confirm_and_sync_field_reference(runner)
    runner.runtime_context_builder.field_origin_local_x += 0.01

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_not_synced"
    assert runner.field_reference_service.reference.is_frozen is False


def test_field_mission_start_freezes_before_starting_action() -> None:
    runner = _runner()
    runner.configure_action_mission(_field_steps())
    _confirm_and_sync_field_reference(runner)

    payload = runner.action_mission_start()

    assert payload["running"] is True
    assert runner.field_reference_service.reference.is_frozen is True
    assert runner.action_runtime.runner.action_name == "goto_waypoint"


def test_field_mission_start_rejects_freeze_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner()
    runner.configure_action_mission(_field_steps())
    _confirm_and_sync_field_reference(runner)
    monkeypatch.setattr(
        runner.field_reference_service,
        "freeze",
        lambda: {"ok": False, "error": "simulated freeze failure"},
    )

    payload = runner.action_mission_start()

    assert payload["running"] is False
    assert payload["reason"] == "field_reference_freeze_failed"
    assert runner.action_runtime.runner.action_name is None


def test_non_field_mission_starts_without_reference_or_freeze() -> None:
    runner = _runner()
    runner.configure_action_mission(_basic_steps())

    payload = runner.action_mission_start()

    assert payload["running"] is True
    assert runner.field_reference_service.reference.is_frozen is False


def test_takeoff_auto_confirm_does_not_overwrite_frozen_reference() -> None:
    runner = _runner()
    _confirm_and_sync_field_reference(runner)
    assert runner.field_reference_service.freeze()["ok"] is True
    builder = runner.runtime_context_builder
    before = (
        builder.field_heading_yaw_rad,
        builder.field_origin_local_x,
        builder.field_origin_local_y,
        builder.field_origin_local_z,
    )

    dispatcher = runner.action_runtime.dispatcher
    dispatch = dispatcher.dispatch_actions(
        [
            {
                "action_type": "confirm_field_heading",
                "params": {
                    "yaw_rad": -1.0,
                    "source": "takeoff_auto",
                    "drone": {
                        "local_position_valid": True,
                        "local_x": 999.0,
                        "local_y": 998.0,
                        "local_z": -50.0,
                    },
                },
                "key": "takeoff_confirm_field_heading",
                "once": True,
                "priority": 2,
            }
        ],
        action_name="takeoff",
        send_commands=False,
        link_manager=None,
    )

    assert dispatch["errors"] == []
    assert dispatch["sent"][0]["action_type"] == "confirm_field_heading"
    assert before == (
        builder.field_heading_yaw_rad,
        builder.field_origin_local_x,
        builder.field_origin_local_y,
        builder.field_origin_local_z,
    )
    assert runner.field_reference_service.reference.is_frozen is True


def test_takeoff_auto_confirm_does_not_overwrite_confirmed_reference() -> None:
    runner = _runner()
    _confirm_and_sync_field_reference(runner)
    builder = runner.runtime_context_builder
    before = (builder.field_heading_yaw_rad, builder.field_origin_local_x)

    ok = runner.protected_confirm_field_heading(
        yaw_rad=-1.0,
        drone={
            "local_position_valid": True,
            "local_x": 999.0,
            "local_y": 998.0,
            "local_z": -50.0,
        },
        source="takeoff_auto",
    )

    assert ok is True
    assert before == (builder.field_heading_yaw_rad, builder.field_origin_local_x)
    assert runner.field_reference_service.reference.is_frozen is False


def test_legacy_confirm_cannot_overwrite_frozen_reference() -> None:
    runner = _runner()
    _confirm_and_sync_field_reference(runner)
    assert runner.field_reference_service.freeze()["ok"] is True
    builder = runner.runtime_context_builder
    before = (builder.field_heading_yaw_rad, builder.field_origin_local_x)
    _set_snapshot(
        runner,
        {
            "drone": {
                "attitude_valid": True,
                "local_position_valid": True,
                "yaw": -1.0,
                "local_x": 999.0,
                "local_y": 998.0,
                "local_z": -50.0,
            }
        },
    )

    result = runner.confirm_field_heading_manual()

    assert result.ok is False
    assert "frozen" in result.message
    assert before == (builder.field_heading_yaw_rad, builder.field_origin_local_x)
