"""Tests for drop descent and localization tuning changes."""
from __future__ import annotations
import json


def test_descend_speed_024():
    """Fast descend speed is 0.24."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                c = step["params"]["align_descend"]["config"]
                assert c["descend_speed_mps"] == 0.24, f"{path}: {c['descend_speed_mps']}"


def test_slow_descend_and_complete_v2_edge_descend_speeds():
    """Complete rescue v2 alone lowers the unaligned descent band."""
    drop = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    rescue = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    drop_cfg = next(s for s in drop["steps"] if s["name"] == "gps_drop_sequence")["params"]["align_descend"]["config"]
    rescue_cfg = next(s for s in rescue["steps"] if s["name"] == "gps_drop_sequence")["params"]["align_descend"]["config"]
    assert drop_cfg["slow_descend_speed_mps"] == rescue_cfg["slow_descend_speed_mps"] == 0.18
    assert drop_cfg["unaligned_descend_speed_mps"] == 0.08
    assert rescue_cfg["unaligned_descend_speed_mps"] == 0.06


def test_fast_window_028():
    """Fast descent window is ex/ey 0.28."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                c = step["params"]["align_descend"]["config"]
                assert c["max_ex_cam"] == 0.28, f"{path} max_ex"
                assert c["max_ey_cam"] == 0.28, f"{path} max_ey"


def test_slow_window_unchanged():
    """Slow descent window still 0.55."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                c = step["params"]["align_descend"]["config"]
                assert c["slow_descend_max_ex_cam"] == 0.55
                assert c["slow_descend_max_ey_cam"] == 0.55


def test_finish_window_unchanged():
    """Final alignment window still 0.35."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                a = step["params"]["align_descend"]
                assert a["finish_alignment_max_ex_cam"] == 0.35
                assert a["finish_alignment_max_ey_cam"] == 0.35
                assert a["finish_alignment_hold_updates"] == 1


def test_low_scale_unchanged():
    """1.0m and 1.3m scale still 0.40."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                hsp = step["params"]["align_descend"]["config"]["height_scale_points"]
                assert hsp[0]["scale"] == 0.40
                assert hsp[1]["scale"] == 0.40


def test_high_scale_065():
    """2.4m, 3.5m, 4.5m scale is 0.65."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                hsp = step["params"]["align_descend"]["config"]["height_scale_points"]
                assert hsp[2]["scale"] == 0.65
                assert hsp[3]["scale"] == 0.65
                assert hsp[4]["scale"] == 0.65


def test_fusion_fov_68_54():
    """Fusion camera FOV is 68.15/54.3."""
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
                    assert cam["fov_x_deg"] == 68.15, f"{path} fusion fov_x"
                    assert cam["fov_y_deg"] == 54.3, f"{path} fusion fov_y"


def test_target_lock_fov_68_54():
    """GPS target_lock camera FOV is 68.15/54.3."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
        "config/action_missions/recon_gps_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] in ("gps_drop_sequence", "gps_recon_sequence"):
                tl = step["params"].get("target_lock", {})
                if tl and "camera" in tl:
                    assert tl["camera"]["fov_x_deg"] == 68.15, f"{path} lock fov_x"
                    assert tl["camera"]["fov_y_deg"] == 54.3, f"{path} lock fov_y"


def test_align_descend_fov_still_85_69():
    """align_descend FOV still 85.0/69.0."""
    paths = [
        "config/action_missions/drop_two_targets_v2.json",
        "config/action_missions/rescue_2026_full_auto_v2.json",
    ]
    for path in paths:
        data = json.loads(open(path).read())
        for step in data["steps"]:
            if step["name"] == "gps_drop_sequence":
                c = step["params"]["align_descend"]["config"]
                assert c["fov_x_deg"] == 85.0, f"{path} align fov_x"
                assert c["fov_y_deg"] == 69.0, f"{path} align fov_y"


def test_complete_rescue_v2_drop_overrides_are_deliberate():
    """Rescue v2 no longer shares the generic template's conservative values."""
    drop = json.loads(open("config/action_missions/drop_two_targets_v2.json").read())
    rescue = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())
    dp = dict(next(s for s in drop["steps"] if s["name"] == "gps_drop_sequence")["params"])
    rp = dict(next(s for s in rescue["steps"] if s["name"] == "gps_drop_sequence")["params"])
    assert dp["approach_altitude_m"] == 2.5 and rp["approach_altitude_m"] == 3.5
    assert dp["align_descend_max_updates"] == 35 and rp["align_descend_max_updates"] == 150
    assert rp["single_target_climb_after_release_m"] == 3.5


def test_recon_fov_consistent():
    """Recon v2 and rescue v2 recon scan/lock FOV consistent."""
    recon = json.loads(open("config/action_missions/recon_gps_v2.json").read())
    rescue = json.loads(open("config/action_missions/rescue_2026_full_auto_v2.json").read())

    def get_fovs(data):
        fusion = None
        lock = None
        for s in data["steps"]:
            if s["name"] == "gps_multi_view_localize":
                cam = s["params"].get("camera", {})
                if cam:
                    fusion = cam["fov_x_deg"], cam["fov_y_deg"]
            if s["name"] == "gps_recon_sequence":
                tl = s["params"].get("target_lock", {})
                if tl and "camera" in tl:
                    lock = tl["camera"]["fov_x_deg"], tl["camera"]["fov_y_deg"]
        return fusion, lock

    rf, rl = get_fovs(recon)
    sf, sl = get_fovs(rescue)
    # Recon v2 may use defaults (no camera key); rescue v2 has explicit FOV
    if rf is not None and sf is not None:
        assert rf == sf
    if rl is not None and sl is not None:
        assert rl == sl


def test_sitl_identical_to_base():
    """SITL profile configs byte-identical to base configs."""
    pairs = [
        ("config/action_missions/drop_two_targets_v2.json", "config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json"),
        ("config/action_missions/rescue_2026_full_auto_v2.json", "config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json"),
        ("config/action_missions/recon_gps_v2.json", "config/profiles/rk3588-sitl/action_missions/recon_gps_v2.json"),
    ]
    for base_path, sitl_path in pairs:
        base = open(base_path).read()
        sitl = open(sitl_path).read()
        assert base == sitl, f"{base_path} != {sitl_path}"


def test_v1_unchanged():
    """V1 config files can still be loaded."""
    import os
    for path in ["config/action_missions/drop_two_targets_v1.json", "config/action_missions/rescue_2026_full_auto.json"]:
        if os.path.exists(path):
            json.loads(open(path).read())
