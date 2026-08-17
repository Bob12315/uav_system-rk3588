from __future__ import annotations

import time
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

from contracts.platform.common import SchemaVersion
from contracts.platform.observability import *
from observability.cycle_recorder import AsyncCycleRecorder
from observability.event_publisher import IsolatedEventPublisher, RecentEventSink
from observability.jsonl_audit_adapter import JsonlAuditAdapter
from observability.jsonl_cycle_store import JsonlCycleStore
from observability.v1_cycle_writer_adapter import V1CycleWriterAdapter


def _event(event_id="e"):
    return OperationalEvent(SchemaVersion(1,0), event_id, datetime.now(timezone.utc), time.monotonic_ns(),
        "test", "thing", "INFO", "ok", None, None, "test", SchemaVersion(1,0), MappingProxyType({"x":1}))


def test_event_fanout_preserves_id_and_isolates_failure() -> None:
    class Bad:
        def append(self, event): raise OSError("disk")
    recent=RecentEventSink(); publisher=IsolatedEventPublisher((("recent",recent,4),("bad",Bad(),4)))
    receipt=publisher.publish(_event("same")); time.sleep(0.03)
    assert receipt.event_id == "same" and recent.latest(1).items[0].event_id == "same"
    assert publisher.health()["bad"]["failures"] == 1
    publisher.close()


def test_event_cursor_survives_recent_buffer_eviction() -> None:
    recent = RecentEventSink(capacity=3)
    for index in range(5):
        recent.append(_event(f"e{index}"))
    first = recent.latest(2)
    assert [item.event_id for item in first.items] == ["e2", "e3"]
    second = recent.latest(2, first.next_cursor)
    assert [item.event_id for item in second.items] == ["e4"]


def test_event_slow_sink_overflow_is_nonblocking_and_close_is_bounded() -> None:
    release = threading.Event()
    class Slow:
        def append(self, event): release.wait(0.5)
    publisher = IsolatedEventPublisher((("slow", Slow(), 1),))
    started = time.monotonic()
    receipts = [publisher.publish(_event(f"slow-{index}")) for index in range(4)]
    assert time.monotonic() - started < 0.1
    assert any(item.sinks[0].disposition == SinkDisposition.DROPPED for item in receipts)
    release.set(); publisher.close(0.5)
    assert not publisher._workers[0].thread.is_alive()


def test_audit_redacts_and_persists_without_changing_business_result(tmp_path) -> None:
    adapter=JsonlAuditAdapter(tmp_path/"audit.jsonl")
    entry=AuditEntry(SchemaVersion(1,0),"a",datetime.now(timezone.utc),"actor","admin","local","req","req",
        "set_send","system","allowed","ok",None,"sitl",{"token":"secret","value":1})
    assert adapter.append(entry).disposition == SinkDisposition.ACCEPTED
    deadline=time.time()+1
    while time.time()<deadline and adapter.receipt("a").disposition != SinkDisposition.PERSISTED: time.sleep(0.01)
    assert adapter.latest(1).items[0].sanitized_detail["token"] == "[REDACTED]"
    adapter.close()


def test_audit_latest_cursor_is_bounded_newest_first_window(tmp_path) -> None:
    adapter = JsonlAuditAdapter(tmp_path / "audit.jsonl", receipt_capacity=3)
    for index in range(5):
        entry=AuditEntry(SchemaVersion(1,0),f"a{index}",datetime.now(timezone.utc),"actor","admin","local",
            f"req-{index}","correlation","op","resource","allowed","ok",None,None,
            {"message": "authorization=very-secret Bearer abc.def"})
        adapter.append(entry)
    deadline=time.time()+1
    while time.time()<deadline and adapter.receipt("a4").disposition != SinkDisposition.PERSISTED: time.sleep(0.01)
    first=adapter.latest(2)
    assert [item.audit_id for item in first.items] == ["a3","a4"]
    assert first.items[-1].sanitized_detail["message"] == "authorization=[REDACTED] Bearer [REDACTED]"
    second=adapter.latest(2, first.next_cursor)
    assert [item.audit_id for item in second.items] == ["a1","a2"]
    assert adapter.receipt("a0") is None
    adapter.close()


def _cycle(session, sequence):
    payload=FrozenJson.from_value({"runtime":{"mode":"test"}})
    return CycleRecordEnvelope(SchemaVersion(1,0),session,sequence,datetime.now(timezone.utc),time.monotonic_ns(),
        f"cycle-{sequence}",None,"snapshot",None,SchemaVersion(1,0),payload,payload.sha256)


