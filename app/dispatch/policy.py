from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# SafetyGate — pure static check, zero side effects
# ---------------------------------------------------------------------------

class SafetyGate:
    """Thin, auditable safety gate that enforces the two hard cut-off
    switches *before* any per-action-type policy lookup.

    When requires_run_authorization / requires_send_commands are provided,
    they are checked against the global flags.  If not provided, both
    default to True (i.e. the gate is always required).
    """

    @staticmethod
    def check(
        *,
        run_authorized: bool,
        send_commands: bool,
        requires_run_authorization: bool = True,
        requires_send_commands: bool = True,
    ) -> tuple[bool, str]:
        if requires_run_authorization and not run_authorized:
            return False, "run_not_authorized"
        if requires_send_commands and not send_commands:
            return False, "send_commands_disabled"
        return True, "action_dispatch_enabled"


# ---------------------------------------------------------------------------
# DispatchRule + ACTION_DISPATCH_POLICY — pure data, zero side effects
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DispatchRule:
    """A single rule that governs whether an action_type may be dispatched."""

    allowed_actions: set[str] = field(default_factory=set)
    requires_run_authorization: bool = True
    requires_send_commands: bool = True
    continuous: bool = False
    once_respected: bool = True


ACTION_DISPATCH_POLICY: dict[str, DispatchRule] = {
    "local_position": DispatchRule(
        allowed_actions={"goto_waypoint", "survey_area", "multi_view_localize", "recon_scan", "recon_inspect_target", "drop_sequence", "recon_sequence"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "global_goto": DispatchRule(
        allowed_actions={"goto_waypoint", "multi_view_localize", "gps_multi_view_localize", "gps_drop_sequence", "gps_recon_sequence", "gps_recon_area_scan"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "flight_command": DispatchRule(
        allowed_actions={"align_descend", "recon_inspect_target", "payload_release", "recon_descend_observe", "drop_sequence", "recon_sequence", "gps_drop_sequence", "gps_recon_sequence", "visual_land"},
        requires_run_authorization=True,
        requires_send_commands=True,
        continuous=True,
        once_respected=False,
    ),
    "body_velocity": DispatchRule(
        allowed_actions={"align_descend", "recon_inspect_target"},
        requires_run_authorization=True,
        requires_send_commands=True,
        continuous=True,
        once_respected=False,
    ),
    "set_servo": DispatchRule(
        allowed_actions={"payload_release", "drop_sequence", "gps_drop_sequence"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "set_mode": DispatchRule(
        allowed_actions={"takeoff"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "arm": DispatchRule(
        allowed_actions={"takeoff"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "takeoff": DispatchRule(
        allowed_actions={"takeoff"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "land": DispatchRule(
        allowed_actions={"land"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "condition_yaw": DispatchRule(
        allowed_actions={"yaw_align", "gps_multi_view_localize"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "change_speed": DispatchRule(
        allowed_actions={"change_speed"},
        requires_run_authorization=True,
        requires_send_commands=True,
    ),
    "yolo_lock_target": DispatchRule(
        allowed_actions={"target_lock", "recon_inspect_target", "drop_sequence", "recon_sequence", "gps_target_lock", "gps_drop_sequence", "gps_recon_sequence", "visual_land"},
        requires_run_authorization=True,
        requires_send_commands=False,
    ),
    "clear_continuous_commands": DispatchRule(
        allowed_actions={"drop_sequence", "recon_sequence", "recon_descend_observe", "gps_drop_sequence", "gps_recon_sequence", "visual_land"},
        requires_run_authorization=True,
        requires_send_commands=True,
        once_respected=False,
    ),
}


ACTION_REQUEST_CAPABILITIES: dict[str, frozenset[str]] = {}
for _request_type, _rule in ACTION_DISPATCH_POLICY.items():
    for _action_name in _rule.allowed_actions:
        ACTION_REQUEST_CAPABILITIES.setdefault(_action_name, set()).add(_request_type)
ACTION_REQUEST_CAPABILITIES = {
    name: frozenset(request_types)
    for name, request_types in ACTION_REQUEST_CAPABILITIES.items()
}


def action_requires_run_authorization(action_name: str) -> bool:
    return action_name in ACTION_REQUEST_CAPABILITIES
