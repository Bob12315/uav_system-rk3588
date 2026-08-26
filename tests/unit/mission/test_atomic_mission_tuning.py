from __future__ import annotations

import json
from pathlib import Path

from missions.common.actions.action_lab import action_definitions, action_lab_specs


ROOT = Path(__file__).parents[3]


def _steps(name: str) -> list[dict]:
    return json.loads((ROOT / f"config/action_missions/{name}").read_text())["steps"]


def _align(name: str) -> list[dict]:
    return [step["params"] for step in _steps(name) if step["name"] == "align_descend" and step["label"].startswith("drop_")]


def test_atomic_drop_tuning_and_payload_offsets_are_preserved() -> None:
    generic = _align("drop_two_targets.json")
    rescue = _align("rescue_2026_full_auto.json")
    assert len(generic) == len(rescue) == 2
    assert [item["config"]["payload_forward_m"] for item in generic] == [-0.06, 0.06]
    assert [item["config"]["payload_forward_m"] for item in rescue] == [-0.06, 0.06]
    assert {item["max_updates"] for item in generic} == {35}
    assert {item["max_updates"] for item in rescue} == {150}
    for item in rescue:
        config = item["config"]
        assert config["descend_speed_mps"] == 0.30
        assert config["slow_descend_speed_mps"] == 0.14
        assert (config["max_ex_cam"], config["max_ey_cam"]) == (0.16, 0.16)
        assert (config["slow_descend_max_ex_cam"], config["slow_descend_max_ey_cam"]) == (0.35, 0.35)
        assert (config["deadband_ex_cam"], config["deadband_ey_cam"]) == (0.04, 0.04)
        assert (config["fov_x_deg"], config["fov_y_deg"]) == (85, 69)
        assert item["finish_alignment_timeout_s"] == 1.0


def test_capture_camera_and_recon_routes_are_preserved() -> None:
    drop = _steps("drop_two_targets.json")
    cameras = [step["params"]["camera"] for step in drop if step["name"] == "gps_capture_view"]
    assert len(cameras) == 4
    assert all((camera["fov_x_deg"], camera["fov_y_deg"]) == (68.15, 54.3) for camera in cameras)
    recon = _steps("recon_gps.json")
    points = [(step["params"]["x"], step["params"]["y"], step["params"]["altitude_m"])
              for step in recon if step.get("label", "").startswith("recon_scan_goto_")]
    assert points == [(-3, 56, 3), (3, 56, 3), (3, 58, 3), (-3, 58, 3)]


def test_profile_contains_no_mission_template_copies() -> None:
    profile_dir = ROOT / "config/profiles/rk3588-sitl/action_missions"
    assert not profile_dir.exists() or list(profile_dir.glob("*.json")) == []


def test_action_lab_public_defaults_are_owned_by_definitions() -> None:
    assert action_lab_specs() == [definition.web_spec() for definition in action_definitions()]
