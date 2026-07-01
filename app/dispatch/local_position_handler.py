from __future__ import annotations

from app.dispatch.normalizer import get_action_params

LOCAL_NED = 1


def dispatch_local_position(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> tuple[dict[str, object], str | None]:
    """Execute a ``local_position`` dispatch.

    Returns ``(result, log_message)`` where *log_message* is a
    pre-formatted log line (or ``None`` to skip logging).
    """
    params = get_action_params(action)
    x = float(params["x"])
    y = float(params["y"])
    z = float(params["z"])
    frame = int(params.get("frame", LOCAL_NED))
    yaw = None if params.get("yaw") is None else float(params["yaw"])
    priority = int(action.get("priority", 4))

    if frame == LOCAL_NED:
        wrapper = getattr(link_manager, "goto_local_ned", None)
        if callable(wrapper):
            log_msg = _fmt_goto_log(action, yaw, priority)
            wrapper(x_north_m=x, y_east_m=y, z_down_m=z, yaw_rad=yaw, priority=priority)
            return ({"status": "sent", "detail": _build_detail(action, x, y, z, frame, yaw)}, log_msg)

    sender = getattr(link_manager, "local_position", None)
    if not callable(sender):
        return ({"status": "skipped", "reason": "local_position_dispatch_not_available"}, None)
    if yaw is not None and not _accepts_keyword(sender, "yaw"):
        return ({"status": "skipped", "reason": "local_position_yaw_not_supported"}, None)
    log_msg = _fmt_local_log(action, frame, yaw, priority)
    sender(x, y, z, frame, yaw=yaw, priority=priority)
    return ({"status": "sent", "detail": _build_detail(action, x, y, z, frame, yaw)}, log_msg)


def _build_detail(
    action: dict[str, object],
    x: float, y: float, z: float, frame: int, yaw: float | None,
) -> dict[str, object]:
    d: dict[str, object] = {
        "action_type": "local_position",
        "x": x, "y": y, "z": z, "frame": frame,
        "key": str(action.get("key") or ""),
    }
    for name in (
        "input_frame", "input_target", "local_target",
        "field_origin_local_x", "field_origin_local_y",
        "field_heading_yaw_rad",
    ):
        if name in action:
            d[name] = action[name]
    if yaw is not None:
        d["yaw"] = yaw
    return d


def _fmt_goto_log(action: dict[str, object], yaw: float | None, priority: int) -> str:
    return (
        "action_lab dispatch goto_local_ned input_frame=%s input_target=%s"
        " local_target=%s field_origin=(%s,%s) field_heading_yaw_rad=%s"
        " yaw_rad=%s priority=%s key=%s"
        % (
            action.get("input_frame"), action.get("input_target"),
            action.get("local_target"),
            action.get("field_origin_local_x"), action.get("field_origin_local_y"),
            action.get("field_heading_yaw_rad"), yaw, priority, action.get("key"),
        )
    )


def _fmt_local_log(
    action: dict[str, object], frame: int, yaw: float | None, priority: int,
) -> str:
    return (
        "action_lab dispatch local_position input_frame=%s input_target=%s"
        " local_target=%s field_origin=(%s,%s) field_heading_yaw_rad=%s"
        " frame=%s yaw=%s priority=%s key=%s"
        % (
            action.get("input_frame"), action.get("input_target"),
            action.get("local_target"),
            action.get("field_origin_local_x"), action.get("field_origin_local_y"),
            action.get("field_heading_yaw_rad"), frame, yaw, priority, action.get("key"),
        )
    )


def _accepts_keyword(func, name: str) -> bool:
    import inspect
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD or p.name == name
        for p in sig.parameters.values()
    )
