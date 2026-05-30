from __future__ import annotations

import json
from types import SimpleNamespace

from app.app_config import BlackboxConfig
from app.blackbox_recorder import BlackboxRecorder
from missions.common.control.types import FlightCommand, MissionStageInput
from fusion.models import FusedState, PerceptionTarget
from telemetry_link.models import DroneState, GimbalState, LinkStatus


def _config(output_dir: str) -> BlackboxConfig:
    return BlackboxConfig(
        enabled=True,
        output_dir=output_dir,
        sample_hz=0.0,
        flush_every=1,
        rotate_mb=100.0,
        keep_files=20,
        include_perception=True,
        include_drone=True,
        include_gimbal=True,
        include_fused=True,
        include_commands=True,
        include_events=True,
    )


def test_blackbox_recorder_writes_control_cycle_jsonl(tmp_path) -> None:
    recorder = BlackboxRecorder(_config(str(tmp_path)))
    recorder.start()

    recorder.record(
        now=100.0,
        dt=0.05,
        perception=PerceptionTarget(
            timestamp=99.9,
            target_valid=True,
            tracking_state="locked",
            track_id=7,
            confidence=0.8,
            ex=-0.12,
            ey=0.04,
            target_size=0.03,
        ),
        drone=DroneState(
            connected=True,
            armed=True,
            mode="GUIDED",
            control_allowed=True,
            roll=0.1,
            pitch=0.2,
            yaw=0.3,
            vx=1.0,
            vy=2.0,
            vz=-0.5,
        ),
        gimbal=GimbalState(gimbal_valid=True, yaw=3.0, pitch=-20.0, roll=0.0),
        link=LinkStatus(connected=True, target_system=1, target_component=1),
        fused=FusedState(target_valid=True, ex_cam=-0.12, ey_cam=0.04, state_valid=True),
        inputs=MissionStageInput(dt=0.05, target_valid=True, control_allowed=True),
        mission=SimpleNamespace(active_mode="APPROACH_TRACK", hold_reason=""),
        health=SimpleNamespace(hold_reason="ok"),
        mode_status=SimpleNamespace(mode_name="APPROACH_TRACK", hold_reason=""),
        raw_command=FlightCommand(vx_cmd=0.4, gimbal_yaw_rate_cmd=-0.1, valid=True, active=True),
        shaped_command=FlightCommand(vx_cmd=0.3, gimbal_yaw_rate_cmd=-0.08, enable_gimbal=True, valid=True, active=True),
        send_commands=True,
    )
    recorder.close()

    assert recorder.path is not None
    lines = recorder.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["runtime"]["mission"] == "APPROACH_TRACK"
    assert payload["perception"]["track_id"] == 7
    assert payload["drone"]["mode"] == "GUIDED"
    assert payload["gimbal"]["gimbal_valid"] is True
    assert payload["command_raw"]["vx"] == 0.4
    assert payload["command_shaped"]["gimbal_yaw_rate"] == -0.08
    assert payload["events"] == []
