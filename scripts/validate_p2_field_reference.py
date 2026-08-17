#!/usr/bin/env python3
"""P2 gate: v3 runtime Field Reference and legacy-path retirement."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import build_arg_parser, load_app_config  # noqa: E402
from missions.engine import MissionActionStep  # noqa: E402
from application.runner import SystemRunner  # noqa: E402


def main() -> None:
    profiles = sorted((ROOT / "config" / "field_profiles").glob("*.json"))
    if [path.name for path in profiles] != ["competition_runtime_v3.json"]:
        raise SystemExit("only competition_runtime_v3.json may be shipped")
    forbidden = ("app/mission_runner.py", "app/stage_registry.py")
    if any((ROOT / path).exists() for path in forbidden):
        raise SystemExit("legacy mission/stage files remain")
    args = build_arg_parser().parse_args(["--no-yolo-udp", "--no-ui"])
    runner = SystemRunner(load_app_config(args))
    controller = runner.field_service
    started = controller.start_competition_runtime_sampling(34.104189, 108.642674, started_at_s=1000.0)
    if started.get("ok") is not True:
        raise SystemExit(f"v3 sampling start failed: {started}")
    for index in range(48):
        controller.observe_runtime_profile_sampling({
            "global_position_valid": True, "last_global_position_time": 2000.0 + index,
            "lat": 34.103649, "lon": 108.642674, "gps_fix_type": 3,
            "satellites_visible": 12, "gps_eph": 1.0, "gps_epv": 1.0,
        }, observed_at_s=1000.0 + index * 0.26)
    status = controller.status()["field_reference"]
    if not status["is_ready_for_field_to_gps"]:
        raise SystemExit(f"invalid v3 field capability status: {status}")
    runner.configure_action_mission([MissionActionStep(
        name="goto_waypoint",
        params={"x": 0.0, "y": 5.0, "altitude_m": 3.0,
                "waypoint_mode": "field", "target_frame": "global",
                "yaw_mode": "field_heading"},
    )])
    mission = runner.action_mission_start(
        authorize=True,
        operator="p2-validator",
        target_source="sitl",
    )
    if mission.get("running") is not True:
        raise SystemExit(f"v3 Field Reference Action Mission preflight failed: {mission}")
    runner.action_mission_stop()
    print("P2 v3 runtime Field Reference and legacy retirement validated")


if __name__ == "__main__":
    main()
