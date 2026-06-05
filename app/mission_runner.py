from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from missions.base import Mission, MissionAction, MissionContext, MissionOutput


@dataclass(slots=True)
class MissionRunner:
    mission: Mission
    link_manager: Any | None = None
    yolo_client: Any | None = None
    send_actions: bool = False
    executed_action_keys: set[str] = field(default_factory=set)
    action_log: deque[str] = field(default_factory=lambda: deque(maxlen=120))
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("MissionRunner")
    )

    def reset(self) -> None:
        self.mission.reset()
        self.executed_action_keys.clear()
        self.action_log.clear()

    def update(self, context: MissionContext) -> MissionOutput:
        output = self.mission.update(context)
        self._dispatch_actions(output.actions)
        return output

    def _dispatch_actions(self, actions: list[MissionAction]) -> None:
        for action in actions:
            if action.once and action.key and action.key in self.executed_action_keys:
                continue
            dispatched = self._dispatch_action(action)
            if dispatched and action.once and action.key:
                self.executed_action_keys.add(action.key)

    def _dispatch_action(self, action: MissionAction) -> bool:
        action_type = str(action.action_type)
        params = dict(action.params)
        priority = int(action.priority)

        if not self.send_actions:
            self._log_action("DRY", "action skipped", action, params)
            return False

        try:
            if action_type == "yolo_lock_target":
                if self.yolo_client is None:
                    self._log_action("DROP", "action missing_yolo_client", action, params)
                    return False
                self.yolo_client.lock_target(int(params["track_id"]))
            elif action_type == "yolo_unlock_target":
                if self.yolo_client is None:
                    self._log_action("DROP", "action missing_yolo_client", action, params)
                    return False
                self.yolo_client.unlock_target()
            else:
                if self.link_manager is None:
                    self._log_action("DROP", "action missing_link", action, params)
                    return False
                return self._dispatch_link_action(action, action_type, params, priority)
        except Exception:
            self._log_action("FAIL", "action dispatch_failed", action, params)
            self.logger.exception("mission action dispatch failed: %s", action_type)
            return False

        self._log_action("TX", "action queued", action, params)
        return True

    def _dispatch_link_action(
        self,
        action: MissionAction,
        action_type: str,
        params: dict[str, object],
        priority: int,
    ) -> bool:
        try:
            if action_type == "set_mode":
                self.link_manager.set_mode(str(params["mode"]), priority=priority)
            elif action_type == "arm":
                self.link_manager.arm(priority=priority)
            elif action_type == "disarm":
                self.link_manager.disarm(priority=priority)
            elif action_type == "takeoff":
                self.link_manager.takeoff(float(params["altitude_m"]), priority=priority)
            elif action_type == "gimbal_angle":
                self.link_manager.send_gimbal_angle(
                    pitch=float(params["pitch"]),
                    yaw=float(params.get("yaw", 0.0)),
                    roll=float(params.get("roll", 0.0)),
                    priority=priority,
                )
            elif action_type == "land":
                self.link_manager.land(priority=priority)
            elif action_type == "local_position":
                self.link_manager.local_position(
                    float(params["x"]),
                    float(params["y"]),
                    float(params["z"]),
                    int(params.get("frame", 1)),
                    yaw=None if params.get("yaw") is None else float(params["yaw"]),
                    priority=priority,
                )
            elif action_type == "global_goto":
                self.link_manager.global_goto(
                    float(params["lat"]),
                    float(params["lon"]),
                    float(params["alt"]),
                    int(params.get("frame", 3)),
                    priority=priority,
                )
            elif action_type == "set_servo":
                self.link_manager.set_servo(
                    int(params["channel"]),
                    int(params["pwm"]),
                    priority=priority,
                )
            elif action_type == "set_relay":
                self.link_manager.set_relay(
                    int(params["relay_id"]),
                    bool(params["state"]),
                    priority=priority,
                )
            elif action_type == "release_payload":
                self.link_manager.release_payload(
                    int(params["payload_id"]),
                    priority=priority,
                )
            else:
                self._log_action("DROP", "action unknown", action, params)
                return False
        except Exception:
            self._log_action("FAIL", "action dispatch_failed", action, params)
            self.logger.exception("mission action dispatch failed: %s", action_type)
            return False

        self._log_action("TX", "action queued", action, params)
        return True

    def _log_action(
        self,
        level: str,
        message: str,
        action: MissionAction,
        params: dict[str, object],
    ) -> None:
        line = (
            f"{level} {message} action={action.action_type} "
            f"key={action.key or '-'} params={params}"
        )
        self.action_log.appendleft(line)
        if level == "FAIL":
            return
        if level == "TX":
            self.logger.info(line)
        elif level == "DROP":
            self.logger.warning(line)
        else:
            self.logger.debug(line)

    def get_action_log_lines(self) -> list[str]:
        return list(self.action_log)
