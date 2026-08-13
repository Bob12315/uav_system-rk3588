# Archived composite-template tuning assertions; atomic equivalents replace them.
"""Config consistency tests for competition parameter changes."""
from __future__ import annotations
import json


def test_return_home_altitudes_match_each_mission_profile() -> None:
    expected_altitudes = {
        "config/action_missions/drop_two_targets_v2.json": 3.5,
        "config/action_missions/rescue_2026_full_auto_v2.json": 4.0,
        "config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json": 3.5,
        "config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json": 4.0,
    }
    for path, expected_altitude_m in expected_altitudes.items():
        data = json.loads(open(path).read())
        rth = next(s for s in data["steps"] if s["label"] == "return_home_gps")
        assert rth["params"]["altitude_m"] == expected_altitude_m


def test_complete_rescue_v2_has_its_intentional_aggressive_drop_overrides() -> None:
    """The standalone drop template stays unchanged; complete rescue v2 is tuned separately."""
    drop = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    rescue = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    drop_seq = next(s for s in drop["steps"] if s["name"] == "gps_drop_sequence")
    rescue_seq = next(s for s in rescue["steps"] if s["name"] == "gps_drop_sequence")
    dp = dict(drop_seq["params"])
    rp = dict(rescue_seq["params"])
    assert dp["approach_altitude_m"] == 2.5
    assert rp["approach_altitude_m"] == 3.5
    assert rp["finish_altitude_m"] == 1.2
    assert rp["single_target_climb_after_release_m"] == 3.5
    assert rp["no_target_strategy"] == "field_center_direct_dual_release"
    assert rp["align_descend_max_updates"] == rp["align_descend"]["max_updates"] == 150
    assert rp["align_descend"]["config"]["unaligned_descend_speed_mps"] == 0.0
    assert rp["align_descend"]["config"]["min_altitude_m"] == 1.2
    assert rp["align_descend"]["config"]["descent_speed_stages"] == [
        {"max_altitude_m": 2.4, "max_descend_speed_mps": 0.18},
        {"max_altitude_m": 3.2, "max_descend_speed_mps": 0.24},
        {"max_altitude_m": 3.5, "max_descend_speed_mps": 0.30},
    ]
    assert rp["target_lock"]["max_match_distance_m"] == 3.0
    assert "fallback_max_match_distance_m" not in rp["target_lock"]
    assert rp["target_lock_max_updates"] == 6
    assert rp["target_lock"]["min_confidence"] == 0.75
    assert rp["target_lock"]["try_next_target_on_failure"] is True
    assert rp["target_lock"]["direct_release_when_exhausted"] is True


def test_rescue_v2_base_and_sitl_identical() -> None:
    """Rescue base V2 and SITL profile V2 are byte-identical."""
    base = open("config/action_missions/rescue_2026_full_auto_v2.json").read()
    sitl = open("config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json").read()
    assert base == sitl


def test_complete_rescue_v2_scopes_ground_speed_changes() -> None:
    data = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    steps = data["steps"]
    labels = [step.get("label") for step in steps]
    expected = {
        "drop_speed_1mps": 1.0,
        "restore_transition_speed_2mps": 2.0,
        "recon_speed_1mps": 1.0,
        "restore_return_speed_2mps": 2.0,
    }
    for label, speed in expected.items():
        step = next(step for step in steps if step.get("label") == label)
        assert step["name"] == "change_speed"
        assert step["params"]["speed_mps"] == speed
        assert step["params"]["speed_type"] == "ground"

    assert labels.index("drop_speed_1mps") + 1 == labels.index("gps_drop_sequence")
    assert labels.index("gps_drop_sequence") + 1 == labels.index("restore_transition_speed_2mps")
    assert labels.index("recon_speed_1mps") + 1 == labels.index("goto_recon_entry_4m")
    assert labels.index("goto_recon_entry_4m") + 1 == labels.index("gps_recon_area_scan")
    assert labels.index("gps_recon_area_scan") + 1 == labels.index("restore_return_speed_2mps")
    assert next(step for step in steps if step.get("label") == "gps_drop_sequence")["on_failed"]["target"] == "restore_return_speed_2mps"


def test_action_lab_public_defaults_are_owned_by_action_definitions() -> None:
    from missions.common.actions.action_lab import action_definitions, action_lab_specs
    definitions = {item.name: item.default_params for item in action_definitions()}
    assert {item["name"]: item["default_params"] for item in action_lab_specs()} == definitions
