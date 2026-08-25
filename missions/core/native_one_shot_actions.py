from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import math
from typing import Callable, Generic, TypeVar

from contracts.core.action import (
    ActionStepResult,
    ActionStepState,
    ActionTickContext,
    CodecResult,
    EffectAckFeedbackState,
    EffectAdmissionFeedbackState,
    EffectCompletionFeedbackState,
    EffectEmission,
    EffectTransportFeedbackState,
)
from contracts.core.common import FrozenJson, freeze_json, thaw_json
from contracts.core.effects import (
    Arm,
    ChangeSpeed,
    Effect,
    Land,
    SetFlightMode,
    Takeoff,
)


P = TypeVar("P")


class TypedObjectCodec(Generic[P]):
    def __init__(self, decoder: Callable[[dict[str, object]], P]) -> None:
        self._decoder = decoder

    def validate_encoded(self, value: FrozenJson) -> CodecResult[None]:
        result = self.decode(value)
        return CodecResult(None, result.reason_code)

    def decode(self, value: FrozenJson) -> CodecResult[P]:
        raw = thaw_json(value)
        if not isinstance(raw, dict):
            return CodecResult(None, "parameters_must_be_object")
        try:
            return CodecResult(self._decoder(raw))
        except (KeyError, TypeError, ValueError):
            return CodecResult(None, "invalid_parameters")

    def encode(self, value: P) -> CodecResult[FrozenJson]:
        try:
            raw = asdict(value) if is_dataclass(value) else value
            return CodecResult(freeze_json(raw))
        except (TypeError, ValueError):
            return CodecResult(None, "output_schema_invalid")


@dataclass(frozen=True, slots=True)
class EmptyParams:
    pass


@dataclass(frozen=True, slots=True)
class TakeoffParams:
    mode: str
    altitude_m: float
    require_armed: bool


@dataclass(frozen=True, slots=True)
class ChangeSpeedParams:
    speed_mps: float


@dataclass(frozen=True, slots=True)
class OneShotOutput:
    effects_completed: int


def empty_params_codec() -> TypedObjectCodec[EmptyParams]:
    def decode(raw: dict[str, object]) -> EmptyParams:
        if raw:
            raise ValueError("unexpected parameters")
        return EmptyParams()
    return TypedObjectCodec(decode)


def takeoff_params_codec() -> TypedObjectCodec[TakeoffParams]:
    def decode(raw: dict[str, object]) -> TakeoffParams:
        allowed = {"mode", "altitude_m", "require_armed"}
        if set(raw) - allowed:
            raise ValueError("unknown takeoff parameter")
        altitude = float(raw.get("altitude_m", 5.0))
        if not math.isfinite(altitude) or altitude <= 0:
            raise ValueError("invalid altitude")
        mode = str(raw.get("mode", "GUIDED")).strip().upper()
        if not mode:
            raise ValueError("empty mode")
        return TakeoffParams(mode, altitude, bool(raw.get("require_armed", True)))
    return TypedObjectCodec(decode)


def speed_params_codec() -> TypedObjectCodec[ChangeSpeedParams]:
    def decode(raw: dict[str, object]) -> ChangeSpeedParams:
        if set(raw) - {"speed_mps"}:
            raise ValueError("unknown speed parameter")
        speed = float(raw["speed_mps"])
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("invalid speed")
        return ChangeSpeedParams(speed)
    return TypedObjectCodec(decode)


class NativeSequentialEffectAction:
    """Feedback-driven one-shot Action; submission alone never completes it."""

    def __init__(self, builder: Callable[[object], tuple[Effect, ...]]) -> None:
        self._builder = builder
        self._effects: tuple[Effect, ...] = ()
        self._index = 0
        self._emitted = False

    def start(self, params: object, context: ActionTickContext) -> ActionStepResult:
        self._effects = self._builder(params)
        self._index = 0
        self._emitted = False
        if not self._effects:
            return ActionStepResult(ActionStepState.SUCCEEDED, output=OneShotOutput(0))
        return ActionStepResult(ActionStepState.RUNNING)

    def step(self, context: ActionTickContext) -> ActionStepResult:
        local_token = f"one-shot:{self._index}"
        if not self._emitted:
            self._emitted = True
            return ActionStepResult(
                ActionStepState.RUNNING,
                (EffectEmission(local_token, self._effects[self._index]),),
            )
        feedback = next((item for item in context.feedback if item.local_token == local_token), None)
        if feedback is None:
            return ActionStepResult(ActionStepState.RUNNING)
        lifecycle = feedback.lifecycle
        if (lifecycle.admission in {EffectAdmissionFeedbackState.REJECTED,
                                    EffectAdmissionFeedbackState.FAILED_TO_SUBMIT}
                or lifecycle.transport is EffectTransportFeedbackState.FAILED
                or lifecycle.ack is EffectAckFeedbackState.REJECTED
                or lifecycle.completion is EffectCompletionFeedbackState.FAILED):
            return ActionStepResult(ActionStepState.FAILED, reason_code=feedback.reason_code or "effect_failed")
        completed = (
            lifecycle.completion is EffectCompletionFeedbackState.COMPLETED
            or lifecycle.ack is EffectAckFeedbackState.ACKNOWLEDGED
            or (lifecycle.transport is EffectTransportFeedbackState.TRANSMITTED
                and lifecycle.ack is EffectAckFeedbackState.NOT_EXPECTED)
        )
        if not completed:
            return ActionStepResult(ActionStepState.RUNNING)
        self._index += 1
        self._emitted = False
        if self._index == len(self._effects):
            return ActionStepResult(
                ActionStepState.SUCCEEDED,
                output=OneShotOutput(len(self._effects)),
                reason_code="effects_completed",
            )
        return ActionStepResult(ActionStepState.RUNNING)

    def stop(self, context: ActionTickContext) -> None:
        self._effects = ()


def takeoff_factory() -> NativeSequentialEffectAction:
    return NativeSequentialEffectAction(
        lambda value: (
            SetFlightMode(value.mode),
            *((Arm(),) if value.require_armed else ()),
            Takeoff(value.altitude_m),
        ) if isinstance(value, TakeoffParams) else (),
    )


def land_factory() -> NativeSequentialEffectAction:
    return NativeSequentialEffectAction(lambda value: (Land(),) if isinstance(value, EmptyParams) else ())


def speed_factory() -> NativeSequentialEffectAction:
    return NativeSequentialEffectAction(
        lambda value: (ChangeSpeed(value.speed_mps),)
        if isinstance(value, ChangeSpeedParams) else (),
    )


def output_codec() -> TypedObjectCodec[OneShotOutput]:
    return TypedObjectCodec(lambda raw: OneShotOutput(int(raw["effects_completed"])))
