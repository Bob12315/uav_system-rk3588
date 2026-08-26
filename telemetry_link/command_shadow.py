from __future__ import annotations

import time
import uuid

from contracts.platform.common import SchemaVersion
from contracts.platform.vehicle_commands import (
    AckPolicy, Arm, ChangeSpeed, CompletionPolicy, ConditionYaw, GimbalAngle,
    GlobalPositionTarget, Land, LocalPositionTarget, SetMode, SetServo, Takeoff,
    VehicleCommandEnvelope,
)
from .command_broker import CommandBroker
from .models import ActionCommand, ActionType


class LegacyOneShotShadow:
    """Copies supported legacy one-shots into a write-disabled typed broker."""

    def __init__(self, *, source: str, session_id) -> None:
        self.source = source
        self._session_id = session_id
        self.broker = CommandBroker(
            writer=None, source=lambda: self.source, link_session=self._session_id,
            authorization_generation=lambda: 0, send_generation=lambda: 0,
            monotonic_ns=time.monotonic_ns, shadow=True,
        )

    def observe(self, command: ActionCommand) -> str | None:
        payload = self._payload(command)
        if payload is None:
            return None
        now = time.monotonic_ns()
        command_id = uuid.uuid4().hex
        policy = AckPolicy.DISABLED if payload.kind in {"set_mode", "local_position", "global_position"} else AckPolicy.RECORD_ONLY
        completion = CompletionPolicy.STATE_OBSERVED if payload.kind in {"set_mode", "arm", "takeoff", "land", "local_position", "global_position"} else CompletionPolicy.TRANSPORT_ONLY
        envelope = VehicleCommandEnvelope(
            SchemaVersion(1, 0), command_id, "compat-shadow", "compat-shadow", 0, 0,
            self.source, self._session_id(), now, now + 5_000_000_000,
            command.priority, command_id, policy, completion, 500, payload,
        )
        self.broker.submit(envelope)
        self.broker.drain_one()
        return command_id

    @staticmethod
    def _payload(command: ActionCommand):
        p = command.params
        kind = command.action_type
        if kind == ActionType.SET_MODE: return SetMode(str(p["mode"]))
        if kind == ActionType.ARM: return Arm(True)
        if kind == ActionType.DISARM: return Arm(False)
        if kind == ActionType.TAKEOFF: return Takeoff(float(p["altitude_m"]))
        if kind == ActionType.LAND: return Land()
        if kind == ActionType.LOCAL_POSITION: return LocalPositionTarget(float(p["x"]), float(p["y"]), float(p["z"]), p.get("yaw"))
        if kind == ActionType.GLOBAL_GOTO:
            return GlobalPositionTarget(
                float(p["lat"]), float(p["lon"]), float(p["alt"]), p.get("yaw")
            )
        if kind == ActionType.CONDITION_YAW: return ConditionYaw(float(p["yaw_deg"]), bool(p.get("relative", False)))
        if kind == ActionType.CHANGE_SPEED: return ChangeSpeed(float(p["speed_mps"]))
        if kind == ActionType.SET_SERVO: return SetServo(int(p["channel"]), int(p["pwm"]))
        if kind == ActionType.GIMBAL_ANGLE: return GimbalAngle(float(p["yaw"]), float(p["pitch"]))
        return None
