from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from contracts.platform.common import ResourceVersion, RunId, RunResourceGenerationId, SourceId

from .action import ActionContractRef, ActionSnapshot
from .common import FrozenJson, IdempotencyKey, RequestId
from .input_state import InputSnapshotRef
from .mission import MissionDefinition, MissionSnapshot, StepExecutionToken
from .run_io import ResultProjectionPolicy, RunRecordingPolicy
from .time import CoreTime


@dataclass(frozen=True, slots=True)
class RunToken:
    run_id: RunId
    generation_id: RunResourceGenerationId


@dataclass(frozen=True, slots=True)
class ActionRunTarget:
    action_contract_ref: ActionContractRef
    encoded_parameters: FrozenJson


@dataclass(frozen=True, slots=True)
class MissionRunTarget:
    definition: MissionDefinition
    inputs: FrozenJson


RunTarget: TypeAlias = ActionRunTarget | MissionRunTarget


@dataclass(frozen=True, slots=True)
class RunAuthorizationRequest:
    actor_id: str
    request_context_id: str
    operator_confirmed: bool


@dataclass(frozen=True, slots=True)
class StartRunCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    target: RunTarget
    target_source: SourceId
    authorization_request: RunAuthorizationRequest
    recording_policy: RunRecordingPolicy
    result_projection_policy: ResultProjectionPolicy
    requested_at: CoreTime


@dataclass(frozen=True, slots=True)
class StopRunCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    run_token: RunToken
    reason_code: str


@dataclass(frozen=True, slots=True)
class SkipStepCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    expected_step: StepExecutionToken


@dataclass(frozen=True, slots=True)
class ClearTerminalCommand:
    request_id: RequestId
    idempotency_key: IdempotencyKey
    run_token: RunToken


class RunCommandDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class RunCommandReceipt:
    request_id: RequestId
    disposition: RunCommandDisposition
    replayed: bool
    run_id: RunId | None
    resource_version: ResourceVersion | None
    reason_code: str | None


class RunState(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    STARTING = "starting"
    RUNNING = "running"
    FINALIZING = "finalizing"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED}


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    token: RunToken
    state: RunState
    target_source: SourceId
    version: ResourceVersion
    created_at: CoreTime
    started_at: CoreTime | None
    updated_at: CoreTime
    finished_at: CoreTime | None
    action: ActionSnapshot | None
    mission: MissionSnapshot | None
    reason_code: str | None
    last_consumed_input_ref: InputSnapshotRef | None = None
    last_advanced_tick_sequence: int | None = None
