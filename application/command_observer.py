from __future__ import annotations

import time

from contracts.platform.vehicle_commands import AckState, CommandStatusSnapshot, CompletionState, VehicleCommandEnvelope


class CommandCompletionObserver:
    def __init__(self, update_completion, *, monotonic_ns=time.monotonic_ns) -> None:
        self._update_completion = update_completion
        self._monotonic_ns = monotonic_ns

    def observe(self, command: VehicleCommandEnvelope, status: CommandStatusSnapshot, vehicle) -> bool:
        if status.transmitted_at_monotonic_ns is None:
            return False
        if vehicle.link_session_id != command.expected_link_session_id:
            self._update_completion(command.command_id, CompletionState.SESSION_LOST, "completion_session_lost")
            return False
        if status.ack_state == AckState.NACKED:
            return False
        sample_is_new = vehicle.captured_at.monotonic_ns > status.transmitted_at_monotonic_ns
        sample_before_deadline = vehicle.captured_at.monotonic_ns < command.deadline_monotonic_ns
        payload = command.payload
        met = False
        if sample_is_new and sample_before_deadline:
            if payload.kind == "set_mode": met = vehicle.mode == payload.mode
            elif payload.kind == "arm": met = vehicle.armed is payload.arm
            elif payload.kind == "takeoff": met = bool(vehicle.in_air) and (vehicle.relative_altitude_m or 0.0) >= payload.altitude_m * 0.9
            elif payload.kind == "land": met = bool(vehicle.landed) or vehicle.in_air is False
            elif payload.kind == "local_position" and vehicle.local_valid:
                error = ((vehicle.local_north_m - payload.north_m) ** 2 + (vehicle.local_east_m - payload.east_m) ** 2 + (vehicle.local_down_m - payload.down_m) ** 2) ** 0.5
                met = error <= 0.5
            elif payload.kind == "global_position" and vehicle.global_valid:
                met = abs(vehicle.latitude_deg - payload.latitude_deg) < 1e-5 and abs(vehicle.longitude_deg - payload.longitude_deg) < 1e-5
        if met:
            self._update_completion(command.command_id, CompletionState.OBSERVED, "goal_observed")
            return True
        if self._monotonic_ns() >= command.deadline_monotonic_ns:
            self._update_completion(command.command_id, CompletionState.GOAL_TIMEOUT, "goal_timeout")
        return False
