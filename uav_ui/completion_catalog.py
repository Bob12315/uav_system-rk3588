from __future__ import annotations

from itertools import product


_ACTIONS = ("on", "off", "toggle", "enable", "disable", "enabled", "disabled", "1", "0", "true", "false", "tog")
_CONTROLLERS = ("gimbal", "body", "approach", "all")
_STAGE_CONTROLLERS = ("APPROACH_TRACK", "OVERHEAD_HOLD", "CORRIDOR_FOLLOW", "IDLE", "auto", "clear")
_MISSIONS = ("visual_tracking", "rescue_competition")
_COMMON_FLIGHT_MODES = ("GUIDED", "LOITER", "RTL", "LAND", "STABILIZE", "ALT_HOLD", "AUTO")
_MESSAGE_NAMES = (
    "ATTITUDE",
    "GLOBAL_POSITION_INT",
    "LOCAL_POSITION_NED",
    "VFR_HUD",
    "BATTERY_STATUS",
    "GIMBAL_DEVICE_ATTITUDE_STATUS",
)


def build_completion_candidates() -> tuple[str, ...]:
    candidates = {
        "quit",
        "exit",
        "target ",
        "target next",
        "target prev",
        "target previous",
        "target lock ",
        "target unlock",
        "control ",
        "control send ",
        "control send_commands ",
        "control commands ",
        "switch_source ",
        "switch_source real",
        "switch_source sitl",
        "mode ",
        "arm",
        "arm throttle",
        "disarm",
        "takeoff ",
        "land",
        "condition_yaw ",
        "change_speed ",
        "set_home ",
        "set_home current",
        "global_goto ",
        "local_pos ",
        "reposition ",
        "set_roi_location ",
        "roi_none",
        "roi_none ",
        "gimbal_manager_configure",
        "gimbal_manager_configure ",
        "set_message_interval ",
        "message_interval ",
        "body_vel ",
        "yaw_rate ",
        "stop",
        "gimbal ",
        "gimbal_rate ",
        "pid reload",
        "stage reload",
        "stage config reload",
        "stage controllers reload",
        "mission list",
        "mission current",
        "mission status",
        "mission start",
        "mission reset",
        "mission switch ",
        "mission select ",
        "mission use ",
    }
    for root, controller, action in product(("controller", "controllers"), _CONTROLLERS, _ACTIONS):
        candidates.add(f"{root} {controller} {action}")
    for command, action in product(("control send", "control send_commands", "control commands"), _ACTIONS):
        candidates.add(f"{command} {action}")
    for root, mode in product(("stage",), _STAGE_CONTROLLERS):
        candidates.add(f"{root} {mode}")
        candidates.add(f"{root} mode {mode}")
    for command, mission in product(("mission switch", "mission select", "mission use"), _MISSIONS):
        candidates.add(f"{command} {mission}")
    for mode in _COMMON_FLIGHT_MODES:
        candidates.add(f"mode {mode}")
    for speed_type in ("ground", "air", "climb", "descent"):
        candidates.add(f"change_speed {speed_type}")
    for frame in ("relative", "global", "terrain"):
        candidates.add(f"global_goto {frame}")
    for frame in ("local", "offset", "body", "body_offset"):
        candidates.add(f"local_pos {frame}")
    for yaw_option in ("cw", "ccw", "shortest", "absolute", "relative"):
        candidates.add(f"condition_yaw {yaw_option}")
    for message in _MESSAGE_NAMES:
        candidates.add(f"set_message_interval {message} ")
        candidates.add(f"message_interval {message} ")
        candidates.add(f"set_message_interval {message} default")
        candidates.add(f"message_interval {message} default")
    for yaw_mode in ("follow", "lock"):
        candidates.add(f"gimbal_rate {yaw_mode}")
    return tuple(sorted(candidates, key=lambda item: item.lower()))


COMMAND_COMPLETIONS = build_completion_candidates()
