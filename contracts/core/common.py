from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
import math
from typing import NewType, TypeAlias

from contracts.platform.common import (
    ActionInstanceId,
    AuthorizationGeneration,
    CancellationGeneration,
    CancellationId,
    CommandId,
    LeaseGeneration,
    LeaseId,
    LinkSessionId,
    ResourceVersion,
    RunExecutionGeneration,
    RunId,
    RunResourceGenerationId,
    SchemaVersion,
    SendGeneration,
    SubmissionReceiptId,
)

ActionDefinitionId = NewType("ActionDefinitionId", str)
ActionContractFingerprint = NewType("ActionContractFingerprint", str)
MissionId = NewType("MissionId", str)
MissionDefinitionId = NewType("MissionDefinitionId", str)
StepId = NewType("StepId", str)
EffectId = NewType("EffectId", str)
InputSnapshotId = NewType("InputSnapshotId", str)
CoreCycleId = NewType("CoreCycleId", str)
SchedulerSessionId = NewType("SchedulerSessionId", str)
PreparationId = NewType("PreparationId", str)
DispatchReceiptId = NewType("DispatchReceiptId", str)
OperationId = NewType("OperationId", str)
RequestId = NewType("RequestId", str)
IdempotencyKey = NewType("IdempotencyKey", str)

FrozenScalar: TypeAlias = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class FrozenObject(Mapping[str, object]):
    items_tuple: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        keys = tuple(key for key, _ in self.items_tuple)
        if any(not key for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("frozen object keys must be unique non-empty strings")
        if keys != tuple(sorted(keys)):
            raise ValueError("frozen object keys must be in canonical order")

    def __getitem__(self, key: str) -> object:
        for candidate, value in self.items_tuple:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.items_tuple)

    def __len__(self) -> int:
        return len(self.items_tuple)


FrozenJson: TypeAlias = FrozenScalar | tuple["FrozenJson", ...] | FrozenObject


def freeze_json(value: object) -> FrozenJson:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("FrozenJson rejects NaN and infinity")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("FrozenJson object keys must be strings")
        return FrozenObject(tuple(sorted((key, freeze_json(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported FrozenJson value: {type(value).__name__}")


def thaw_json(value: FrozenJson) -> object:
    if isinstance(value, FrozenObject):
        return {key: thaw_json(item) for key, item in value.items_tuple}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


class StableReason(str, Enum):
    ACCEPTED = "accepted"
    INVALID_STATE = "invalid_state"
    INVALID_PARAMETERS = "invalid_parameters"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SNAPSHOT_STALE = "snapshot_stale"
    SEND_DISABLED = "send_disabled"
    AUTHORIZATION_DENIED = "authorization_denied"
    LEASE_REVOKED = "lease_revoked"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


__all__ = [name for name in globals() if not name.startswith("_")]
