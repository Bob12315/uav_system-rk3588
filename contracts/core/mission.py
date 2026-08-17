from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from contracts.platform.common import ActionInstanceId, ResourceVersion, SchemaVersion

from .action import ActionContractRef, ActionOutputEnvelope, ExitBarrier
from .common import FrozenJson, FrozenObject, MissionDefinitionId, MissionId, StepId
from .input_state import InputSnapshotRef


@dataclass(frozen=True, slots=True)
class LiteralExpr:
    value: FrozenJson


@dataclass(frozen=True, slots=True)
class BlackboardRefExpr:
    root_key: str
    path: tuple[str | int, ...] = ()

    def __post_init__(self) -> None:
        if not self.root_key:
            raise ValueError("blackboard root key is required")


ValueExpr: TypeAlias = LiteralExpr | BlackboardRefExpr


class FailureMode(str, Enum):
    FAIL = "fail"
    CONTINUE = "continue"
    RETRY = "retry"
    JUMP = "jump"


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    mode: FailureMode
    max_retries: int = 0
    jump_target: StepId | None = None
    retry_delay_ms: int = 0

    def __post_init__(self) -> None:
        if self.max_retries < 0 or self.retry_delay_ms < 0:
            raise ValueError("failure budgets must be non-negative")
        if self.mode is FailureMode.RETRY and self.max_retries < 1:
            raise ValueError("retry policy must be bounded")
        if self.mode is FailureMode.JUMP and self.jump_target is None:
            raise ValueError("jump policy requires a target")


@dataclass(frozen=True, slots=True)
class StepDefinition:
    step_id: StepId
    label: str | None
    action_contract_ref: ActionContractRef
    parameters: FrozenObject
    save_as: str | None
    failure_policy: FailurePolicy
    exit_barrier: ExitBarrier


@dataclass(frozen=True, slots=True)
class MissionDefinition:
    schema_version: SchemaVersion
    definition_id: MissionDefinitionId
    revision: str
    label: str
    steps: tuple[StepDefinition, ...]
    max_total_starts: int
    max_total_transitions: int
    max_transitions_per_cycle: int

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("mission requires at least one step")
        step_ids = tuple(step.step_id for step in self.steps)
        labels = tuple(step.label for step in self.steps if step.label is not None)
        if len(step_ids) != len(set(step_ids)) or len(labels) != len(set(labels)):
            raise ValueError("mission step IDs and labels must be unique")
        known = set(step_ids)
        if any(
            step.failure_policy.jump_target not in known
            for step in self.steps
            if step.failure_policy.jump_target is not None
        ):
            raise ValueError("mission contains an unknown jump target")
        if min(self.max_total_starts, self.max_total_transitions, self.max_transitions_per_cycle) < 1:
            raise ValueError("mission budgets must be positive and bounded")


class MissionState(str, Enum):
    IDLE = "idle"
    STARTING_CHILD = "starting_child"
    RUNNING_CHILD = "running_child"
    FINALIZING_CHILD = "finalizing_child"
    WAITING_BARRIER = "waiting_barrier"
    WAITING_RETRY = "waiting_retry"
    SAVING_OUTPUT = "saving_output"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class StepExecutionToken:
    mission_id: MissionId
    step_id: StepId
    generation: int


@dataclass(frozen=True, slots=True)
class PendingMissionTransition:
    step_token: StepExecutionToken
    child_instance_id: ActionInstanceId
    succeeded: bool
    output: ActionOutputEnvelope | None
    reason_code: str | None
    destination_step_id: StepId | None
    barrier: ExitBarrier


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    mission_id: MissionId
    definition_id: MissionDefinitionId
    state: MissionState
    current_step_token: StepExecutionToken | None
    child_instance_id: ActionInstanceId | None
    last_consumed_input_ref: InputSnapshotRef | None
    version: ResourceVersion
    total_starts: int
    total_transitions: int
    pending_transition: PendingMissionTransition | None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class MissionReduceContext:
    cycle_id: str
    input_ref: InputSnapshotRef


@dataclass(frozen=True, slots=True)
class StartChildAction:
    step: StepDefinition
    step_token: StepExecutionToken
    resolved_parameters: FrozenJson


@dataclass(frozen=True, slots=True)
class StopChildAction:
    child_instance_id: ActionInstanceId
    reason_code: str


@dataclass(frozen=True, slots=True)
class RequestExitBarrier:
    step_token: StepExecutionToken
    barrier: ExitBarrier


@dataclass(frozen=True, slots=True)
class ScheduleRetryDelay:
    step_token: StepExecutionToken
    delay_ms: int


@dataclass(frozen=True, slots=True)
class CompleteMission:
    succeeded: bool
    reason_code: str


MissionIntent: TypeAlias = StartChildAction | StopChildAction | RequestExitBarrier | ScheduleRetryDelay | CompleteMission
