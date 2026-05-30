from __future__ import annotations

from collections.abc import Callable

from command_dispatcher import CommandResult, dispatch_text_command
from link_manager import LinkManager

from uav_ui.control_switches import ControlRuntimeSwitches, ControlSwitchSnapshot
from uav_ui.yolo_command_client import YoloCommandClient


_CONTINUOUS_MANUAL_COMMANDS = {"body_vel", "yaw_rate", "stop", "gimbal_rate"}
_MANUAL_COMMANDS = {
    "switch_source",
    "mode",
    "arm",
    "disarm",
    "takeoff",
    "land",
    "condition_yaw",
    "change_speed",
    "set_home",
    "global_goto",
    "local_pos",
    "reposition",
    "set_roi_location",
    "roi_none",
    "gimbal_manager_configure",
    "set_message_interval",
    "message_interval",
    "body_vel",
    "yaw_rate",
    "stop",
    "gimbal",
    "gimbal_rate",
}


def build_ui_command_handler(
    manager: LinkManager,
    *,
    controller_switches: ControlRuntimeSwitches | None = None,
    yolo_client: YoloCommandClient | None = None,
    mission_command_handler: Callable[[list[str]], CommandResult] | None = None,
    stage_override_handler: Callable[[str | None], CommandResult] | None = None,
    stage_config_reload_handler: Callable[[], CommandResult] | None = None,
) -> Callable[[str], CommandResult]:
    def _handle(command: str) -> CommandResult:
        own_result = _dispatch_ui_command(
            command,
            manager=manager,
            controller_switches=controller_switches,
            yolo_client=yolo_client,
            mission_command_handler=mission_command_handler,
            stage_override_handler=stage_override_handler,
            stage_config_reload_handler=stage_config_reload_handler,
        )
        if own_result is not None:
            return own_result
        command_root = _command_root(command)
        sending_disabled_before_dispatch = False
        if command_root in _CONTINUOUS_MANUAL_COMMANDS:
            sending_disabled_before_dispatch = _disable_control_sending_for_manual_command(
                manager,
                controller_switches,
            )
        result = dispatch_text_command(manager, command)
        if result.ok and command_root in _MANUAL_COMMANDS and not sending_disabled_before_dispatch:
            _disable_control_sending_for_manual_command(manager, controller_switches)
        return result

    return _handle


def _dispatch_ui_command(
    command: str,
    *,
    manager: LinkManager,
    controller_switches: ControlRuntimeSwitches | None,
    yolo_client: YoloCommandClient | None,
    mission_command_handler: Callable[[list[str]], CommandResult] | None,
    stage_override_handler: Callable[[str | None], CommandResult] | None,
    stage_config_reload_handler: Callable[[], CommandResult] | None,
) -> CommandResult | None:
    parts = command.strip().split()
    if not parts:
        return CommandResult(False, "empty command")

    root = parts[0].lower()
    if root in {"controller", "controllers"}:
        return _dispatch_controller_command(parts, controller_switches)
    if root == "control":
        return _dispatch_control_command(parts, manager, controller_switches)
    if root == "target":
        return _dispatch_target_command(parts, yolo_client)
    if root == "task":
        return _dispatch_stage_override_command(parts, stage_override_handler)
    if root == "mission":
        mission_result = _dispatch_mission_command(parts, mission_command_handler)
        if mission_result is not None:
            return mission_result
        return CommandResult(
            False,
            "format: mission list | mission switch <name> | mission start | mission reset | mission current",
        )
    if root == "pid":
        return _dispatch_stage_config_command(parts, stage_config_reload_handler)
    if root in {"stage", "stages"}:
        if len(parts) >= 2 and parts[1].lower() in {"reload", "load", "config", "controllers"}:
            return _dispatch_stage_config_command(parts, stage_config_reload_handler)
        return _dispatch_stage_override_command(parts, stage_override_handler)
    return None


def _dispatch_controller_command(
    parts: list[str],
    controller_switches: ControlRuntimeSwitches | None,
) -> CommandResult:
    if controller_switches is None:
        return CommandResult(False, "controller switching is not available in this UI")
    if len(parts) != 3:
        return CommandResult(False, "format: controller <gimbal|body|approach|all> <on|off|toggle>")
    name = parts[1].lower()
    action = parts[2].lower()
    if name not in {"gimbal", "body", "approach", "all"}:
        return CommandResult(False, "controller name must be gimbal, body, approach, or all")
    if action in {"on", "enable", "enabled", "1", "true"}:
        snapshot = controller_switches.set_controller(name, True)
    elif action in {"off", "disable", "disabled", "0", "false"}:
        snapshot = controller_switches.set_controller(name, False)
    elif action in {"toggle", "tog"}:
        snapshot = controller_switches.toggle_controller(name)
    else:
        return CommandResult(False, "controller action must be on, off, or toggle")
    return CommandResult(True, f"controllers {format_controller_snapshot(snapshot)}")


