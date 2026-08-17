from application.core.execution_fence_authority import CoreExecutionFenceAuthority
from contracts.platform.common import ActionInstanceId, LeaseId, LinkSessionId, RunId


def test_execution_generations_never_recycle_after_revoke() -> None:
    authority = CoreExecutionFenceAuthority("sitl", LinkSessionId("session"))
    first = authority.activate(RunId("run-1"), ActionInstanceId("action-1"), LeaseId("lease-1"), 1)
    authority.revoke(2)
    second = authority.activate(RunId("run-2"), ActionInstanceId("action-2"), LeaseId("lease-2"), 3)
    assert second.run_execution_generation > first.run_execution_generation
    assert second.authorization_generation > first.authorization_generation
    assert second.lease_generation > first.lease_generation


def test_source_switch_forces_send_generation_and_cancellation_generation() -> None:
    authority = CoreExecutionFenceAuthority("real", LinkSessionId("real-session"))
    before = authority.snapshot()
    after = authority.switch_session("sitl", LinkSessionId("sitl-session"), 5)
    assert after.run_id is None
    assert after.send_generation > before.send_generation
    assert after.cancellation_generation > before.cancellation_generation
