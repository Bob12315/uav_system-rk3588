from __future__ import annotations

import threading
import uuid

from contracts.platform.common import (
    ActionInstanceId,
    AuthorizationGeneration,
    CancellationGeneration,
    ExecutionFenceQueryPort,
    ExecutionFenceSnapshot,
    LeaseGeneration,
    LeaseId,
    LinkSessionId,
    ResourceVersion,
    RunExecutionGeneration,
    RunId,
    SendGeneration,
    SourceId,
)


class CoreExecutionFenceAuthority(ExecutionFenceQueryPort):
    def __init__(self, source: SourceId, link_session_id: LinkSessionId, *, send_enabled: bool = False) -> None:
        if source not in {"real", "sitl"}:
            raise ValueError("production execution source must be real or sitl")
        if not link_session_id:
            raise ValueError("link session identity is required")
        self._lock = threading.Lock()
        self._generation_id = uuid.uuid4().hex
        self._send_enabled = bool(send_enabled)
        # Counters are authority-lifetime monotonic.  They must not be derived
        # from the nullable active projection because revoke clears that
        # projection and would otherwise recycle generation 1 for every step.
        self._run_execution_generation = 0
        self._authorization_generation = 0
        self._lease_generation = 0
        self._send_generation = 0
        self._cancellation_generation = 0
        self._snapshot = ExecutionFenceSnapshot(
            ResourceVersion(self._generation_id, 0), source, link_session_id,
            None, None, None, None, None, None,
            SendGeneration(self._send_generation),
            CancellationGeneration(self._cancellation_generation), 0,
        )

    def snapshot(self) -> ExecutionFenceSnapshot:
        with self._lock:
            return self._snapshot

    def set_send(self, enabled: bool, now_ns: int, *, force_generation: bool = False) -> ExecutionFenceSnapshot:
        with self._lock:
            if enabled == self._send_enabled and not force_generation:
                return self._snapshot
            self._send_enabled = enabled
            self._send_generation += 1
            current = self._snapshot
            self._snapshot = ExecutionFenceSnapshot(
                current.resource_version.next(), current.source, current.link_session_id,
                current.run_id, current.run_execution_generation, current.authorization_generation,
                current.action_instance_id, current.execution_lease_id, current.lease_generation,
                SendGeneration(self._send_generation), current.cancellation_generation, now_ns,
            )
            return self._snapshot

    def activate(
        self,
        run_id: RunId,
        action_instance_id: ActionInstanceId,
        lease_id: LeaseId,
        now_ns: int,
    ) -> ExecutionFenceSnapshot:
        with self._lock:
            current = self._snapshot
            self._run_execution_generation += 1
            self._authorization_generation += 1
            self._lease_generation += 1
            self._snapshot = ExecutionFenceSnapshot(
                current.resource_version.next(), current.source, current.link_session_id,
                run_id, RunExecutionGeneration(self._run_execution_generation),
                AuthorizationGeneration(self._authorization_generation),
                action_instance_id, lease_id, LeaseGeneration(self._lease_generation),
                current.send_generation, current.cancellation_generation, now_ns,
            )
            return self._snapshot

    def revoke(self, now_ns: int) -> tuple[ExecutionFenceSnapshot, ExecutionFenceSnapshot]:
        with self._lock:
            target = self._snapshot
            self._cancellation_generation += 1
            self._snapshot = ExecutionFenceSnapshot(
                target.resource_version.next(), target.source, target.link_session_id,
                None, None, None, None, None, None,
                target.send_generation,
                CancellationGeneration(self._cancellation_generation),
                now_ns,
            )
            return target, self._snapshot

    def switch_session(self, source: SourceId, session: LinkSessionId, now_ns: int) -> ExecutionFenceSnapshot:
        with self._lock:
            current = self._snapshot
            self._send_enabled = False
            self._send_generation += 1
            self._cancellation_generation += 1
            self._snapshot = ExecutionFenceSnapshot(
                current.resource_version.next(), source, session,
                None, None, None, None, None, None,
                SendGeneration(self._send_generation),
                CancellationGeneration(self._cancellation_generation), now_ns,
            )
            return self._snapshot
