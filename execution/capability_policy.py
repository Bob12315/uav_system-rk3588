from __future__ import annotations

from contracts.core.execution import EffectDispatchAttempt

from .effect_registry import EFFECT_REGISTRY


def authorize_effect(attempt: EffectDispatchAttempt) -> str | None:
    rule = EFFECT_REGISTRY[attempt.envelope.effect.kind]
    now_ns = attempt.now.monotonic_ns
    grant = attempt.grant
    lease = attempt.lease
    if grant.run_id != attempt.envelope.run_id or lease.run_id != attempt.envelope.run_id:
        return "run_mismatch"
    if lease.action_instance_id != attempt.envelope.action_instance_id:
        return "action_instance_mismatch"
    if lease.run_execution_generation != attempt.envelope.run_execution_generation:
        return "run_generation_stale"
    if lease.authorization_generation != grant.generation:
        return "authorization_generation_stale"
    if now_ns >= grant.expires_monotonic_ns or now_ns >= lease.expires_monotonic_ns:
        return "lease_expired"
    if attempt.envelope.effect.kind not in grant.allowed_effect_kinds:
        return "grant_capability_denied"
    if attempt.envelope.effect.kind not in lease.allowed_effect_kinds:
        return "lease_capability_denied"
    if rule.protected and attempt.lease.action_contract_ref.definition_id != "payload_release":
        return "protected_profile_mismatch"
    return None
