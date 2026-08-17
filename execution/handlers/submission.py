from __future__ import annotations


def submission_outcome(receipt: object, detail: dict[str, object]) -> dict[str, object]:
    state = getattr(receipt, "submission_state", None)
    if state is None:
        detail = dict(detail)
        detail["submission_state"] = "LEGACY_ACCEPTED_UNKNOWN"
        return {"status": "accepted", "detail": detail}
    value = getattr(state, "value", str(state))
    detail = dict(detail)
    detail["command_id"] = getattr(receipt, "command_id", None)
    detail["submission_state"] = value
    reason = str(getattr(receipt, "reason_code", "submission_rejected"))
    if value == "ACCEPTED":
        return {"status": "accepted", "detail": detail}
    return {"status": "skipped", "reason": reason, "detail": detail}
