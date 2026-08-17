from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
import yaml
from pymavlink import mavutil

from contracts.platform.common import SchemaVersion
from contracts.platform.vehicle_commands import (
    AckPolicy, AckState, BodyVelocity, CompletionPolicy, SetServo, SubmissionState,
    TransportState, VehicleCommandEnvelope,
)
from telemetry_link.ack_router import AckRouter, AckSlot
from telemetry_link.command_broker import CommandBroker
from telemetry_link.command_queue import CommandQueue
from telemetry_link.command_sender import CommandSender
from telemetry_link.config import DEFAULT_CONFIG_PATH, _build_config
from telemetry_link.mavlink_command_adapter import MavlinkCommandAdapter, WriteContext
from telemetry_link.mavlink_encoder import MavlinkEnvelopeWriter
from telemetry_link.models import ActionCommand, ActionType, ControlCommand, ControlType
from telemetry_link.frames import BODY_NED, LOCAL_NED
from telemetry_link.state_cache import StateCache
from telemetry_link.link_manager import LinkManager, SourceRuntime
import telemetry_link.link_manager as link_manager_module
from telemetry_link.config import EndpointConfig
import logging
import time


class _Mav:
    def __init__(self): self.calls = []
    def command_long_send(self, *args): self.calls.append(args)
    def set_position_target_local_ned_send(self, *args): self.calls.append(args)


class _Client:
    target_system = 1
    target_component = 0
    autopilot_component = 1
    local_system = 255
    local_component = 0
    connection_string = "fake:sitl"
    is_sitl = True
    def __init__(self): self.master = SimpleNamespace(target_system=1, target_component=0, mav=_Mav())
    def send_raw_message(self, callback): callback(self.master)

    def connect(self): pass
    def wait_heartbeat(self, timeout): pass
    def recv_message(self, timeout=0.1):
        time.sleep(0.001)
        return None
    def close(self): pass


class _ImmediateWorker:
    def notify(self): pass


def _backend():
    cfg_data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = _build_config(cfg_data)
    cache = StateCache(3, 2)
    client = _Client()
    encoder = CommandSender(client, CommandQueue(), cache, cfg, threading.Event(), propagate_errors=True)
    writer = MavlinkEnvelopeWriter(encoder)
    context = WriteContext("run", "lease", 1, 1, True)
    broker = CommandBroker(writer=writer, source=lambda: "sitl", link_session=lambda: "session",
        authorization_generation=lambda: context.authorization_generation,
        send_generation=lambda: context.send_generation, send_enabled=lambda: context.send_enabled,
        monotonic_ns=lambda: 10, connected=lambda: True)
    adapter = MavlinkCommandAdapter(broker, _ImmediateWorker(), source="sitl",
                                    session_id=lambda: "session", context=context)
    return client, broker, adapter


def test_v2_one_shot_has_one_writer_and_transmitted_only_after_wire() -> None:
    client, broker, adapter = _backend()
    receipt = adapter.submit_action(ActionCommand(ActionType.SET_SERVO, {"channel": 8, "pwm": 1500}))
    assert broker.status(receipt.command_id).transport_state == TransportState.NOT_ATTEMPTED
    broker.drain_one()
    assert broker.status(receipt.command_id).transport_state == TransportState.TRANSMITTED
    assert len(client.master.mav.calls) == 1
    assert client.master.mav.calls[0][2] == mavutil.mavlink.MAV_CMD_DO_SET_SERVO


def test_v2_control_rejects_implicit_frame_conversion_and_types_stop() -> None:
    _client, broker, adapter = _backend()
    rejected = adapter.submit_control(ControlCommand(ControlType.VELOCITY, vx=1.0,
        timestamp=time.time(), frame=LOCAL_NED))
    assert rejected.submission_state == SubmissionState.REJECTED
    assert rejected.reason_code == "unsupported_control_frame"
    stop = adapter.submit_control(ControlCommand(ControlType.STOP, timestamp=time.time(), frame=BODY_NED))
    assert stop.submission_state == SubmissionState.ACCEPTED
    broker.drain_one()
    assert broker.status(stop.command_id).transport_state == TransportState.TRANSMITTED
    assert broker._active_motion == set()


def test_backend_configuration_is_strict_xor() -> None:
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    for legacy, v2 in ((False, False), (True, True)):
        data["legacy_writer_enabled"] = legacy
        data["v2_writer_enabled"] = v2
        with pytest.raises(ValueError, match="exactly one"):
            _build_config(data)


