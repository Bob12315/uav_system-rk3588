from __future__ import annotations

import json
import math
import socket
import threading
from types import SimpleNamespace

import pytest

from telemetry_link.attitude_udp_publisher import AttitudeSample as PublisherSample
from telemetry_link.attitude_udp_publisher import AttitudeUdpPublisher
from telemetry_link.state_cache import StateCache
from telemetry_link.telemetry_receiver import TelemetryReceiver
from yolo_app.attitude_history import AttitudeHistory, AttitudeSample
from yolo_app.attitude_receiver import AttitudeReceiver


def _sample(
    sequence: int,
    timestamp_ns: int,
    *,
    yaw: float = 0.0,
    publisher: str = "publisher-a",
    link: str = "link-a",
) -> AttitudeSample:
    return AttitudeSample(
        publisher, link, "sitl", sequence, timestamp_ns,
        0.0, 0.0, yaw, 0.0, 0.0, 0.0,
    )


def _wire(sequence: int, *, publisher: str, link: str, timestamp_ns: int) -> bytes:
    return json.dumps({
        "schema_version": 1,
        "message_type": "attitude",
        "publisher_session_id": publisher,
        "sequence": sequence,
        "source": "sitl",
        "link_session_id": link,
        "received_at_monotonic_ns": timestamp_ns,
        "sent_at_monotonic_ns": timestamp_ns + 1,
        "roll_rad": 0.1,
        "pitch_rad": -0.2,
        "yaw_rad": 0.3,
        "roll_rate_rad_s": 0.4,
        "pitch_rate_rad_s": 0.5,
        "yaw_rate_rad_s": 0.6,
    }).encode()


def _reset_wire(*, publisher: str, source: str) -> bytes:
    return json.dumps({
        "schema_version": 1,
        "message_type": "attitude_reset",
        "publisher_session_id": publisher,
        "sequence": 0,
        "source": source,
        "sent_at_monotonic_ns": 1,
    }).encode()


def test_history_slerp_crosses_yaw_wrap_on_short_path() -> None:
    history = AttitudeHistory(max_samples=8, history_ms=1000)
    history.append(_sample(1, 1_000_000_000, yaw=math.radians(179.0)))
    history.append(_sample(2, 1_100_000_000, yaw=math.radians(-179.0)))

    match = history.lookup(
        1_050_000_000,
        max_sample_distance_ms=60,
        max_bracket_span_ms=120,
    )

    assert match.valid
    assert abs(abs(math.degrees(match.yaw_rad)) - 180.0) < 1e-6
    assert match.before_sequence == 1 and match.after_sequence == 2


def test_history_requires_both_sides_and_rejects_stale_sample() -> None:
    history = AttitudeHistory(max_samples=8, history_ms=1000)
    history.append(_sample(1, 1_000_000_000))

    missing_after = history.lookup(
        1_010_000_000,
        max_sample_distance_ms=50,
        max_bracket_span_ms=100,
    )
    assert not missing_after.valid and missing_after.reason == "missing_attitude_after"

    history.append(_sample(2, 1_200_000_000))
    stale = history.lookup(
        1_100_000_000,
        max_sample_distance_ms=50,
        max_bracket_span_ms=250,
    )
    assert not stale.valid and stale.reason == "attitude_sample_too_far"


def test_history_is_bounded_and_session_change_clears_old_samples() -> None:
    history = AttitudeHistory(max_samples=4, history_ms=10_000)
    for sequence in range(1, 7):
        assert history.append(_sample(sequence, sequence * 10_000_000))
    assert len(history) == 4

    assert history.append(_sample(1, 100_000_000, publisher="publisher-b", link="link-b"))
    assert len(history) == 1
    assert history.session_key == ("publisher-b", "link-b", "sitl")


