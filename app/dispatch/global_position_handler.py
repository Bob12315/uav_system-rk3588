from __future__ import annotations

from app.dispatch.normalizer import get_action_params


def dispatch_global_goto(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> tuple[dict[str, object], str | None]:
    """Execute a ``global_goto`` dispatch through LinkManager."""
    params = get_action_params(action)
    lat = float(params["lat"])
    lon = float(params["lon"])
    alt = float(params["alt"])
    frame = int(params["frame"])
    priority = int(action.get("priority", 4))

    sender = getattr(link_manager, "global_goto", None)
    if not callable(sender):
        return ({"status": "skipped", "reason": "global_goto_dispatch_not_available"}, None)

    log_msg = (
        "action_lab dispatch global_goto input_frame=%s input_target=%s"
        " global_target=%s field_origin=(%s,%s) field_heading_yaw_rad=%s"
        " frame=%s priority=%s key=%s"
        % (
            action.get("input_frame"), action.get("input_target"),
            action.get("global_target"),
            action.get("field_origin_lat"), action.get("field_origin_lon"),
            action.get("field_heading_yaw_rad"), frame, priority, action.get("key"),
        )
    )
    sender(lat=lat, lon=lon, alt=alt, frame=frame, priority=priority)
    detail: dict[str, object] = {
        "action_type": "global_goto",
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "frame": frame,
        "key": str(action.get("key") or ""),
    }
    for name in (
        "input_frame", "input_target", "global_target",
        "field_origin_lat", "field_origin_lon", "field_heading_yaw_rad",
    ):
        if name in action:
            detail[name] = action[name]
    return ({"status": "sent", "detail": detail}, log_msg)
