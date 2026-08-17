from __future__ import annotations

import time

from execution.normalizer import get_action_params
from execution.handlers.submission import submission_outcome


def dispatch_set_servo(
    action: dict[str, object],
    *,
    link_manager: object | None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Execute a ``set_servo`` dispatch.

    Returns ``(result, servo_command)`` where *result* is the dispatch
    status dict and *servo_command* is the updated last-servo-command
    state (or ``None`` to leave it unchanged).
    """
    if link_manager is None:
        params = (
            action.get("params")
            if isinstance(action.get("params"), dict)
            else {}
        )
        sc: dict[str, object] = {
            "channel": params.get("channel"),
            "pwm": params.get("pwm"),
            "priority": action.get("priority", 3),
            "time": time.time(),
            "key": str(action.get("key") or ""),
            "ack": None,
            "error": "telemetry_not_connected",
        }
        return (
            {"status": "error", "reason": "telemetry_not_connected"},
            sc,
        )

    params = get_action_params(action)
    channel = int(params.get("servo_output", params.get("channel")))
    pwm = int(params["pwm"])
    priority = int(action.get("priority", 3))

    wrapper = getattr(link_manager, "set_servo_output_pwm", None)
    if callable(wrapper):
        receipt = wrapper(servo_output=channel, pwm=pwm, priority=priority)
    else:
        fn = getattr(link_manager, "set_servo", None)
        if not callable(fn):
            return (
                {"status": "error", "reason": "set_servo_not_callable"},
                None,
            )
        receipt = fn(channel, pwm, priority=priority)

    sc = {
        "channel": channel,
        "pwm": pwm,
        "priority": priority,
        "time": time.time(),
        "key": str(action.get("key") or ""),
        "ack": None,
        "error": None,
    }
    result = submission_outcome(receipt, {
            "action_type": "set_servo",
            "channel": channel,
            "pwm": pwm,
            "key": str(action.get("key") or ""),
        })
    return result, sc
