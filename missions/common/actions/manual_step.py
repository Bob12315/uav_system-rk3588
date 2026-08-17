from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from contracts.frames import LOCAL_NED

from .base import ActionModule
from .result import ActionResult


@dataclass(frozen=True, slots=True)
class LocalStepTarget:
    north_m: float
    east_m: float
    down_m: float


def body_step_to_local_target(
    *, north_m: float, east_m: float, down_m: float, yaw_rad: float,
    direction: str, step_m: float,
) -> LocalStepTarget:
    """Convert one body-relative step into an absolute LOCAL_NED target."""
    if not all(math.isfinite(float(value)) for value in (north_m, east_m, down_m, yaw_rad, step_m)):
        raise ValueError("manual step inputs must be finite")
    if step_m <= 0.0:
        raise ValueError("step_m must be positive")
    if direction not in {"forward", "back", "left", "right", "up", "down"}:
        raise ValueError(f"invalid direction: {direction}")
    forward_m = step_m if direction == "forward" else -step_m if direction == "back" else 0.0
    right_m = step_m if direction == "right" else -step_m if direction == "left" else 0.0
    down_offset_m = step_m if direction == "down" else -step_m if direction == "up" else 0.0
    return LocalStepTarget(
        north_m=north_m + forward_m * math.cos(yaw_rad) - right_m * math.sin(yaw_rad),
        east_m=east_m + forward_m * math.sin(yaw_rad) + right_m * math.cos(yaw_rad),
        down_m=down_m + down_offset_m,
    )


class ManualStepAction(ActionModule):
    """Emit one audited LOCAL_NED position request for a Web manual step."""

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self.direction = str(data.get("direction", "")).strip().lower()
        self.step_m = float(data.get("step_m", 0.0))
        body_step_to_local_target(
            north_m=0.0, east_m=0.0, down_m=0.0, yaw_rad=0.0,
            direction=self.direction, step_m=self.step_m,
        )
        self.priority = int(data.get("priority", 2))
        self.started = True
        self.stopped = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started or self.stopped:
            return ActionResult(failed=True, reason="manual_step_not_running")
        data = context or {}
        drone = data.get("drone")
        if not isinstance(drone, dict):
            return ActionResult(failed=True, reason="telemetry_state_unavailable")
        if not bool(drone.get("connected", False)):
            return ActionResult(failed=True, reason="telemetry_disconnected")
        if bool(drone.get("stale", True)):
            return ActionResult(failed=True, reason="telemetry_stale")
        if not bool(drone.get("control_allowed", False)):
            return ActionResult(failed=True, reason="control_not_allowed")
        if not bool(drone.get("local_position_valid", False)):
            return ActionResult(failed=True, reason="local_position_unavailable")
        yaw_value = data.get("arm_heading_yaw_rad")
        if yaw_value is None:
            if not bool(drone.get("attitude_valid", False)):
                return ActionResult(failed=True, reason="attitude_unavailable")
            yaw_value = drone.get("yaw")
        try:
            yaw_rad = float(yaw_value)
            target = body_step_to_local_target(
                north_m=float(drone["local_x"]), east_m=float(drone["local_y"]),
                down_m=float(drone["local_z"]), yaw_rad=yaw_rad,
                direction=self.direction, step_m=self.step_m,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return ActionResult(failed=True, reason=f"invalid_manual_step_context: {exc}")
        self.stopped = True
        target_detail = {
            "north_m": target.north_m, "east_m": target.east_m,
            "z_down_m": target.down_m, "yaw_rad": yaw_rad,
        }
        return ActionResult(
            effects=ActionResult.typed([{
                "action_type": "local_position",
                "params": {"x": target.north_m, "y": target.east_m, "z": target.down_m,
                           "frame": LOCAL_NED, "yaw": yaw_rad},
                "input_frame": "local_ned",
                "local_target": dict(target_detail),
                "key": "manual_step", "once": True, "priority": self.priority,
            }]),
            done=True,
            reason="manual_step_target_ready",
            detail={"direction": self.direction, "step_m": self.step_m, "target": target_detail},
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.direction = ""
        self.step_m = 0.0
        self.priority = 2
        self.started = False
        self.stopped = False
