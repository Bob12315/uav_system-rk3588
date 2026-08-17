from __future__ import annotations

from dataclasses import dataclass
import time

from contracts.platform.vehicle_commands import AckState


@dataclass(slots=True)
class AckSlot:
    command_id: str
    link_session_id: str
    mav_command: int
    target_system: int
    target_component: int
    discard: bool = False
    transmitted: bool = False
    early_result: tuple[int, int | None] | None = None
    ack_deadline_monotonic_ns: int = 0
    total_deadline_monotonic_ns: int = 0
    local_system: int = 0
    local_component: int = 0
    in_progress: bool = False


class AckRouter:
    """Strict COMMAND_ACK correlation scoped to one link session and sender."""

    def __init__(self, update_ack, *, monotonic_ns=time.monotonic_ns,
                 quarantine_ns: int = 250_000_000) -> None:
        self._update_ack = update_ack
        self._slots: dict[tuple[str, int, int, int], AckSlot] = {}
        self._monotonic_ns = monotonic_ns
        self._quarantine_ns = max(0, int(quarantine_ns))
        self._quarantine: dict[tuple[str, int, int, int], int] = {}

    def register(self, slot: AckSlot) -> None:
        key = (slot.link_session_id, slot.mav_command, slot.target_system, slot.target_component)
        if key in self._slots:
            raise RuntimeError("ack_slot_already_inflight")
        quarantine_until = self._quarantine.get(key, 0)
        if self._monotonic_ns() < quarantine_until:
            raise RuntimeError("ack_key_quarantined")
        self._quarantine.pop(key, None)
        self._slots[key] = slot

    def has_command(self, command_id: str) -> bool:
        return any(slot.command_id == command_id for slot in self._slots.values())

    def abort(self, command_id: str) -> None:
        for key, slot in list(self._slots.items()):
            if slot.command_id == command_id:
                self._slots.pop(key, None)
                self._quarantine[key] = self._monotonic_ns() + self._quarantine_ns

    def mark_transmitted(self, command_id: str) -> None:
        for slot in self._slots.values():
            if slot.command_id == command_id:
                slot.transmitted = True
                if slot.early_result is not None:
                    result, progress = slot.early_result
                    slot.early_result = None
                    self._apply(slot, result, progress)
                return

    def observe(self, *, link_session_id: str, mav_command: int, source_system: int,
                source_component: int, result: int, progress: int | None = None,
                target_system: int = 0, target_component: int = 0) -> bool:
        key = (link_session_id, mav_command, source_system, source_component)
        slot = self._slots.get(key)
        if slot is None:
            return False
        if target_system not in {0, slot.local_system} or target_component not in {0, slot.local_component}:
            return False
        if slot.discard:
            self._slots.pop(key, None)
            self._quarantine[key] = self._monotonic_ns() + self._quarantine_ns
            return True
        if not slot.transmitted:
            slot.early_result = (result, progress)
            return True
        self._apply(slot, result, progress)
        return True

    def lose_session(self, link_session_id: str) -> None:
        for key, slot in list(self._slots.items()):
            if slot.link_session_id == link_session_id:
                if not slot.discard:
                    self._update_ack(slot.command_id, AckState.SESSION_LOST, reason_code="ack_session_lost")
                self._slots.pop(key, None)

    def expire(self, now_monotonic_ns: int) -> None:
        for key, slot in list(self._slots.items()):
            deadline = slot.total_deadline_monotonic_ns if slot.in_progress else min(
                slot.ack_deadline_monotonic_ns, slot.total_deadline_monotonic_ns)
            if now_monotonic_ns < deadline:
                continue
            if not slot.discard:
                self._update_ack(slot.command_id, AckState.TIMED_OUT, reason_code="ack_timeout")
            self._slots.pop(key, None)
            self._quarantine[key] = now_monotonic_ns + self._quarantine_ns

    def _apply(self, slot: AckSlot, result: int, progress: int | None) -> None:
        if result == 5:
            slot.in_progress = True
            self._update_ack(slot.command_id, AckState.IN_PROGRESS, progress=progress, reason_code="ack_in_progress")
            return
        key = (slot.link_session_id, slot.mav_command, slot.target_system, slot.target_component)
        self._slots.pop(key, None)
        self._quarantine[key] = self._monotonic_ns() + self._quarantine_ns
        state = AckState.ACKED if result == 0 else AckState.NACKED
        self._update_ack(slot.command_id, state, progress=progress, reason_code="ack_accepted" if result == 0 else "ack_denied")