def _dispatch_control_command(
    parts: list[str],
    manager: LinkManager,
    controller_switches: ControlRuntimeSwitches | None,
) -> CommandResult:
    if controller_switches is None:
        return CommandResult(False, "control runtime switching is not available in this UI")
    if len(parts) != 3 or parts[1].lower() not in {"send", "send_commands", "commands"}:
        return CommandResult(False, "format: control send <on|off|toggle>")
    action = parts[2].lower()
    if action in {"on", "enable", "enabled", "1", "true"}:
        snapshot = controller_switches.set_send_commands(True)
    elif action in {"off", "disable", "disabled", "0", "false"}:
        snapshot = controller_switches.set_send_commands(False)
        _clear_continuous_commands(manager)
    elif action in {"toggle", "tog"}:
        snapshot = controller_switches.toggle_send_commands()
        if not snapshot.send_commands:
            _clear_continuous_commands(manager)
    else:
        return CommandResult(False, "control send action must be on, off, or toggle")
    return CommandResult(True, f"control send_commands={'ON' if snapshot.send_commands else 'OFF'}")


def _dispatch_target_command(
    parts: list[str],
    yolo_client: YoloCommandClient | None,
) -> CommandResult:
    if yolo_client is None:
        return CommandResult(False, "target switching is not available in this UI")
    if len(parts) < 2:
        return CommandResult(False, "format: target <next|prev|lock <track_id>|unlock>")
    action = parts[1].lower()
    try:
        if action == "next":
            yolo_client.send("switch_next")
            return CommandResult(True, "target switch_next sent")
        if action in {"prev", "previous"}:
            yolo_client.send("switch_prev")
            return CommandResult(True, "target switch_prev sent")
        if action == "unlock":
            yolo_client.send("unlock_target")
            return CommandResult(True, "target unlock_target sent")
        if action == "lock":
            if len(parts) != 3:
                return CommandResult(False, "format: target lock <track_id>")
            track_id = int(parts[2])
            yolo_client.send("lock_target", track_id=track_id)
            return CommandResult(True, f"target lock_target sent track_id={track_id}")
    except ValueError:
        return CommandResult(False, "target lock track_id must be an integer")
    except Exception as exc:
        return CommandResult(False, f"target command failed: {exc}")
    return CommandResult(False, "target action must be next, prev, lock, or unlock")


def _dispatch_mission_command(
    parts: list[str],
    mission_command_handler: Callable[[list[str]], CommandResult] | None,
) -> CommandResult | None:
    if len(parts) < 2:
        if mission_command_handler is None:
            return CommandResult(False, "mission switching is not available in this UI")
        return mission_command_handler([])
    action = parts[1].lower()
    if action not in {"list", "ls", "switch", "select", "use", "stage", "start", "reset", "current", "status"}:
        return None
    if mission_command_handler is None:
        return CommandResult(False, "mission switching is not available in this UI")
    return mission_command_handler(parts[1:])


def _dispatch_stage_override_command(
    parts: list[str],
    stage_override_handler: Callable[[str | None], CommandResult] | None,
) -> CommandResult:
    if stage_override_handler is None:
        return CommandResult(False, "stage override is not available in this UI")
    if len(parts) == 2 and parts[1].lower() in {"auto", "clear"}:
        return stage_override_handler(None)
    if len(parts) == 2:
        return stage_override_handler(parts[1])
    if len(parts) == 3 and parts[1].lower() == "mode":
        if parts[2].lower() in {"auto", "clear"}:
            return stage_override_handler(None)
        return stage_override_handler(parts[2])
    return CommandResult(False, "format: stage mode <APPROACH_TRACK|OVERHEAD_HOLD|auto>")


def _dispatch_stage_config_command(
    parts: list[str],
    stage_config_reload_handler: Callable[[], CommandResult] | None,
) -> CommandResult:
    if stage_config_reload_handler is None:
        return CommandResult(False, "mission stage config reload is not available in this UI")
    if len(parts) == 2 and parts[1].lower() in {"reload", "load"}:
        return stage_config_reload_handler()
    if (
        len(parts) == 3
        and parts[1].lower() in {"config", "controllers"}
        and parts[2].lower() in {"reload", "load"}
    ):
        return stage_config_reload_handler()
    return CommandResult(False, "format: pid reload | stage reload | stage config reload")


def format_controller_snapshot(snapshot: ControlSwitchSnapshot) -> str:
    return (
        f"G={'ON' if snapshot.gimbal else 'OFF'} "
        f"B={'ON' if snapshot.body else 'OFF'} "
        f"A={'ON' if snapshot.approach else 'OFF'} "
        f"SEND={'ON' if snapshot.send_commands else 'OFF'}"
    )


def _command_root(command: str) -> str:
    parts = command.strip().split(maxsplit=1)
    return parts[0].lower() if parts else ""


def _disable_control_sending_for_manual_command(
    manager: LinkManager,
    controller_switches: ControlRuntimeSwitches | None,
) -> bool:
    if controller_switches is None:
        return False
    controller_switches.set_send_commands(False)
    _clear_continuous_commands(manager)
    return True


def _clear_continuous_commands(manager: LinkManager) -> None:
    clear_sender = getattr(manager, "clear_continuous_commands", None)
    if callable(clear_sender):
        clear_sender()