def test_history_fails_closed_when_observed_attitude_rate_is_low() -> None:
    history = AttitudeHistory(max_samples=16, history_ms=2000)
    for sequence in range(1, 6):
        history.append(_sample(sequence, sequence * 100_000_000))  # 10 Hz

    match = history.lookup(
        450_000_000,
        max_sample_distance_ms=60,
        max_bracket_span_ms=120,
        min_rate_hz=25.0,
        rate_window_ms=1000,
        min_rate_samples=4,
    )

    assert not match.valid
    assert match.reason == "attitude_rate_insufficient"
    assert match.observed_rate_hz == pytest.approx(10.0)


def test_history_accepts_observed_attitude_rate_near_30_hz() -> None:
    history = AttitudeHistory(max_samples=16, history_ms=2000)
    step_ns = 33_000_000
    for sequence in range(1, 7):
        history.append(_sample(sequence, sequence * step_ns))

    match = history.lookup(
        5 * step_ns + step_ns // 2,
        max_sample_distance_ms=20,
        max_bracket_span_ms=40,
        min_rate_hz=25.0,
        rate_window_ms=1000,
        min_rate_samples=4,
    )

    assert match.valid
    assert match.observed_rate_hz is not None and match.observed_rate_hz > 30.0


def test_history_rate_uses_full_window_instead_of_four_jittery_samples() -> None:
    history = AttitudeHistory(max_samples=64, history_ms=2000)
    timestamps_ns = [sequence * 30_000_000 for sequence in range(1, 23)]
    timestamps_ns.extend([710_000_000, 760_000_000, 810_000_000, 860_000_000])
    for sequence, timestamp_ns in enumerate(timestamps_ns, start=1):
        history.append(_sample(sequence, timestamp_ns))

    match = history.lookup(
        835_000_000,
        max_sample_distance_ms=30,
        max_bracket_span_ms=60,
        min_rate_hz=25.0,
        rate_window_ms=1000,
        min_rate_samples=4,
    )

    assert match.valid
    assert match.observed_rate_hz == pytest.approx(25 / 830e-3)


def test_receiver_retires_old_link_session() -> None:
    history = AttitudeHistory(max_samples=8, history_ms=1000)
    receiver = AttitudeReceiver("127.0.0.1", 0, history, expected_source="sitl")
    try:
        assert receiver.ingest(_wire(1, publisher="a", link="link-a", timestamp_ns=10)) == "accepted"
        assert receiver.ingest(_wire(1, publisher="b", link="link-b", timestamp_ns=20)) == "accepted"
        assert receiver.ingest(_wire(2, publisher="a", link="link-a", timestamp_ns=30)) == "retired_session"
        assert len(history) == 1
        assert history.session_key == ("b", "link-b", "sitl")
    finally:
        receiver.close()


def test_active_source_reset_clears_history_and_retires_old_source() -> None:
    history = AttitudeHistory(max_samples=8, history_ms=1000)
    receiver = AttitudeReceiver("127.0.0.1", 0, history, expected_source="active")
    try:
        assert receiver.ingest(_wire(1, publisher="a", link="link-a", timestamp_ns=10)) == "accepted"
        assert receiver.ingest(_reset_wire(publisher="b", source="real")) == "accepted_reset"
        assert len(history) == 0
        assert receiver.ingest(_wire(2, publisher="a", link="link-a", timestamp_ns=30)) == "retired_session"
    finally:
        receiver.close()


def test_publisher_preserves_short_burst_and_contains_link_identity() -> None:
    sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink.bind(("127.0.0.1", 0))
    sink.settimeout(1.0)
    stop_event = threading.Event()
    publisher = AttitudeUdpPublisher(
        "127.0.0.1", sink.getsockname()[1], source="sitl", stop_event=stop_event
    )
    try:
        publisher.offer(PublisherSample("sitl", "link-a", 10, 0, 0, 0, 0, 0, 0))
        publisher.offer(PublisherSample("sitl", "link-a", 20, 1, 2, 3, 4, 5, 6))
        publisher.start()
        first_payload, _addr = sink.recvfrom(4096)
        second_payload, _addr = sink.recvfrom(4096)
        first = json.loads(first_payload)
        second = json.loads(second_payload)
        assert first["schema_version"] == 1
        assert first["sequence"] == 1
        assert first["link_session_id"] == "link-a"
        assert first["received_at_monotonic_ns"] == 10
        assert second["sequence"] == 2
        assert second["received_at_monotonic_ns"] == 20
        assert second["roll_rad"] == pytest.approx(1.0)
    finally:
        stop_event.set()
        publisher.close()
        sink.close()


