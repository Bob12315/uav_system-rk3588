from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from contracts.platform.common import (
    ActionInstanceId,
    AuthorizationGeneration,
    LeaseGeneration,
    LeaseId,
    LinkSessionId,
    RunExecutionGeneration,
    RunId,
    SendGeneration,
    SourceId,
)

from .action import ActionContractRef
from .common import DispatchReceiptId, EffectId, FrozenJson, IdempotencyKey
from .effects import Effect, EffectKind
from .input_state import InputSnapshotRef
from .time import CoreTime


@dataclass(frozen=True, slots=True)
class RunAuthorizationGrant:
    actor_id: str
    run_id: RunId
    source: SourceId
    generation: AuthorizationGeneration
    allowed_effect_kinds: frozenset[EffectKind]
    expires_monotonic_ns: int
    policy_revision: str


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    lease_id: LeaseId
    generation: LeaseGeneration
    run_id: RunId
    run_execution_generation: RunExecutionGeneration
    action_instance_id: ActionInstanceId
    action_contract_ref: ActionContractRef
    source: SourceId
    link_session_id: LinkSessionId
    authorization_generation: AuthorizationGeneration
    allowed_effect_kinds: frozenset[EffectKind]
    expires_monotonic_ns: int


@dataclass(frozen=True, slots=True)
class EffectEnvelope:
    effect_id: EffectId
    idempotency_key: IdempotencyKey
    run_id: RunId
    run_execution_generation: RunExecutionGeneration
    action_instance_id: ActionInstanceId
    emission_sequence: int
    local_token: str
    effect: Effect
    emitted_input_ref: InputSnapshotRef


@dataclass(frozen=True, slots=True)
class EffectDispatchAttempt:
    envelope: EffectEnvelope
    attempt_number: int
    evaluation_input_ref: InputSnapshotRef
    lease: ExecutionLease
    grant: RunAuthorizationGrant
    send_generation: SendGeneration
    now: CoreTime


class SafetyDisposition(str, Enum):
    ALLOW = "allow"
    MODIFY = "modify"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class SafetyContext:
    input_ref: InputSnapshotRef
    send_enabled: bool
    source: SourceId
    link_session_id: LinkSessionId
    policy_revision: str
    now: CoreTime


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    disposition: SafetyDisposition
    original: Effect
    effective: Effect | None
    reason_code: str | None
    diagnostics: FrozenJson


class DispatchState(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED_TO_SUBMIT = "failed_to_submit"


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    receipt_id: DispatchReceiptId
    effect_id: EffectId
    state: DispatchState
    replayed: bool
    platform_command_id: str | None
    reason_code: str | None
