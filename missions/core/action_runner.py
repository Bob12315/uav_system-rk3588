from __future__ import annotations

from dataclasses import dataclass

from contracts.core.action import (
    ActionOutputEnvelope,
    ActionRegistration,
    ActionModule,
    ActionSnapshot,
    ActionState,
    ActionStepResult,
    ActionStepState,
    ActionTickContext,
    EffectEmission,
)
from contracts.core.common import freeze_json
from contracts.platform.common import ActionInstanceId


@dataclass(slots=True)
class _ActiveAction:
    registration: ActionRegistration
    module: ActionModule | None
    snapshot: ActionSnapshot


class ActionRunner:
    """One-instance lifecycle owner.  It never dispatches effects or performs I/O."""

    def __init__(self) -> None:
        self._active: _ActiveAction | None = None

    @property
    def snapshot(self) -> ActionSnapshot | None:
        return None if self._active is None else self._active.snapshot

    def start(
        self,
        instance_id: ActionInstanceId,
        registration: ActionRegistration,
        encoded_parameters,
        context: ActionTickContext,
    ) -> tuple[ActionSnapshot, tuple[EffectEmission, ...]]:
        if self._active is not None and self._active.snapshot.state in {ActionState.STARTING, ActionState.RUNNING}:
            raise RuntimeError("an Action is already active")
        decoded = registration.params_codec.decode(encoded_parameters)
        if not decoded.accepted:
            snapshot = ActionSnapshot(
                instance_id, registration.definition.contract_ref, ActionState.FAILED,
                context.snapshot.ref, 0, decoded.reason_code or "invalid_parameters",
            )
            self._active = _ActiveAction(registration, None, snapshot)
            return snapshot, ()
        try:
            module = registration.factory()
            result = module.start(decoded.value, context)
        except Exception:
            snapshot = ActionSnapshot(
                instance_id, registration.definition.contract_ref, ActionState.FAILED,
                context.snapshot.ref, 0, "action_start_failed",
            )
            self._active = _ActiveAction(registration, None, snapshot)
            return snapshot, ()
        snapshot, effects = self._apply_result(instance_id, registration, result, context, 1)
        self._active = _ActiveAction(registration, module, snapshot)
        return snapshot, effects

    def step(self, context: ActionTickContext) -> tuple[ActionSnapshot, tuple[EffectEmission, ...]]:
        active = self._active
        if active is None or active.snapshot.state is not ActionState.RUNNING:
            raise RuntimeError("no running Action")
        if active.module is None:
            raise RuntimeError("running Action has no module")
        try:
            result = active.module.step(context)
        except Exception:
            result = ActionStepResult(ActionStepState.FAILED, reason_code="action_step_failed")
        snapshot, effects = self._apply_result(
            active.snapshot.instance_id,
            active.registration,
            result,
            context,
            active.snapshot.step_count + 1,
        )
        active.snapshot = snapshot
        return snapshot, effects

    def stop(self, context: ActionTickContext, reason_code: str = "stopped") -> ActionSnapshot | None:
        active = self._active
        if active is None:
            return None
        if active.snapshot.state in {ActionState.RUNNING, ActionState.STARTING}:
            if active.module is None:
                raise RuntimeError("running Action has no module")
            try:
                active.module.stop(context)
            except Exception:
                reason_code = "action_stop_failed"
            active.snapshot = ActionSnapshot(
                active.snapshot.instance_id,
                active.snapshot.contract_ref,
                ActionState.STOPPED,
                context.snapshot.ref,
                active.snapshot.step_count,
                reason_code,
            )
        return active.snapshot

    def clear_terminal(self) -> None:
        if self._active is not None and self._active.snapshot.state in {
            ActionState.SUCCEEDED, ActionState.FAILED, ActionState.STOPPED,
        }:
            self._active = None

    @staticmethod
    def _apply_result(
        instance_id: ActionInstanceId,
        registration: ActionRegistration,
        result: object,
        context: ActionTickContext,
        step_count: int,
    ) -> tuple[ActionSnapshot, tuple[EffectEmission, ...]]:
        if not isinstance(result, ActionStepResult):
            result = ActionStepResult(ActionStepState.FAILED, reason_code="invalid_action_result")
        allowed = registration.definition.allowed_effect_kinds
        if any(emission.effect.kind not in allowed for emission in result.effects):
            result = ActionStepResult(ActionStepState.FAILED, reason_code="effect_not_allowed")
        state = {
            ActionStepState.RUNNING: ActionState.RUNNING,
            ActionStepState.SUCCEEDED: ActionState.SUCCEEDED,
            ActionStepState.FAILED: ActionState.FAILED,
        }[result.state]
        output = None
        if state is ActionState.SUCCEEDED:
            encoded = registration.output_codec.encode(result.output)
            if not encoded.accepted or encoded.value is None:
                state = ActionState.FAILED
                reason = encoded.reason_code or "output_schema_invalid"
            else:
                output = ActionOutputEnvelope(
                    registration.definition.contract_ref,
                    registration.definition.output_schema,
                    freeze_json(encoded.value),
                )
                reason = result.reason_code
        else:
            reason = result.reason_code
        snapshot = ActionSnapshot(
            instance_id,
            registration.definition.contract_ref,
            state,
            context.snapshot.ref,
            step_count,
            reason,
            output,
        )
        return snapshot, result.effects if state is ActionState.RUNNING else ()
