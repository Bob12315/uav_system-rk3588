from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass

from contracts.platform.common import SchemaVersion
from contracts.platform.field import ReferenceVersion
from contracts.platform.vehicle_commands import (
    COMMAND_POLICY, AckPolicy, Arm, BodyVelocity, CancelRequest, ChangeSpeed,
    CommandSubmissionReceipt, CompletionPolicy, ConditionYaw, GimbalAngle,
    GimbalRate, GlobalPositionTarget, Land, LocalPositionTarget, SetMode,
    SetServo, StopMotion, SubmissionState, Takeoff, VehicleCommandEnvelope,
)
from .frames import BODY_NED
from .command_broker import CommandBroker, CommandBrokerWorker
from .models import ActionCommand, ActionType, ControlCommand, ControlType, GimbalRateCommand


@dataclass(slots=True)
class WriteContext:
    run_id: str = "unauthorized"
    execution_lease_id: str = "unauthorized"
    authorization_generation: int = 0
    send_generation: int = 0
    send_enabled: bool = False


class MavlinkCommandAdapter:
    """Compatibility facade from legacy method parameters to typed broker submit."""

    def __init__(self, broker: CommandBroker, worker: CommandBrokerWorker, *, source: str,
                 session_id, context: WriteContext) -> None:
        self.broker = broker
        self.worker = worker
        self.source = source
        self.session_id = session_id
        self.context = context

    def submit_action(self, command: ActionCommand) -> CommandSubmissionReceipt:
        payload = self._action_payload(command)
        if payload is None:
            return CommandSubmissionReceipt(uuid.uuid4().hex, SubmissionState.REJECTED,
                                            "unsupported_vehicle_command", uuid.uuid4().hex)
        version = command.params.get("field_reference_version")
        if isinstance(version, dict):
            try: version = ReferenceVersion(str(version["generation_id"]), int(version["revision"]))
            except (KeyError, TypeError, ValueError): version = None
        return self._submit(payload, command.priority, ttl_ns=10_000_000_000,
                            field_reference_version=version if isinstance(version, ReferenceVersion) else None)

    def submit_control(self, command: ControlCommand) -> CommandSubmissionReceipt:
        if command.command_type not in {ControlType.VELOCITY, ControlType.YAW_RATE, ControlType.STOP}:
            return CommandSubmissionReceipt(uuid.uuid4().hex, SubmissionState.REJECTED,
                                            "unsupported_vehicle_command", uuid.uuid4().hex)
        if command.frame != BODY_NED:
            return CommandSubmissionReceipt(uuid.uuid4().hex, SubmissionState.REJECTED,
                                            "unsupported_control_frame", uuid.uuid4().hex)
        if command.command_type == ControlType.STOP:
            return self._submit(StopMotion(), 0, ttl_ns=500_000_000)
        payload = BodyVelocity(command.vx, command.vy, command.vz,
                               command.yaw_rate, command.yaw)
        if command.command_type == ControlType.YAW_RATE:
            payload = BodyVelocity(0.0, 0.0, 0.0, command.yaw_rate)
        return self._submit(payload, 5, ttl_ns=500_000_000)

    def submit_gimbal_rate(self, command: GimbalRateCommand) -> CommandSubmissionReceipt:
        return self._submit(GimbalRate(command.yaw_rate, command.pitch_rate), 5, ttl_ns=500_000_000)

    def cancel(self, request: CancelRequest):
        return self.broker.cancel(request)

    def _submit(self, payload, priority: int, *, ttl_ns: int,
                field_reference_version: ReferenceVersion | None = None) -> CommandSubmissionReceipt:
        now = time.monotonic_ns()
        command_id = uuid.uuid4().hex
        ack, completion = COMMAND_POLICY[payload.kind]
        envelope = VehicleCommandEnvelope(
            SchemaVersion(1, 0), command_id, self.context.run_id,
            self.context.execution_lease_id, self.context.authorization_generation,
            self.context.send_generation, self.source, self.session_id(), now, now + ttl_ns,
            priority, command_id, ack, completion, 500, payload, field_reference_version,
        )
        receipt = self.broker.submit(envelope)
        if receipt.submission_state == SubmissionState.ACCEPTED:
            self.worker.notify()
        return receipt

    @staticmethod
    def _action_payload(command: ActionCommand):
        p = command.params; kind = command.action_type
        if kind == ActionType.SET_MODE: return SetMode(str(p["mode"]))
        if kind == ActionType.ARM: return Arm(True)
        if kind == ActionType.DISARM: return Arm(False)
        if kind == ActionType.TAKEOFF: return Takeoff(float(p["altitude_m"]))
        if kind == ActionType.LAND: return Land()
        if kind == ActionType.LOCAL_POSITION: return LocalPositionTarget(float(p["x"]), float(p["y"]), float(p["z"]), None if p.get("yaw") is None else float(p["yaw"]))
        if kind == ActionType.GLOBAL_GOTO:
            return GlobalPositionTarget(
                float(p["lat"]), float(p["lon"]), float(p["alt"]),
                None if p.get("yaw") is None else float(p["yaw"]),
            )
        if kind == ActionType.CONDITION_YAW: return ConditionYaw(float(p["yaw_deg"]), bool(p.get("relative", False)))
        if kind == ActionType.CHANGE_SPEED: return ChangeSpeed(float(p["speed_mps"]))
        if kind == ActionType.SET_SERVO: return SetServo(int(p["channel"]), int(p["pwm"]))
        if kind == ActionType.GIMBAL_ANGLE: return GimbalAngle(math.radians(float(p["yaw"])), math.radians(float(p["pitch"])))
        return None
