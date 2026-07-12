from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# SafetyGate — pure static check, zero side effects
# ---------------------------------------------------------------------------

class SafetyGate:
    """Thin, auditable safety gate that enforces the two hard cut-off
    switches *before* any per-action-type policy lookup.

    When requires_send_actions / requires_send_commands are provided,
    they are checked against the global flags.  If not provided, both
    default to True (i.e. the gate is always required).
    """

    @staticmethod
    def check(
        *,
        send_actions: bool,
        send_commands: bool,
        requires_send_actions: bool = True,
        requires_send_commands: bool = True,
    ) -> tuple[bool, str]:
        if requires_send_actions and not send_actions:
            return False, "dry_run_only"
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
    requires_send_actions: bool = True
    requires_send_commands: bool = True
    continuous: bool = False
    once_respected: bool = True


ACTION_DISPATCH_POLICY: dict[str, DispatchRule] = {
    "local_position": DispatchRule(
        allowed_actions={"goto_waypoint", "survey_area", "multi_view_localize", "recon_scan", "recon_inspect_target", "drop_sequence", "recon_sequence"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "global_goto": DispatchRule(
        allowed_actions={"goto_waypoint", "multi_view_localize", "gps_multi_view_localize", "gps_drop_sequence", "gps_recon_sequence"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "flight_command": DispatchRule(
        allowed_actions={"align_descend", "recon_inspect_target", "payload_release", "recon_descend_observe", "drop_sequence", "recon_sequence", "gps_drop_sequence", "gps_recon_sequence", "visual_land"},
        requires_send_actions=True,
        requires_send_commands=True,
        continuous=True,
        once_respected=False,
    ),
    "body_velocity": DispatchRule(
        allowed_actions={"align_descend", "recon_inspect_target"},
        requires_send_actions=True,
        requires_send_commands=True,
        continuous=True,
        once_respected=False,
    ),
    "set_servo": DispatchRule(
        allowed_actions={"payload_release", "drop_sequence", "gps_drop_sequence"},
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
    "condition_yaw": DispatchRule(
        allowed_actions={"yaw_align", "gps_multi_view_localize"},
        requires_send_actions=True,
        requires_send_commands=True,
    ),
    "yolo_lock_target": DispatchRule(
        allowed_actions={"target_lock", "recon_inspect_target", "drop_sequence", "recon_sequence", "gps_target_lock", "gps_drop_sequence", "gps_recon_sequence", "visual_land"},
        requires_send_actions=True,
        requires_send_commands=False,
    ),
    "clear_continuous_commands": DispatchRule(
        allowed_actions={"drop_sequence", "recon_sequence", "recon_descend_observe", "gps_drop_sequence", "gps_recon_sequence", "visual_land"},
        requires_send_actions=True,
        requires_send_commands=True,
        once_respected=False,
    ),
}
