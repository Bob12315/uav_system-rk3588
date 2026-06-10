from __future__ import annotations


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
