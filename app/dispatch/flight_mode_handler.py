from __future__ import annotations

from app.dispatch.normalizer import get_action_params


def dispatch_set_mode(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> dict[str, object]:
    params = get_action_params(action)
    raw_mode = params["mode"]
    mode = "" if raw_mode is None else str(raw_mode).strip().upper()
    priority = int(action.get("priority", params.get("priority", 2)))
    key = str(action.get("key") or "")
    if not mode:
        return {"status": "error", "reason": "empty_mode"}
    if link_manager is None:
        return {"status": "error", "reason": "telemetry_not_connected"}
    sender = getattr(link_manager, "set_mode", None)
    if not callable(sender):
        return {"status": "error", "reason": "set_mode_not_callable"}
    sender(mode, priority=priority)
    return {
        "status": "sent",
        "detail": {
            "action_type": "set_mode", "mode": mode,
            "priority": priority, "key": key,
        },
    }


def dispatch_arm(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> dict[str, object]:
    params = get_action_params(action)
    priority = int(action.get("priority", params.get("priority", 1)))
    key = str(action.get("key") or "")
    if link_manager is None:
        return {"status": "error", "reason": "telemetry_not_connected"}
    sender = getattr(link_manager, "arm", None)
    if not callable(sender):
        return {"status": "error", "reason": "arm_not_callable"}
    sender(priority=priority)
    return {
        "status": "sent",
        "detail": {
            "action_type": "arm", "priority": priority, "key": key,
        },
    }


def dispatch_takeoff(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> dict[str, object]:
    params = get_action_params(action)
    altitude_m = float(params["altitude_m"])
    priority = int(action.get("priority", params.get("priority", 2)))
    key = str(action.get("key") or "")
    if not altitude_m > 0.0:
        return {"status": "error", "reason": "invalid_takeoff_altitude"}
    if link_manager is None:
        return {"status": "error", "reason": "telemetry_not_connected"}
    sender = getattr(link_manager, "takeoff", None)
    if not callable(sender):
        return {"status": "error", "reason": "takeoff_not_callable"}
    sender(altitude_m, priority=priority)
    return {
        "status": "sent",
        "detail": {
            "action_type": "takeoff", "altitude_m": altitude_m,
            "priority": priority, "key": key,
        },
    }


def dispatch_land(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> dict[str, object]:
    params = get_action_params(action)
    priority = int(action.get("priority", params.get("priority", 2)))
    key = str(action.get("key") or "")
    if link_manager is None:
        return {"status": "error", "reason": "telemetry_not_connected"}
    clear_continuous = getattr(link_manager, "clear_continuous_commands", None)
    if callable(clear_continuous):
        clear_continuous()
    clear_nav = getattr(link_manager, "clear_pending_local_position_actions", None)
    if callable(clear_nav):
        clear_nav()
    sender = getattr(link_manager, "land", None)
    if not callable(sender):
        return {"status": "error", "reason": "land_not_callable"}
    sender(priority=priority)
    return {
        "status": "sent",
        "detail": {
            "action_type": "land", "priority": priority, "key": key,
        },
    }


def dispatch_condition_yaw(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> dict[str, object]:
    params = get_action_params(action)
    yaw_deg = float(params["yaw_deg"])
    yaw_speed_deg_s = float(params.get("yaw_speed_deg_s", 20.0))
    direction = int(params.get("direction", 0))
    relative = bool(params.get("relative", False))
    priority = int(action.get("priority", params.get("priority", 4)))
    key = str(action.get("key") or "")
    if link_manager is None:
        return {"status": "error", "reason": "telemetry_not_connected"}
    sender = getattr(link_manager, "condition_yaw", None)
    if not callable(sender):
        return {"status": "error", "reason": "condition_yaw_not_callable"}
    sender(yaw_deg, yaw_speed_deg_s, direction, relative, priority=priority)
    return {
        "status": "sent",
        "detail": {
            "action_type": "condition_yaw",
            "yaw_deg": yaw_deg,
            "yaw_speed_deg_s": yaw_speed_deg_s,
            "direction": direction,
            "relative": relative,
            "priority": priority,
            "key": key,
        },
    }