def test_cycle_recorder_session_drop_oldest_and_bounded_close(tmp_path) -> None:
    runtime=tmp_path/"runtime"; store=JsonlCycleStore(runtime/"blackbox", runtime_root=runtime)
    recorder=AsyncCycleRecorder(store, capacity=2, shutdown_flush_timeout_s=0.5)
    status=recorder.start_session(RecorderStart("armed",10)); session=status.recorder_session_id
    assert session
    assert recorder.record(_cycle("wrong",0)).disposition == RecordDisposition.REJECTED
    for seq in range(5): recorder.record(_cycle(session,seq))
    final=recorder.close()
    assert final.state in {DrainState.DRAINED,DrainState.PARTIAL} and final.persisted + final.dropped > 0
    assert list((runtime/"blackbox").glob("*.jsonl"))


def test_cycle_fixture_projects_exact_historical_v1_shape() -> None:
    fixture_dir = Path("tests/fixtures/observability")
    raw = json.loads((fixture_dir / "cycle_record_envelope_v1.json").read_text(encoding="utf-8"))
    payload = FrozenJson.from_value(raw["payload"])
    record = CycleRecordEnvelope(
        SchemaVersion(**raw["schema"]), raw["recorder_session_id"], raw["sequence"],
        datetime.fromisoformat(raw["sampled_at_utc"]), raw["sampled_at_monotonic_ns"],
        raw["core_cycle_id"], raw["correlation_id"], raw["source_snapshot_ref"], raw["run_id"],
        SchemaVersion(**raw["payload_schema"]), payload, payload.sha256,
        tuple(raw["referenced_event_ids"]), raw["debug_digest"],
    )
    expected = json.loads((fixture_dir / "cycle_record_envelope_v1.expected.json").read_text(encoding="utf-8"))
    assert V1CycleWriterAdapter.project(record) == expected


def test_cycle_new_session_resets_session_status(tmp_path) -> None:
    runtime=tmp_path/"runtime"; store=JsonlCycleStore(runtime/"blackbox", runtime_root=runtime)
    recorder=AsyncCycleRecorder(store, shutdown_flush_timeout_s=0.5)
    first=recorder.start_session(RecorderStart("first",0)); first_id=first.recorder_session_id
    recorder.record(_cycle(first_id,1)); recorder.stop_session("done")
    second=recorder.start_session(RecorderStart("second",0))
    assert second.recorder_session_id != first_id
    assert second.persisted == 0 and second.dropped == 0 and second.write_failures == 0
    recorder.close()


def test_cycle_rotation_prunes_data_and_matching_meta(tmp_path) -> None:
    runtime=tmp_path/"runtime"; output=runtime/"blackbox"
    store=JsonlCycleStore(output, runtime_root=runtime, rotate_bytes=1, flush_every=100)
    recorder=AsyncCycleRecorder(store, keep_files=2, shutdown_flush_timeout_s=0.5)
    status=recorder.start_session(RecorderStart("rotate",0)); session=status.recorder_session_id
    for sequence in range(5): recorder.record(_cycle(session,sequence))
    recorder.close()
    data=list(output.glob("*.jsonl")); meta=list(output.glob("*.meta.json"))
    assert 1 <= len(data) <= 2 and len(meta) == len(data)
    assert {path.stem for path in data} == {path.name.removesuffix(".meta.json") for path in meta}


def test_cycle_start_timeout_never_reports_recording() -> None:
    release=threading.Event()
    class Store:
        current_segment=None
        def open_segment(self, metadata): release.wait(0.5)
        def prune(self, policy): return None
        def close_segment(self, status=None): return None
    recorder=AsyncCycleRecorder(Store(), shutdown_flush_timeout_s=0.01)
    status=recorder.start_session(RecorderStart("blocked",0))
    assert status.state == DrainState.PARTIAL and status.last_error == "start_barrier_timeout"
    release.set(); recorder.close(); recorder._thread.join(0.5)
    assert not recorder._thread.is_alive()


def test_cycle_store_rejects_directory_outside_runtime(tmp_path) -> None:
    try:
        JsonlCycleStore(tmp_path/"outside", runtime_root=tmp_path/"runtime")
    except ValueError as exc:
        assert "injected runtime root" in str(exc)
    else:
        raise AssertionError("cycle store accepted path outside runtime root")
