from __future__ import annotations


def empty_dispatch() -> dict[str, list[dict[str, object]]]:
    """Return a fresh, empty dispatch result envelope.

    Extracted from ``ActionDispatcher`` as a pure static factory with
    zero side effects.
    """
    return {"sent": [], "skipped": [], "errors": []}
