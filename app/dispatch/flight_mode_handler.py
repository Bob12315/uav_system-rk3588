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
