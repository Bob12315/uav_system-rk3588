from __future__ import annotations


class SafetyGate:
    """Thin, auditable safety gate that enforces the two hard cut-off
    switches *before* any per-action-type policy lookup.

    This gate only cares about the global send_actions / send_commands
    flags.  Per-action-type allow-listing lives in the dispatch policy.
    """

    @staticmethod
    def check(*, send_actions: bool, send_commands: bool) -> tuple[bool, str]:
        if not send_actions:
            return False, "dry_run_only"
        if not send_commands:
            return False, "send_commands_disabled"
        return True, "ok"