def test_test_only_sitl_composition_constructs_no_real_client(monkeypatch) -> None:
    constructed = []
    monkeypatch.setattr(link_manager_module, "MavlinkClient",
                        lambda endpoint: constructed.append(endpoint.name) or _Client())
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data.update(data_source="sitl", active_source="sitl")
    manager = LinkManager(_build_config(data))
    assert tuple(manager.runtimes) == ("sitl",)
    assert constructed == ["sitl"] and "real" not in constructed


def test_source_switch_clears_both_backends_and_reports_undeliverable_stop(monkeypatch) -> None:
    monkeypatch.setattr(link_manager_module, "MavlinkClient", lambda _endpoint: _Client())
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data.update(data_source="dual", active_source="real")
    manager = LinkManager(_build_config(data))
    old_writer = []
    old = CommandBroker(writer=old_writer.append, source=lambda: "real",
        link_session=lambda: "real-session", authorization_generation=lambda: 1,
        send_generation=lambda: 1, send_enabled=lambda: True,
        connected=lambda: False, monotonic_ns=lambda: 10)
    new = CommandBroker(writer=lambda _value: None, source=lambda: "sitl",
        link_session=lambda: "sitl-session", authorization_generation=lambda: 1,
        send_generation=lambda: 1, send_enabled=lambda: True, monotonic_ns=lambda: 10)
    motion = VehicleCommandEnvelope(SchemaVersion(1, 0), "motion", "run", "lease", 1, 1,
        "real", "real-session", 1, 1000, 1, "motion", AckPolicy.DISABLED,
        CompletionPolicy.TRANSPORT_ONLY, 0, BodyVelocity(1, 0, 0))
    pending = VehicleCommandEnvelope(SchemaVersion(1, 0), "pending", "run", "lease", 1, 1,
        "sitl", "sitl-session", 1, 1000, 1, "pending", AckPolicy.RECORD_ONLY,
        CompletionPolicy.TRANSPORT_ONLY, 100, SetServo(8, 1500))
    old.submit(motion); old.drain_one(); new.submit(pending)
    manager.runtimes["real"].command_broker = old
    manager.runtimes["sitl"].command_broker = new
    for runtime in manager.runtimes.values():
        runtime.command_queue.put_action(ActionCommand(ActionType.LAND, created_at=time.time()))
    receipt = manager.activate_source("sitl", expected_revision=0)
    assert receipt.accepted and receipt.barrier_disposition == "STOP_UNDELIVERABLE"
    assert new.status("pending").queue_state.value == "CANCELLED"
    assert all(runtime.command_queue.get_next_action() is None for runtime in manager.runtimes.values())


def test_early_ack_is_published_after_transmitted_event() -> None:
    holder = {}
    class Writer:
        def write(self, command):
            holder["router"].register(AckSlot(command.command_id, "session", 183, 1, 1))
            holder["router"].observe(link_session_id="session", mav_command=183,
                source_system=1, source_component=1, result=0)
        def mark_transmitted(self, command): holder["router"].mark_transmitted(command.command_id)
    context = WriteContext("run", "lease", 1, 1, True)
    broker = CommandBroker(writer=Writer(), source=lambda: "sitl", link_session=lambda: "session",
        authorization_generation=lambda: 1, send_generation=lambda: 1,
        send_enabled=lambda: True, monotonic_ns=lambda: 10)
    holder["router"] = AckRouter(broker.update_ack)
    adapter = MavlinkCommandAdapter(broker, _ImmediateWorker(), source="sitl",
                                    session_id=lambda: "session", context=context)
    receipt = adapter.submit_action(ActionCommand(ActionType.SET_SERVO, {"channel": 8, "pwm": 1500}))
    broker.drain_one()
    assert broker.status(receipt.command_id).ack_state == AckState.ACKED
    names = [event.event_type for event in broker.events.read_after(0, 20)]
    assert names.index("TRANSMITTED") < names.index("ACKED")


@pytest.mark.parametrize("legacy,v2", [(False, True), (True, False)])
def test_runtime_rehearsal_has_exactly_one_backend_owner(legacy, v2) -> None:
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data.update(legacy_writer_enabled=legacy, v2_writer_enabled=v2,
                request_message_intervals=False, data_source="sitl", active_source="sitl")
    cfg = _build_config(data)
    runtime = SourceRuntime("sitl", cfg.sitl, cfg, StateCache(3, 2), CommandQueue(),
                            _Client(), threading.Event(), threading.Event())
    runtime._connect_and_start_workers(logging.getLogger("backend-rehearsal"))
    try:
        assert (runtime.broker_worker is not None) is v2
        assert runtime.sender is not None
        assert runtime.sender.is_alive() is legacy
    finally:
        runtime.stop()
    assert runtime.broker_worker is None
    assert runtime.sender is None
