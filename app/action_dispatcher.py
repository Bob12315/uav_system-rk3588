from __future__ import annotations

import inspect
import logging
import time
from typing import Any


from app.dispatch_policy import ACTION_DISPATCH_POLICY, DispatchRule
from app.safety_gate import SafetyGate
from telemetry_link.frames import BODY_NED, LOCAL_NED


class ActionDispatcher:
    """Owns Action Lab dispatch logic previously scattered inside SystemRunner.

    Public API mirrors the old SystemRunner methods so the compat wrappers
    are trivial one-liner delegations.
    """

    def __init__(
        self,
        *,
        policy: dict[str, DispatchRule] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._policy = policy or ACTION_DISPATCH_POLICY
        self._logger = logger or logging.getLogger(self.__class__.__name__)
        self.send_actions: bool = False
        self.dispatched_keys: set[str] = set()
        self.last_dispatch: dict[str, list[dict[str, object]]] = self.empty_dispatch()
        self.last_servo_command: dict[str, object] | None = None

    # ------------------------------------------------------------------
    # gate — mirrors _action_lab_dispatch_gate + _action_lab_dispatch_decision
    # ------------------------------------------------------------------

    def gate(
        self,
        *,
        send_commands: bool,
        action_type: str | None = None,
        action_name: str | None = None,
    ) -> tuple[bool, str]:
        ok, note = SafetyGate.check(
            send_actions=self.send_actions,
            send_commands=send_commands,
        )
        if not ok:
            return ok, note

        if action_type is not None:
            return self._gate_action_type(action_type, action_name=action_name)
        return self._gate_action_name(action_name)

    def _gate_action_type(
        self, action_type: str, *, action_name: str | None = None
    ) -> tuple[bool, str]:
        allowed, note = self._basic_gate_action_type(action_type)
        if not allowed:
            return allowed, note
        if action_name is not None:
            rule = self._policy.get(action_type)
            if rule is not None and action_name not in rule.allowed_actions:
                return False, "action_dispatch_not_enabled"
        return allowed, note

    @staticmethod
    def _basic_gate_action_type(action_type: str) -> tuple[bool, str]:
        if action_type == "set_servo":
            return True, "payload_set_servo_dispatch_enabled"
        if action_type == "local_position":
            return True, "local_position_dispatch_enabled"
        if action_type == "flight_command":
            return True, "action_dispatch_enabled"
        return False, "unsupported_action_type"

    def _gate_action_name(self, action_name: str | None) -> tuple[bool, str]:
        if action_name == "payload_release":
            return True, "payload_set_servo_dispatch_enabled"
        if action_name == "goto_waypoint":
            return True, "local_position_dispatch_enabled"
        if action_name == "survey_area":
            return True, "local_position_dispatch_enabled"
        if action_name == "align_descend":
            return True, "action_dispatch_enabled"
        return False, "action_dispatch_not_enabled"

    # ------------------------------------------------------------------
    # dispatch_result — mirrors _dispatch_action_lab_result
    # ------------------------------------------------------------------

    def dispatch_result(
        self,
        result: dict[str, object],
        *,
        action_name: str | None,
        send_commands: bool,
        link_manager: object | None,
    ) -> dict[str, list[dict[str, object]]]:
        actions = list(result.get("actions") or [])
        detail = result.get("detail")
        if isinstance(detail, dict):
            command = detail.get("command")
            if isinstance(command, dict) and command.get("type") == "flight_command":
                self._logger.info(
                    "align_descend command generated flight_command vx=%.3f vy=%.3f vz=%.3f active=%s valid=%s",
                    float(command.get("vx_cmd", 0.0)),
                    float(command.get("vy_cmd", 0.0)),
                    float(command.get("vz_cmd", 0.0)),
                    bool(command.get("active", False)),
                    bool(command.get("valid", False)),
                )
                actions.append(
                    {
                        "action_type": "flight_command",
                        "params": command,
                        "key": f"{action_name or 'action_lab'}_flight_command",
                        "once": False,
                        "priority": int(command.get("priority", 5)),
                    }
                )
        return self.dispatch_actions(
            actions,
            action_name=action_name,
            send_commands=send_commands,
            link_manager=link_manager,
        )

    # ------------------------------------------------------------------
    # dispatch_actions — mirrors _dispatch_action_lab_actions
    # ------------------------------------------------------------------

    def dispatch_actions(
        self,
        actions: list[object],
        *,
        action_name: str | None,
        send_commands: bool,
        link_manager: object | None,
    ) -> dict[str, list[dict[str, object]]]:
        dispatch = self.empty_dispatch()
        effective, note = self.gate(
            send_commands=send_commands,
            action_name=action_name,
        )
        self._logger.info(
            "action_lab dispatch gate current_action=%s send_actions_requested=%s send_commands=%s effective=%s note=%s",
            action_name,
            bool(self.send_actions),
            bool(send_commands),
            bool(effective),
            note,
        )
        if not actions:
            return dispatch

        for action in actions:
            if not isinstance(action, dict):
                dispatch["skipped"].append({"action": action, "reason": "invalid_action"})
                continue
            action_type = str(action.get("action_type") or "")
            action_allowed, action_note = self.gate(
                send_commands=send_commands,
                action_type=action_type,
                action_name=action_name,
            )
            self._logger.info(
                "action_lab dispatch decision current_action=%s action_type=%s dispatch_allowed=%s note=%s",
                action_name,
                action_type,
                bool(action_allowed),
                action_note,
            )
            if not action_allowed:
                dispatch["skipped"].append(
                    {"action": action, "action_type": action_type, "reason": action_note}
                )
                continue
            key = str(action.get("key") or "")
            once_enabled = bool(action.get("once", False)) and action_type != "flight_command"
            if once_enabled and key and key in self.dispatched_keys:
                dispatch["skipped"].append(
                    {"action": action, "action_type": action_type, "reason": "once_already_dispatched"}
                )
                continue
            try:
                outcome = self._dispatch_action(action, link_manager=link_manager)
            except Exception as exc:
                self._logger.exception("action lab dispatch failed")
                dispatch["errors"].append({"action": action, "action_type": action_type, "error": str(exc)})
                if isinstance(action, dict) and action.get("action_type") == "set_servo":
                    self.last_servo_command = {
                        "channel": (action.get("params") or {}).get("channel")
                        if isinstance(action.get("params"), dict)
                        else None,
                        "pwm": (action.get("params") or {}).get("pwm")
                        if isinstance(action.get("params"), dict)
                        else None,
                        "priority": action.get("priority", 3),
                        "time": time.time(),
                        "key": str(action.get("key") or ""),
                        "ack": None,
                        "error": str(exc),
                    }
                continue
            if outcome["status"] == "sent":
                sent = {"action": action, **dict(outcome.get("detail") or {})}
                dispatch["sent"].append(sent)
                self._logger.info("action_lab dispatch sent action_type=%s detail=%s", action_type, sent)
            elif outcome["status"] == "skipped":
                skipped = {
                    "action": action,
                    "action_type": action_type,
                    "reason": str(outcome["reason"]),
                    **dict(outcome.get("detail") or {}),
                }
                dispatch["skipped"].append(skipped)
                self._logger.info("action_lab dispatch skipped action_type=%s reason=%s", action_type, outcome["reason"])
                continue
            else:
                dispatch["errors"].append(
                    {"action": action, "action_type": action_type, "error": str(outcome["reason"])}
                )
                self._logger.info("action_lab dispatch error action_type=%s reason=%s", action_type, outcome["reason"])
                continue
            if once_enabled and key:
                self.dispatched_keys.add(key)
        return dispatch

    # ------------------------------------------------------------------
    # _dispatch_action — mirrors _dispatch_action_lab_action
    # ------------------------------------------------------------------

    def _dispatch_action(
        self,
        action: dict[str, object],
        *,
        link_manager: object | None,
    ) -> dict[str, object]:
        action_type = str(action.get("action_type") or "")
        if action_type == "set_servo":
            return self._dispatch_set_servo(action, link_manager=link_manager)
        if action_type == "local_position":
            return self._dispatch_local_position(action, link_manager=link_manager)
        if action_type == "flight_command":
            return self._dispatch_flight_command(action, link_manager=link_manager)
        return {"status": "skipped", "reason": "unsupported_action_type"}

    # ------------------------------------------------------------------
    # per-type dispatchers
    # ------------------------------------------------------------------

    @staticmethod
    def _action_params(action: dict[str, object]) -> dict[str, object]:
        params = action.get("params")
        if not isinstance(params, dict):
            raise ValueError("missing_params")
        return params

    def _dispatch_set_servo(
        self,
        action: dict[str, object],
        *,
        link_manager: object | None,
    ) -> dict[str, object]:
        if link_manager is None:
            params = action.get("params") if isinstance(action.get("params"), dict) else {}
            self.last_servo_command = {
                "channel": params.get("channel"),
                "pwm": params.get("pwm"),
                "priority": action.get("priority", 3),
                "time": time.time(),
                "key": str(action.get("key") or ""),
                "ack": None,
                "error": "telemetry_not_connected",
            }
            return {"status": "error", "reason": "telemetry_not_connected"}
        params = self._action_params(action)
        channel = int(params["channel"])
        pwm = int(params["pwm"])
        priority = int(action.get("priority", 3))
        self._logger.info(
            "action_lab dispatch set_servo channel=%s pwm=%s priority=%s key=%s",
            channel,
            pwm,
            priority,
            action.get("key"),
        )
        # prefer semantic wrapper (T4)
        wrapper = getattr(link_manager, "set_servo_output_pwm", None)
        if callable(wrapper):
            wrapper(servo_output=channel, pwm=pwm, priority=priority)
        else:
            set_servo = getattr(link_manager, "set_servo", None)
            if not callable(set_servo):
                return {"status": "error", "reason": "set_servo_not_callable"}
            set_servo(channel, pwm, priority=priority)
        self.last_servo_command = {
            "channel": channel,
            "pwm": pwm,
            "priority": priority,
            "time": time.time(),
            "key": str(action.get("key") or ""),
            "ack": None,
            "error": None,
        }
        return {
            "status": "sent",
            "detail": {
                "action_type": "set_servo",
                "channel": channel,
                "pwm": pwm,
                "key": str(action.get("key") or ""),
            },
        }

    def _dispatch_local_position(
        self,
        action: dict[str, object],
        *,
        link_manager: object | None,
    ) -> dict[str, object]:
        params = self._action_params(action)
        x = float(params["x"])
        y = float(params["y"])
        z = float(params["z"])
        frame = int(params.get("frame", LOCAL_NED))
        yaw = None if params.get("yaw") is None else float(params["yaw"])
        priority = int(action.get("priority", 4))

        # prefer semantic wrapper when frame matches (T4)
        if frame == LOCAL_NED:
            wrapper = getattr(link_manager, "goto_local_ned", None)
            if callable(wrapper):
                self._logger.info(
                    "action_lab dispatch goto_local_ned x_north_m=%s y_east_m=%s z_down_m=%s yaw_rad=%s priority=%s key=%s",
                    x, y, z, yaw, priority, action.get("key"),
                )
                wrapper(
                    x_north_m=x,
                    y_east_m=y,
                    z_down_m=z,
                    yaw_rad=yaw,
                    priority=priority,
                )
                detail: dict[str, object] = {
                    "action_type": "local_position",
                    "x": x,
                    "y": y,
                    "z": z,
                    "frame": frame,
                    "key": str(action.get("key") or ""),
                }
                if yaw is not None:
                    detail["yaw"] = yaw
                return {"status": "sent", "detail": detail}

        # fallback: original local_position
        sender = getattr(link_manager, "local_position", None)
        if not callable(sender):
            return {"status": "skipped", "reason": "local_position_dispatch_not_available"}
        if yaw is not None and not self._callable_accepts_keyword(sender, "yaw"):
            return {"status": "skipped", "reason": "local_position_yaw_not_supported"}
        self._logger.info(
            "action_lab dispatch local_position x=%s y=%s z=%s frame=%s yaw=%s priority=%s key=%s",
            x,
            y,
            z,
            frame,
            yaw,
            priority,
            action.get("key"),
        )
        sender(x, y, z, frame, yaw=yaw, priority=priority)
        detail: dict[str, object] = {
            "action_type": "local_position",
            "x": x,
            "y": y,
            "z": z,
            "frame": frame,
            "key": str(action.get("key") or ""),
        }
        if yaw is not None:
            detail["yaw"] = yaw
        return {"status": "sent", "detail": detail}

    def _dispatch_flight_command(
        self,
        action: dict[str, object],
        *,
        link_manager: object | None,
    ) -> dict[str, object]:
        command = self._action_params(action)
        valid = bool(command.get("valid", False))
        active = bool(command.get("active", False))
        vx = float(command.get("vx_cmd", 0.0))
        vy = float(command.get("vy_cmd", 0.0))
        vz = float(command.get("vz_cmd", 0.0))
        yaw_rate = float(command.get("yaw_rate_cmd", 0.0))
        priority = int(action.get("priority", command.get("priority", 5)))
        send_vx = vx if active else 0.0
        send_vy = vy if active else 0.0
        send_vz = vz if active else 0.0
        send_yaw_rate = yaw_rate if active else 0.0
        detail = {
            "action_type": "flight_command",
            "vx_cmd": send_vx,
            "vy_cmd": send_vy,
            "vz_cmd": send_vz,
            "yaw_rate_cmd": send_yaw_rate,
            "priority": priority,
            "key": str(action.get("key") or ""),
            "active": active,
            "valid": valid,
            "enable_body": bool(command.get("enable_body", False)),
            "enable_approach": bool(command.get("enable_approach", False)),
        }
        if not valid:
            return {
                "status": "skipped",
                "reason": "flight_command_inactive",
                "detail": detail,
            }

        frame = BODY_NED
        # prefer semantic wrapper (T4)
        wrapper = getattr(link_manager, "send_body_velocity", None)
        if callable(wrapper):
            self._logger.info(
                "action_lab dispatch send_body_velocity vx_forward_mps=%.3f vy_right_mps=%.3f vz_down_mps=%.3f key=%s active=%s",
                send_vx, send_vy, send_vz, action.get("key"), active,
            )
            wrapper(
                vx_forward_mps=send_vx,
                vy_right_mps=send_vy,
                vz_down_mps=send_vz,
            )
            detail["frame"] = frame
            return {"status": "sent", "detail": detail}

        # fallback: original send_velocity_command
        sender = getattr(link_manager, "send_velocity_command", None) if link_manager is not None else None
        if not callable(sender):
            return {
                "status": "skipped",
                "reason": "flight_command_dispatch_not_available",
                "detail": detail,
            }
        self._logger.info(
            "action_lab dispatch flight_command vx=%.3f vy=%.3f vz=%.3f yaw_rate=%.3f frame=BODY_NED priority=%s key=%s active=%s",
            send_vx,
            send_vy,
            send_vz,
            send_yaw_rate,
            priority,
            action.get("key"),
            active,
        )
        sender(send_vx, send_vy, send_vz, frame=frame)
        detail["frame"] = frame
        return {"status": "sent", "detail": detail}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _callable_accepts_keyword(func, name: str) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return True
        return any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            or parameter.name == name
            for parameter in signature.parameters.values()
        )

    # ------------------------------------------------------------------
    # payload — builds the action_lab status payload dict
    # ------------------------------------------------------------------

    def payload(
        self,
        *,
        status: dict[str, object],
        action_name: str | None,
        send_commands: bool,
    ) -> dict[str, object]:
        requested = bool(self.send_actions)
        effective, note = self.gate(
            send_commands=send_commands,
            action_name=action_name,
        )
        return {
            "send_actions": requested,
            "requested_send_actions": requested,
            "send_actions_requested": requested,
            "send_actions_effective": bool(effective),
            "dry_run_only": not bool(effective),
            "note": note,
            "dispatch": dict(self.last_dispatch),
            "last_servo_command": self.last_servo_command,
            "status": status,
        }

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def empty_dispatch() -> dict[str, list[dict[str, object]]]:
        return {"sent": [], "skipped": [], "errors": []}

    def reset_keys(self) -> None:
        self.dispatched_keys.clear()
        self.last_dispatch = self.empty_dispatch()
        self.last_servo_command = None
