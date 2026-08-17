from datetime import datetime, timezone

from application.core.run_io_aggregate import DetachedRunIoTracker, RunIoAggregate
from contracts.core.run_io import (
    ResultProjectionPolicy,
    RunIoObservation,
    RunIoState,
    RunIoSubmissionReceipt,
    RunRecordingPolicy,
)
from contracts.core.time import CoreTime
from contracts.platform.common import RunId


def test_required_recording_and_result_do_not_treat_acceptance_as_completion() -> None:
    aggregate = RunIoAggregate(
        RunRecordingPolicy(required=True, enabled=True),
        ResultProjectionPolicy(required=True, enabled=True),
    )
    acquire = aggregate.plan_start(RunId("run"), 1, 100)[0]
    aggregate.submitted(RunIoSubmissionReceipt(acquire.operation_id, True, False))
    assert not aggregate.start_ready
    now = CoreTime(10, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")
    aggregate.observed(RunIoObservation(acquire.operation_id, RunIoState.ACTIVE, now))
    assert aggregate.start_ready

    result = aggregate.plan_success(RunId("run"), 1, 200)[0]
    aggregate.submitted(RunIoSubmissionReceipt(result.operation_id, True, False))
    assert not aggregate.success_ready
    aggregate.observed(RunIoObservation(result.operation_id, RunIoState.PERSISTED, now))
    assert aggregate.success_ready


def test_recording_release_and_detached_tracker_are_bounded() -> None:
    aggregate = RunIoAggregate(RunRecordingPolicy(False, True), ResultProjectionPolicy())
    now = CoreTime(10, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")
    acquire = aggregate.plan_start(RunId("run"), 1, 100)[0]
    aggregate.observed(RunIoObservation(acquire.operation_id, RunIoState.ACTIVE, now))
    release = aggregate.plan_release(RunId("run"), 1, 200)[0]
    assert not aggregate.release_done
    aggregate.observed(RunIoObservation(release.operation_id, RunIoState.RELEASED, now))
    assert aggregate.release_done

    tracker = DetachedRunIoTracker(capacity=1)
    tracker.attach(release.operation_id, 20)
    assert tracker.pending(19) == (release.operation_id,)
    assert tracker.pending(20) == ()
