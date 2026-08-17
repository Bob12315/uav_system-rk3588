from __future__ import annotations

from dataclasses import dataclass
import uuid

from contracts.core.common import SchedulerSessionId
from contracts.core.time import CoreClock
from contracts.platform.common import LinkSessionId, SourceId
from contracts.platform.ports import VehicleCommandPort, VisionCommandPort
from execution.dispatcher_v2 import EffectDispatcher
from execution.safety_policy import SafetyPolicy, SafetyPolicyConfig
from missions.core.production_catalog import create_production_catalog

from .cycle_driver import CoreCycleDriver
from .effect_delivery import EffectDeliveryTracker
from .effect_status_projection import PlatformEffectStatusProjection
from .execution_fence_authority import CoreExecutionFenceAuthority
from .run_coordinator import RunCoordinator
from .scheduler import CoreScheduler
from .snapshot_collector import SnapshotCollector, SnapshotCollectorPorts, SnapshotPort
from .state_store import CoreCycleStore, RuntimeInputStore
from .system_control_aggregate import SystemControlAggregate
from .system_send_state import SystemSendState


@dataclass(frozen=True, slots=True)
class CoreRuntime:
    fence: CoreExecutionFenceAuthority
    send_state: SystemSendState
    input_store: RuntimeInputStore
    cycle_store: CoreCycleStore
    coordinator: RunCoordinator
    driver: CoreCycleDriver
    scheduler: CoreScheduler
    system_control: SystemControlAggregate


def build_core_runtime(
    *,
    source: SourceId,
    link_session_id: LinkSessionId,
    vehicle_state: SnapshotPort,
    perception: SnapshotPort,
    field_reference: SnapshotPort,
    fusion,
    vehicle_commands: VehicleCommandPort,
    vision_commands: VisionCommandPort,
    clock: CoreClock,
    cadence_hz: float = 20.0,
    safety_config: SafetyPolicyConfig = SafetyPolicyConfig(),
) -> CoreRuntime:
    """Build one isolated stable-core owner graph with SEND hard-defaulted off."""
    fence = CoreExecutionFenceAuthority(source, link_session_id, send_enabled=False)
    send_state = SystemSendState(fence)
    input_store = RuntimeInputStore()
    cycle_store = CoreCycleStore()
    collector = SnapshotCollector(
        SnapshotCollectorPorts(vehicle_state, perception, field_reference, send_state, fusion),
        input_store,
    )
    coordinator = RunCoordinator(
        create_production_catalog(), fence, EffectDeliveryTracker(),
    )
    dispatcher = EffectDispatcher(
        vehicle_commands, vision_commands, SafetyPolicy(safety_config), fence,
    )
    status_projection = PlatformEffectStatusProjection(vehicle_commands, vision_commands)
    cadence_ns = int(1_000_000_000 / cadence_hz)
    driver = CoreCycleDriver(
        collector, coordinator, dispatcher, vehicle_commands, cycle_store,
        SchedulerSessionId(uuid.uuid4().hex), cadence_ns,
        effect_status_projection=status_projection,
    )
    scheduler = CoreScheduler(clock, driver, cadence_hz=cadence_hz)
    now = clock.now()
    system_control = SystemControlAggregate(send_state.snapshot(), fence.snapshot(), now)
    return CoreRuntime(
        fence, send_state, input_store, cycle_store, coordinator, driver, scheduler,
        system_control,
    )