def test_publisher_drops_oldest_sample_when_bounded_fifo_overflows() -> None:
    sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink.bind(("127.0.0.1", 0))
    sink.settimeout(1.0)
    stop_event = threading.Event()
    publisher = AttitudeUdpPublisher(
        "127.0.0.1",
        sink.getsockname()[1],
        source="sitl",
        stop_event=stop_event,
        max_pending_samples=2,
    )
    try:
        for timestamp_ns in (10, 20, 30):
            publisher.offer(PublisherSample(
                "sitl", "link-a", timestamp_ns, 0, 0, 0, 0, 0, 0
            ))
        publisher.start()
        received = [json.loads(sink.recvfrom(4096)[0]) for _ in range(2)]
        assert [item["received_at_monotonic_ns"] for item in received] == [20, 30]
    finally:
        stop_event.set()
        publisher.close()
        sink.close()


def test_publisher_switch_source_emits_reset_and_rejects_old_source() -> None:
    sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink.bind(("127.0.0.1", 0))
    sink.settimeout(1.0)
    stop_event = threading.Event()
    publisher = AttitudeUdpPublisher(
        "127.0.0.1", sink.getsockname()[1], source="sitl", stop_event=stop_event
    )
    publisher.start()
    try:
        publisher.switch_source("real")
        payload, _addr = sink.recvfrom(4096)
        reset = json.loads(payload)
        assert reset["message_type"] == "attitude_reset"
        assert reset["source"] == "real"

        publisher.offer(PublisherSample("sitl", "old", 10, 0, 0, 0, 0, 0, 0))
        publisher.offer(PublisherSample("real", "new", 20, 0, 0, 0, 0, 0, 0))
        payload, _addr = sink.recvfrom(4096)
        attitude = json.loads(payload)
        assert attitude["message_type"] == "attitude"
        assert attitude["source"] == "real"
        assert attitude["link_session_id"] == "new"
    finally:
        stop_event.set()
        publisher.close()
        sink.close()


def test_telemetry_receiver_timestamps_attitude_at_handler_and_preserves_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = SimpleNamespace(active_source="sitl", attitude_udp_enabled=False)
    cache = StateCache(heartbeat_timeout_sec=3.0, rx_timeout_sec=1.0)
    receiver = TelemetryReceiver(None, cache, cfg, threading.Event(), source_name="sitl")

    class Sink:
        def __init__(self) -> None:
            self.sample: PublisherSample | None = None

        def offer(self, sample: PublisherSample) -> None:
            self.sample = sample

    sink = Sink()
    receiver.attitude_publisher = sink  # type: ignore[assignment]
    monkeypatch.setattr("telemetry_link.telemetry_receiver.time.monotonic_ns", lambda: 123456789)
    message = SimpleNamespace(
        roll=0.1,
        pitch=-0.2,
        yaw=0.3,
        rollspeed=0.4,
        pitchspeed=-0.5,
        yawspeed=0.6,
    )

    receiver._handle_message("ATTITUDE", message, now=10.0)

    state = cache.get_latest_drone_state_raw()
    assert state.attitude_valid
    assert (state.roll, state.pitch, state.yaw) == pytest.approx((0.1, -0.2, 0.3))
    assert sink.sample is not None
    assert sink.sample.received_at_monotonic_ns == 123456789
    assert sink.sample.link_session_id == cache.atomic_publication(10.0)["session_id"]
    assert sink.sample.source == "sitl"
