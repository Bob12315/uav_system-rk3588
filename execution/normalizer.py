from __future__ import annotations


def get_action_params(action: dict[str, object]) -> dict[str, object]:
    """Extract and validate the ``params`` dict from an action envelope.

    Raises ``ValueError("missing_params")`` when *params* is missing
    or not a dict.
    """
    params = action.get("params")
    if not isinstance(params, dict):
        raise ValueError("missing_params")
    return params


def optional_float(value: object) -> float | None:
    """Safe float conversion that returns ``None`` on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_log_float(value: object) -> str:
    """Format a numeric value for logging purposes.

    Returns the value formatted to three decimal places, or "None"
    on conversion failure.
    """
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "None"
