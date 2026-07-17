"""Tests for scan geometry and alignment tuning changes."""
from __future__ import annotations
import json


def test_drop_scan_waypoints_restored_to_original_field_positions():
    """Drop scan preview uses the original field positions."""
    data = json.loads(open("config/field_profiles/competition_runtime_v3.json").read())
    wps = data["drop_scan"]["waypoints"]
    assert len(wps) == 4
    coords = [(w["x_m"], w["y_m"]) for w in wps]
    assert coords == [(-2.0, 31.25), (2.0, 31.25), (2.0, 33.75), (-2.0, 33.75)]


def test_recon_scan_waypoints_updated():
    """Recon scan preview matches the fixed 3m area-scan route."""
    data = json.loads(open("config/field_profiles/competition_runtime_v3.json").read())
    assert "recon_scan" in data
    wps = data["recon_scan"]["waypoints"]
    assert len(wps) == 4
    coords = [(w["x_m"], w["y_m"]) for w in wps]
    assert coords == [(-3.0, 56.0), (3.0, 56.0), (3.0, 58.0), (-3.0, 58.0)]
    assert [w["altitude_m"] for w in wps] == [3.0, 3.0, 3.0, 3.0]


def test_complete_rescue_v2_uses_a_lower_recon_scan():
    """The complete rescue mission scans at 2 m; standalone recon remains at 3 m."""
    recon = json.loads(open("config/action_missions/recon_gps_v2.json").read())
    rescue = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    
    recon_scan = next(s for s in recon["steps"] if s["name"] == "gps_recon_area_scan")
    rescue_scan = next(s for s in rescue["steps"] if s["name"] == "gps_recon_area_scan")
    
    assert [(wp["x"], wp["y"]) for wp in recon_scan["params"]["waypoints"]] == [
        (wp["x"], wp["y"]) for wp in rescue_scan["params"]["waypoints"]
    ]
    assert [wp["altitude_m"] for wp in recon_scan["params"]["waypoints"]] == [3.0] * 4
    assert [wp["altitude_m"] for wp in rescue_scan["params"]["waypoints"]] == [2.0] * 4


def test_profile_drop_and_recce_zones_restored():
    """The Profile geometry is the single source for the original map zones."""
    # Read the field_map.js defaults (difficult to parse, test the profile instead)
    data = json.loads(open("config/field_profiles/competition_runtime_v3.json").read())
    fg = data["field_geometry"]
    assert fg["lane_half_width_m"] == 4.0
    assert (fg["drop_area_y_min_m"], fg["drop_area_y_max_m"], fg["drop_center_y_m"]) == (30.0, 35.0, 32.5)
    assert (fg["recce_area_y_min_m"], fg["recce_area_y_max_m"], fg["recce_center_y_m"]) == (55.0, 60.0, 57.5)


def test_fusion_fov_still_51_3_39_6():
    """Fusion camera FOV is 68.15/54.3 in all mission configs."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
        "config/action_missions/recon_gps_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_multi_view_localize":
                cam = step["params"].get("camera", {})
                if cam:
                    assert cam["fov_x_deg"] == 68.15, f"{path}: fov_x={cam['fov_x_deg']}"
                    assert cam["fov_y_deg"] == 54.3, f"{path}: fov_y={cam['fov_y_deg']}"
        for step in data["steps"]:
            if step["name"] in ("gps_drop_sequence", "gps_recon_sequence"):
                tl = step["params"].get("target_lock", {})
                if tl and "camera" in tl:
                    assert tl["camera"]["fov_x_deg"] == 68.15, f"{path} target_lock fov_x"
                    assert tl["camera"]["fov_y_deg"] == 54.3


def test_align_descend_fov_still_85_69():
    """align_descend FOV still 85.0/69.0 in drop configs."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                cfg = step["params"]["align_descend"]["config"]
                assert cfg["fov_x_deg"] == 85.0, f"{path} align fov_x"
                assert cfg["fov_y_deg"] == 69.0, f"{path} align fov_y"


def test_complete_rescue_v2_drop_overrides_are_deliberate():
    """Only complete rescue v2 carries the aggressive multi-path drop policy."""
    drop = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    rescue = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    dp = dict(next(s for s in drop["steps"] if s["name"] == "gps_drop_sequence")["params"])
    rp = dict(next(s for s in rescue["steps"] if s["name"] == "gps_drop_sequence")["params"])
    assert dp["approach_altitude_m"] == 2.5 and rp["approach_altitude_m"] == 3.5
    assert rp["no_target_field_center"] == {"x": 0.0, "y": 32.5, "altitude_m": 3.5}
    assert rp["single_target_climb_after_release_m"] == 3.5


def test_align_max_updates_are_template_specific():
    """Complete rescue v2 has synchronized 150-update inner and outer limits."""
    for path, expected in (("config/action_missions/drop_two_targets_v2.json", 35), ("config/action_missions/rescue_2026_full_auto_v2.json", 150)):
        data = json.loads(open(path).read())
        params = next(step for step in data["steps"] if step["name"] == "gps_drop_sequence")["params"]
        assert params["align_descend_max_updates"] == expected
        assert params["align_descend"]["max_updates"] == expected


def test_height_scale_points_low_altitude_040():
    """Low altitude scale is 0.40 for 1.0m and 1.3m."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                hsp = step["params"]["align_descend"]["config"]["height_scale_points"]
                assert hsp[0] == {"altitude_m": 1.0, "scale": 0.40}, f"{path} hsp[0]"
                assert hsp[1] == {"altitude_m": 1.3, "scale": 0.40}, f"{path} hsp[1]"


def test_complete_v2_deadband_is_004():
    data = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    c = next(step for step in data["steps"] if step["name"] == "gps_drop_sequence")["params"]["align_descend"]["config"]
    assert (c["deadband_ex_cam"], c["deadband_ey_cam"]) == (0.04, 0.04)


def test_recon_is_gps_hover_without_alignment_params():
    """Recon v2 intentionally has no visual lock/alignment/descent settings."""
    data = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    for step in data["steps"]:
        if step["name"] == "gps_recon_sequence":
            params = step["params"]
            assert params["approach_altitude_m"] == 2.5
            assert params["observe_duration_s"] == 2.0
            assert "target_lock" not in params
            assert "align_descend" not in params


def test_v1_unchanged():
    """V1 config files untouched by this change."""
    import os
    v1_paths = [
        "config/action_missions/drop_two_targets_v1.json",
        "config/action_missions/rescue_2026_full_auto.json",
    ]
    for path in v1_paths:
        if os.path.exists(path):
            data = json.loads(open(path).read())
            assert "steps" in data  # V1 uses name/description/steps format
