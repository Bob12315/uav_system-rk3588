from __future__ import annotations

from dataclasses import replace
import threading
import uuid

from contracts.core.input_state import SendGateSnapshot
from contracts.core.system import (
    BeginMaintenanceCommand,
    CoreSystemSnapshot,
    EndMaintenanceCommand,
    ReconnectSourceCommand,
    SetSendGateCommand,
    ShutdownCommand,
    SwitchSourceCommand,
    SystemCommandDisposition,
    SystemControlCommand,
    SystemControlReceipt,
    SystemOperationSnapshot,
    SystemOperationState,
)
from contracts.platform.common import ExecutionFenceSnapshot, ResourceVersion, SendGeneration
from contracts.core.common import OperationId
from contracts.core.time import CoreTime


class SystemControlAggregate:
    """Pure system-command state owner.  External work is represented as operations."""

    def __init__(self, send_gate: SendGateSnapshot, fence: ExecutionFenceSnapshot, now: CoreTime) -> None:
        self._lock = threading.Lock()
        self._queue: list[tuple[SystemControlCommand, OperationId | None]] = []
        self._idempotency: dict[object, tuple[SystemControlCommand, SystemControlReceipt]] = {}
        self._operations: dict[OperationId, SystemOperationSnapshot] = {}
        self._generation_id = uuid.uuid4().hex
        self._snapshot = CoreSystemSnapshot(
            ResourceVersion(self._generation_id, 0), send_gate, fence,
            False, False, None, None,
        )

    def request(self, command: SystemControlCommand) -> SystemControlReceipt:
        with self._lock:
            previous = self._idempotency.get(command.idempotency_key)
            if previous is not None:
                payload, receipt = previous
                if payload != command:
                    return SystemControlReceipt(command.request_id, SystemCommandDisposition.CONFLICT,
                                                False, receipt.resource_version, receipt.operation_id,
                                                "idempotency_key_reused")
                return replace(receipt, replayed=True)
            if isinstance(command, SetSendGateCommand) and command.expected_version != self._snapshot.send_gate.version:
                receipt = SystemControlReceipt(command.request_id, SystemCommandDisposition.CONFLICT,
                                               False, self._snapshot.version, None,
                                               "send_gate_version_mismatch")
                self._idempotency[command.idempotency_key] = (command, receipt)
                return receipt
            if isinstance(command, SwitchSourceCommand) and command.expected_version != self._snapshot.version:
                receipt = SystemControlReceipt(command.request_id, SystemCommandDisposition.CONFLICT,
                                               False, self._snapshot.version, None,
                                               "system_version_mismatch")
                self._idempotency[command.idempotency_key] = (command, receipt)
                return receipt
            if isinstance(command, EndMaintenanceCommand):
                active = self._snapshot.active_operation_id
                if active != command.operation_id:
                    receipt = SystemControlReceipt(command.request_id, SystemCommandDisposition.CONFLICT,
                                                   False, self._snapshot.version, active,
                                                   "maintenance_operation_mismatch")
                    self._idempotency[command.idempotency_key] = (command, receipt)
                    return receipt
                self._queue.append((command, active))
                receipt = SystemControlReceipt(command.request_id, SystemCommandDisposition.ACCEPTED,
                                               False, self._snapshot.version, active, None)
                self._idempotency[command.idempotency_key] = (command, receipt)
                return receipt
            exclusive = not isinstance(command, SetSendGateCommand)
            if exclusive and self._snapshot.active_operation_id is not None:
                receipt = SystemControlReceipt(command.request_id, SystemCommandDisposition.CONFLICT,
                                               False, self._snapshot.version,
                                               self._snapshot.active_operation_id, "exclusive_operation_active")
            elif isinstance(command, SetSendGateCommand) and command.enabled and self._snapshot.quiescing:
                receipt = SystemControlReceipt(command.request_id, SystemCommandDisposition.REJECTED,
                                               False, self._snapshot.version, None, "system_quiescing")
            else:
                operation_id = OperationId(uuid.uuid4().hex) if exclusive else None
                if operation_id is not None:
                    operation = SystemOperationSnapshot(
                        operation_id, command.request_id, type(command).__name__,
                        SystemOperationState.PENDING, ResourceVersion(str(operation_id), 0),
                        command.requested_at, command.requested_at, None,
                    )
                    self._operations[operation_id] = operation
                    self._snapshot = replace(
                        self._snapshot,
                        version=self._snapshot.version.next(),
                        active_operation_id=operation_id,
                        latest_operation=operation,
                    )
                self._queue.append((command, operation_id))
                receipt = SystemControlReceipt(command.request_id, SystemCommandDisposition.ACCEPTED,
                                               False, self._snapshot.version, operation_id, None)
            self._idempotency[command.idempotency_key] = (command, receipt)
            return receipt

    def apply_pre_capture(self, now: CoreTime, fence: ExecutionFenceSnapshot) -> CoreSystemSnapshot:
        with self._lock:
            queue, self._queue = self._queue, []
            for command, reserved_operation_id in queue:
                if isinstance(command, SetSendGateCommand):
                    send = SendGateSnapshot(
                        command.enabled,
                        SendGeneration(int(self._snapshot.send_gate.generation) + 1),
                        self._snapshot.send_gate.version.next(),
                    )
                    self._snapshot = replace(
                        self._snapshot, send_gate=send, execution_fence=fence,
                        version=self._snapshot.version.next(),
                    )
                    continue
                if isinstance(command, EndMaintenanceCommand):
                    operation_id = command.operation_id
                    current = self._operations[operation_id]
                    terminal = replace(
                        current,
                        state=SystemOperationState.APPLIED if command.succeeded else SystemOperationState.FAILED,
                        version=current.version.next(), updated_at=now, finished_at=now,
                        reason_code=None if command.succeeded else "maintenance_failed",
                    )
                    self._operations[operation_id] = terminal
                    self._snapshot = replace(
                        self._snapshot, version=self._snapshot.version.next(), quiescing=False,
                        active_operation_id=None, latest_operation=terminal,
                    )
                    continue
                if reserved_operation_id is None:
                    raise RuntimeError("exclusive system command lost its reservation")
                operation_id = reserved_operation_id
                current = self._operations[operation_id]
                operation = replace(
                    current, state=SystemOperationState.QUIESCING,
                    version=current.version.next(), updated_at=now,
                )
                self._operations[operation_id] = operation
                forced_off = SendGateSnapshot(
                    False,
                    SendGeneration(int(self._snapshot.send_gate.generation) + 1),
                    self._snapshot.send_gate.version.next(),
                )
                self._snapshot = replace(
                    self._snapshot,
                    version=self._snapshot.version.next(),
                    send_gate=forced_off,
                    execution_fence=fence,
                    quiescing=True,
                    shutdown_requested=isinstance(command, ShutdownCommand),
                    active_operation_id=operation_id,
                    latest_operation=operation,
                )
            return self._snapshot

    def mark_ready_for_external(self, operation_id: OperationId, now: CoreTime) -> SystemOperationSnapshot:
        return self._transition(operation_id, SystemOperationState.READY_FOR_EXTERNAL, now)

    def mark_submitted(self, operation_id: OperationId, now: CoreTime) -> SystemOperationSnapshot:
        return self._transition(operation_id, SystemOperationState.SUBMITTED, now)

    def complete(self, operation_id: OperationId, now: CoreTime, *, succeeded: bool,
                 reason_code: str | None = None) -> SystemOperationSnapshot:
        state = SystemOperationState.APPLIED if succeeded else SystemOperationState.FAILED
        operation = self._transition(operation_id, state, now, reason_code=reason_code, terminal=True)
        with self._lock:
            self._snapshot = replace(
                self._snapshot, version=self._snapshot.version.next(), quiescing=False,
                active_operation_id=None, latest_operation=operation,
            )
        return operation

    def current(self) -> CoreSystemSnapshot:
        with self._lock:
            return self._snapshot

    def operation(self, operation_id: OperationId) -> SystemOperationSnapshot | None:
        with self._lock:
            return self._operations.get(operation_id)

    def _transition(self, operation_id, state, now, *, reason_code=None, terminal=False):
        with self._lock:
            current = self._operations[operation_id]
            if current.state in {
                SystemOperationState.APPLIED, SystemOperationState.FAILED,
                SystemOperationState.TIMED_OUT, SystemOperationState.SUPERSEDED,
            }:
                return current
            updated = replace(
                current, state=state, version=current.version.next(), updated_at=now,
                finished_at=now if terminal else None, reason_code=reason_code,
            )
            self._operations[operation_id] = updated
            self._snapshot = replace(self._snapshot, version=self._snapshot.version.next(), latest_operation=updated)
            return updated
