from __future__ import annotations

from datetime import timedelta

from contracts.core.common import CoreCycleId, SchedulerSessionId, freeze_json
from contracts.core.cycle import CoreCycleSnapshot, SchedulerHealth
from contracts.core.execution import SafetyContext
from contracts.core.input_state import CycleCorrelation
from contracts.core.time import CoreTime
from contracts.platform.common import SchemaVersion

from .run_coordinator import RunCoordinator


class CoreCycleDriver:
    def __init__(self, collector, coordinator: RunCoordinator, dispatcher, cancel_port, cycle_publisher,
                 scheduler_session_id: SchedulerSessionId, cadence_ns: int,
                 effect_status_projection=None) -> None:
        self._collector = collector
        self._coordinator = coordinator
        self._dispatcher = dispatcher
        self._cancel_port = cancel_port
        self._cycle_publisher = cycle_publisher
        self._session_id = scheduler_session_id
        self._cadence_ns = cadence_ns
        self._effect_status_projection = effect_status_projection

    def run_one_cycle(self, now: CoreTime, scheduled_monotonic_ns: int, scheduler_tick_sequence: int) -> CoreCycleSnapshot:
        snapshot = self._collector.capture_and_publish(now)
        correlation = CycleCorrelation(
            self._session_id, CoreCycleId(f"{self._session_id}:{scheduler_tick_sequence}"),
            scheduler_tick_sequence, snapshot.ref,
        )
        if self._effect_status_projection is not None:
            observations = self._effect_status_projection.observe(
                self._coordinator.effect_status_queries(), now,
            )
            self._coordinator.apply_effect_observations(observations)
        plan = self._coordinator.advance(snapshot, correlation, now)
        cancel_receipts = tuple(self._cancel_port.cancel(request) for request in plan.cancellations)
        dispatch_receipts = []
        vehicle = snapshot.vehicle
        source = vehicle.source if vehicle is not None else plan.run_snapshot.target_source if plan.run_snapshot else "real"
        session = vehicle.link_session_id if vehicle is not None else "unavailable"
        for attempt in plan.dispatch_attempts:
            context = SafetyContext(
                snapshot.ref, snapshot.send_gate.enabled, source, session,
                "v1", now,
            )
            yolo_session = None if snapshot.perception is None else snapshot.perception.yolo_process_session_id
            dispatch_receipts.append(self._dispatcher.dispatch(
                attempt, context, yolo_process_session_id=yolo_session,
            ))
        run = self._coordinator.commit(plan, tuple(dispatch_receipts), cancel_receipts, now)
        finished = CoreTime(
            max(now.monotonic_ns, scheduled_monotonic_ns),
            now.utc + timedelta(microseconds=max(0, scheduled_monotonic_ns - now.monotonic_ns) / 1000),
            now.clock_domain_id,
        )
        cycle = CoreCycleSnapshot(
            SchemaVersion(1, 0), correlation, now, finished, snapshot,
            run,
            None if run is None else run.action,
            None if run is None else run.mission,
            freeze_json({"send_enabled": snapshot.send_gate.enabled}),
            SchedulerHealth(
                self._cadence_ns,
                max(0, finished.monotonic_ns - now.monotonic_ns),
                max(0, now.monotonic_ns - scheduled_monotonic_ns),
                0,
            ),
        )
        self._cycle_publisher.publish(cycle)
        return cycle
