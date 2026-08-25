#!/usr/bin/env python3
"""P0 acceptance over the formal Action dispatch chain against live SITL."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from execution.dispatcher import ActionDispatcher
from execution.authorization import RunAuthorization
from contracts.effects import effect_from_request
from telemetry_link.config import DEFAULT_CONFIG_PATH, load_config_file
from contracts.frames import GLOBAL_RELATIVE_ALT_INT
from telemetry_link.link_manager import LinkManager


REPORT = ROOT / "runtime" / "sitl" / "p0" / "acceptance.json"


def wait_for(label: str, predicate, timeout_s: float = 30.0):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.1)
    raise RuntimeError(f"timeout waiting for {label}")


def main() -> int:
    cfg = load_config_file(DEFAULT_CONFIG_PATH)
    cfg.data_source = "sitl"
    cfg.active_source = "sitl"
    cfg.request_message_intervals = True
    manager = LinkManager(cfg)
    dispatcher = ActionDispatcher()
    events: list[dict[str, object]] = []

    def state():
        return manager.get_latest_drone_state()

    def record(name: str, **detail: object) -> None:
        events.append({"time": time.time(), "name": name, **detail})

    def dispatch(action_name: str, action_type: str, params: dict[str, object], key: str):
        result = dispatcher.dispatch_effects(
            [effect_from_request({
                "action_type": action_type,
                "params": params,
                "key": key,
                "once": action_type not in {"flight_command", "body_velocity"},
            })],
            action_name=action_name,
            send_commands=True,
            link_manager=manager,
        )
        if result["errors"] or result["skipped"] or len(result["sent"]) != 1:
            raise RuntimeError(f"{action_name}/{action_type} rejected: {result}")
        decision = result["sent"][0]["safety_decision"]
        record(action_type, reason=decision["reason_code"], status=decision["status"])
        return result

    try:
        manager.start_background()
        wait_for("fresh SITL telemetry", lambda: state() if state().connected and not state().stale else None, 40.0)
        record("telemetry_connected")

        dispatcher.set_authorization(RunAuthorization.create(
            operator="p0-sitl-validator",
            scope_type="mission",
            scope_name="p0_acceptance",
            target_source="sitl",
            allowed_actions={"takeoff", "goto_waypoint", "change_speed", "align_descend", "land"},
        ))

        dispatch("takeoff", "set_mode", {"mode": "GUIDED"}, "p0-mode")
        wait_for("GUIDED", lambda: state() if state().mode == "GUIDED" else None)
        wait_for(
            "EKF/home readiness",
            lambda: state()
            if state().local_position_valid and state().global_position_valid
            else None,
            40.0,
        )
        # ArduPilot may publish valid positions one scheduler cycle before its
        # AHRS home flag becomes armable. This delay is SITL-only and sends no
        # command.
        time.sleep(2.0)
        dispatch("takeoff", "arm", {}, "p0-arm")
        wait_for("armed", lambda: state() if state().armed else None, 40.0)
        dispatch("takeoff", "takeoff", {"altitude_m": 2.0}, "p0-takeoff")
        wait_for("takeoff altitude", lambda: state() if state().relative_altitude >= 1.6 else None, 45.0)

        dispatch("change_speed", "change_speed", {"speed_mps": 0.8, "speed_type": 1}, "p0-speed")
        current = wait_for("global position", lambda: state() if state().global_position_valid else None)
        target_lat = current.lat + 1.0 / 111_111.0
        dispatch(
            "goto_waypoint",
            "global_goto",
            {
                "lat": target_lat,
                "lon": current.lon,
                "alt": current.relative_altitude,
                "frame": GLOBAL_RELATIVE_ALT_INT,
                "yaw": current.yaw,
            },
            "p0-goto",
        )
        wait_for("global goto", lambda: state() if abs(state().lat - target_lat) < 0.000006 else None, 30.0)

        dispatch(
            "align_descend",
            "flight_command",
            {
                "valid": True,
                "active": True,
                "vx_cmd": 0.15,
                "vy_cmd": 0.0,
                "vz_cmd": 0.0,
                "yaw_rate_cmd": 0.0,
            },
            "p0-body",
        )
        wait_for(
            "BODY_NED deadman stop",
            lambda: next(
                (
                    item for item in dispatcher.safety_decisions
                    if item.get("reason_code") == "continuous_deadman_expired"
                ),
                None,
            ),
            3.0,
        )
        record("continuous_deadman_stop")

        dispatch("land", "land", {}, "p0-land")
        wait_for("land/disarm", lambda: state() if not state().armed else None, 60.0)
        record("landed")

        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps(
                {
                    "ok": True,
                    "source": "sitl",
                    "formal_chain": "ActionDispatcher -> ActionSafetyPipeline -> LinkManager -> telemetry_link",
                    "run_id": dispatcher.authorization.run_id if dispatcher.authorization else None,
                    "events": events,
                    "safety_decisions": dispatcher.safety_decisions,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"P0 SITL acceptance passed; report={REPORT}")
        return 0
    except Exception as exc:
        manager.stop_body_velocity_and_clear()
        manager.land(priority=0)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps({"ok": False, "error": str(exc), "events": events}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        dispatcher.safety_pipeline.continuous_guard.close()
        manager.stop()


if __name__ == "__main__":
    raise SystemExit(main())
