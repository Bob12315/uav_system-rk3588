from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from app.runtime_context import RuntimeContextBuilder
from app.web_status_service import WebStatusService


def test_snapshot_lock_only_copies_shared_state():
    lock = threading.Lock()
    callback_names = []

    def outside_lock(name, result):
        def callback():
            assert not lock.locked(), f"{name} called while snapshot lock is held"
            callback_names.append(name)
            return result

        return callback

    @dataclass
    class SwitchState:
        send_commands: bool = False

    class Switches:
        def snapshot(self):
            assert not lock.locked(), "runtime switches called under snapshot lock"
            callback_names.append("switches")
            return SwitchState()

    class ActionRuntime:
        def status_payload(self, *, send_commands):
            assert send_commands is False
            assert not lock.locked(), "Action runtime called under snapshot lock"
            callback_names.append("action_runtime")
            return {"status": {}}

    class LinkManager:
        def get_active_source(self):
            assert not lock.locked(), "LinkManager called under snapshot lock"
            callback_names.append("link_manager")
            return "sitl"

    service = WebStatusService(
        runtime_context_builder=RuntimeContextBuilder(),
        get_snapshot=lambda: {"drone": {}},
        lock=lock,
        controller_switches=Switches(),
        control_command_log=deque(["command"]),
        system_events=deque([{"message": "event"}]),
        action_lab_enabled=True,
        get_action_runtime=outside_lock("get_action_runtime", ActionRuntime()),
        get_action_mission_status_payload=outside_lock("mission", {"running": False}),
        get_link_manager=outside_lock("get_link_manager", LinkManager()),
        get_latest_localization_result=outside_lock("localization", {}),
        get_latest_drop_targets_result=outside_lock("drop_targets", {}),
        get_latest_recon_inspection_result=outside_lock("recon", {}),
        get_latest_drop_workflow_result=outside_lock("drop_workflow", {}),
    )

    snapshot = service.snapshot()

    assert snapshot["active_source"] == "sitl"
    assert snapshot["control_commands"] == ["command"]
    assert snapshot["events"] == [{"message": "event"}]
    assert {
        "switches",
        "get_action_runtime",
        "action_runtime",
        "mission",
        "get_link_manager",
        "link_manager",
        "localization",
        "drop_targets",
        "recon",
        "drop_workflow",
    }.issubset(callback_names)
