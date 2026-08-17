from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, Protocol, TypeVar

from contracts.platform.common import ActionInstanceId, ResourceVersion, SchemaVersion

from .common import (
    ActionContractFingerprint,
    ActionDefinitionId,
    EffectId,
    FrozenJson,
)
from .effects import Effect, EffectKind
from .input_state import CycleCorrelation, InputSnapshotRef, RuntimeInputSnapshot
from .time import CoreTime


@dataclass(frozen=True, slots=True)
class SchemaRef:
    schema_id: str
    version: SchemaVersion


@dataclass(frozen=True, slots=True)
class ActionContractRef:
    definition_id: ActionDefinitionId
    revision: str
    fingerprint: ActionContractFingerprint


class ExitBarrier(str, Enum):
    NONE = "none"
    MOTION_STOPPED = "motion_stopped"


@dataclass(frozen=True, slots=True)
class EffectDispatchPolicy:
    ttl_ms: int
    priority: int
    max_pre_admission_attempts: int = 1
    continuous_refresh_ms: int | None = None

    def __post_init__(self) -> None:
        if self.ttl_ms <= 0 or not 0 <= self.priority <= 100:
            raise ValueError("invalid effect dispatch policy")
        if self.max_pre_admission_attempts < 1:
            raise ValueError("effect submit attempts must be bounded and positive")


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    contract_ref: ActionContractRef
    name: str
    label: str
    description: str
    params_schema: SchemaRef
    output_schema: SchemaRef
    allowed_effect_kinds: frozenset[EffectKind]
    required_inputs: frozenset[str]
    dispatch_policies: tuple[tuple[EffectKind, EffectDispatchPolicy], ...]
    minimum_exit_barrier: ExitBarrier = ExitBarrier.NONE
    protected_profile: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.label:
            raise ValueError("action definition name and label are required")
        policy_kinds = {kind for kind, _ in self.dispatch_policies}
        if not self.allowed_effect_kinds.issubset(policy_kinds):
            raise ValueError("every allowed effect requires a trusted dispatch policy")


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CodecResult(Generic[T]):
    value: T | None
    reason_code: str | None = None

    @property
    def accepted(self) -> bool:
        return self.reason_code is None


class ActionCodec(Protocol[T]):
    def validate_encoded(self, value: FrozenJson) -> CodecResult[None]: ...
    def decode(self, value: FrozenJson) -> CodecResult[T]: ...
    def encode(self, value: T) -> CodecResult[FrozenJson]: ...


class EffectAdmissionFeedbackState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED_TO_SUBMIT = "failed_to_submit"


class EffectTransportFeedbackState(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    TRANSMITTED = "transmitted"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class EffectAckFeedbackState(str, Enum):
    WAITING = "waiting"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    NOT_EXPECTED = "not_expected"
    UNKNOWN = "unknown"


class EffectCompletionFeedbackState(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_OBSERVED = "not_observed"


@dataclass(frozen=True, slots=True)
class EffectLifecycleFeedback:
    admission: EffectAdmissionFeedbackState
    transport: EffectTransportFeedbackState
    ack: EffectAckFeedbackState
    completion: EffectCompletionFeedbackState
    progress_percent: int | None
    status_version: ResourceVersion | None
    observed_at: CoreTime


@dataclass(frozen=True, slots=True)
class EffectFeedback:
    effect_id: EffectId
    local_token: str
    emission_sequence: int
    lifecycle: EffectLifecycleFeedback
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class ActionTickContext:
    correlation: CycleCorrelation
    now: CoreTime
    snapshot: RuntimeInputSnapshot
    feedback: tuple[EffectFeedback, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectEmission:
    local_token: str
    effect: Effect

    def __post_init__(self) -> None:
        if not self.local_token:
            raise ValueError("effect local token must not be empty")


class ActionStepState(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ActionStepResult:
    state: ActionStepState
    effects: tuple[EffectEmission, ...] = ()
    output: object | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.state is not ActionStepState.RUNNING and self.effects:
            raise ValueError("terminal Action result cannot emit effects")


class ActionModule(Protocol):
    def start(self, params: object, context: ActionTickContext) -> ActionStepResult: ...
    def step(self, context: ActionTickContext) -> ActionStepResult: ...
    def stop(self, context: ActionTickContext) -> None: ...


@dataclass(frozen=True, slots=True)
class ActionRegistration:
    definition: ActionDefinition
    factory: Callable[[], ActionModule]
    params_codec: ActionCodec[object]
    output_codec: ActionCodec[object]


@dataclass(frozen=True, slots=True)
class ActionOutputEnvelope:
    action_contract_ref: ActionContractRef
    output_schema: SchemaRef
    payload: FrozenJson


class ActionState(str, Enum):
    EMPTY = "empty"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class ActionSnapshot:
    instance_id: ActionInstanceId
    contract_ref: ActionContractRef
    state: ActionState
    last_consumed_input_ref: InputSnapshotRef
    step_count: int
    reason_code: str | None = None
    output: ActionOutputEnvelope | None = None
