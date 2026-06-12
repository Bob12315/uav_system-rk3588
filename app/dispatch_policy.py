from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DispatchRule:
    """A single rule that governs whether an action_type may be dispatched."""

    allowed_actions: set[str] = field(default_factory=set)
    requires_send_actions: bool = True
    requires_send_commands: bool = True
    continuous: bool = False
    once_respected: bool = True


ACTION_DISPATCH_POLICY: dict[str, DispatchRule] = {
    "local_position": DispatchRule(
        allowed_actions={"goto_waypoint", "survey_area", "multi_view_localize", "recon_scan"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "flight_command": DispatchRule(
        allowed_actions={"align_descend"},
        requires_send_actions=True,
        requires_send_commands=True,
        continuous=True,
        once_respected=False,
    ),
    "body_velocity": DispatchRule(
        allowed_actions={"align_descend"},
        requires_send_actions=True,
        requires_send_commands=True,
        continuous=True,
        once_respected=False,
    ),
    "set_servo": DispatchRule(
        allowed_actions={"payload_release"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "set_mode": DispatchRule(
        allowed_actions={"takeoff"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "arm": DispatchRule(
        allowed_actions={"takeoff"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "takeoff": DispatchRule(
        allowed_actions={"takeoff"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "land": DispatchRule(
        allowed_actions={"land"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "yolo_lock_target": DispatchRule(
        allowed_actions={"target_lock"},
        requires_send_actions=True,
        requires_send_commands=False,
    ),
}
