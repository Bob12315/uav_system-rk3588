from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Protocol

from contracts.core.common import InputSnapshotId
from contracts.core.input_state import (
    ComponentFreshness,
    FreshnessState,
    FusionComputePort,
    FusionSnapshot,
    FusionState,
    InputSnapshotRef,
    RuntimeInputPublisherPort,
    RuntimeInputSnapshot,
    SendGateSnapshot,
)
from contracts.core.time import CoreTime
from contracts.platform.common import ResourceVersion, SchemaVersion
from contracts.platform.perception import PerceptionFrameSnapshot
from contracts.platform.vehicle_state import VehicleStateSnapshot

from .state_store import RuntimeInputStore


@dataclass(frozen=True, slots=True)
class SnapshotCollectorPorts:
    vehicle_state: "SnapshotPort"
    perception: "SnapshotPort"
    field_reference: "SnapshotPort"
    send_gate: "SnapshotPort"
    fusion: FusionComputePort


class SnapshotPort(Protocol):
    def snapshot(self) -> object | None: ...


class SnapshotCollector(RuntimeInputPublisherPort):
    def __init__(self, ports: SnapshotCollectorPorts, store: RuntimeInputStore) -> None:
        self._ports = ports
        self._store = store
        self._generation_id = uuid.uuid4().hex
        self._revision = 0

    @staticmethod
    def _read(port: SnapshotPort) -> object | None:
        try:
            return port.snapshot()
        except Exception:
            return None

    def capture_and_publish(self, now: CoreTime) -> RuntimeInputSnapshot:
        vehicle = self._read(self._ports.vehicle_state)
        perception = self._read(self._ports.perception)
        field = self._read(self._ports.field_reference)
        send_gate = self._read(self._ports.send_gate)
        if not isinstance(send_gate, SendGateSnapshot):
            send_gate = SendGateSnapshot(False, 0, ResourceVersion("unavailable", 0))
        try:
            fusion = self._ports.fusion.compute(vehicle, perception, field)
        except Exception:
            fusion = FusionSnapshot(FusionState.INVALID, None, None, None, None, "fusion_failed")

        self._revision += 1
        ref = InputSnapshotRef(
            InputSnapshotId(uuid.uuid4().hex),
            ResourceVersion(self._generation_id, self._revision),
        )
        snapshot = RuntimeInputSnapshot(
            SchemaVersion(1, 0),
            ref,
            now,
            vehicle,
            self._freshness(vehicle, now),
            perception,
            self._freshness(perception, now),
            field,
            ComponentFreshness(FreshnessState.FRESH if field is not None else FreshnessState.UNAVAILABLE, None),
            fusion,
            send_gate,
        )
        self._store.publish(snapshot)
        return snapshot

    @staticmethod
    def _freshness(value: object | None, now: CoreTime) -> ComponentFreshness:
        if value is None:
            return ComponentFreshness(FreshnessState.UNAVAILABLE, None, "unavailable")
        if isinstance(value, VehicleStateSnapshot):
            age_ns = max(0, now.monotonic_ns - value.captured_at.monotonic_ns)
            if value.stale:
                return ComponentFreshness(FreshnessState.STALE, age_ns, "stale")
            return ComponentFreshness(FreshnessState.FRESH, age_ns)
        if isinstance(value, PerceptionFrameSnapshot):
            return ComponentFreshness(
                FreshnessState.FRESH,
                max(0, now.monotonic_ns - value.received_at_monotonic_ns),
            )
        return ComponentFreshness(FreshnessState.FRESH, None)
