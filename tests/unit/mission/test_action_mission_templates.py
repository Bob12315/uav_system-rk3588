from __future__ import annotations

import json
from pathlib import Path

from missions.engine import MissionActionStep
from missions.common.actions.action_lab import create_action_lab_registry
from scripts.validate_action_missions import DEFAULT_TEMPLATE_PATHS, validate_templates


ROOT = Path(__file__).parents[3]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_only_three_formal_v2_templates_are_shipped() -> None:
    paths = sorted((ROOT / "config/action_missions").glob("*.json"))
    assert [path.name for path in paths] == [
        "drop_two_targets_v2.json", "recon_gps_v2.json", "rescue_2026_full_auto_v2.json",
    ]
    assert all(_load(path)["version"] == 2 for path in paths)


def test_formal_templates_validate_and_actions_are_registered() -> None:
    assert len(validate_templates(DEFAULT_TEMPLATE_PATHS)) == 3
    registered = set(create_action_lab_registry().list())
    for path in DEFAULT_TEMPLATE_PATHS:
        for step in _load(path)["steps"]:
            assert step["name"] in registered
            MissionActionStep(step["name"], step["params"], save_as=step.get("save_as"),
                              label=step.get("label"), on_failed=step.get("on_failed"))


def test_drop_flow_is_explicit_and_preserves_payload_order_and_stop_boundary() -> None:
    steps = _load(ROOT / "config/action_missions/drop_two_targets_v2.json")["steps"]
    names = [step["name"] for step in steps]
    assert "gps_multi_view_localize" not in names
    assert "gps_drop_sequence" not in names
    assert names.count("gps_capture_view") == 4
    assert names.count("gps_target_lock") == 2
    assert names.count("align_descend") == 2
    releases = [step for step in steps if step["name"] == "payload_release"]
    assert [step["params"]["payload_id"] for step in releases] == ["payload_1", "payload_2"]
    for release in releases:
        index = steps.index(release)
        assert steps[index - 1]["name"] == "align_descend"
        assert steps[index + 1]["name"] == "goto_waypoint"


def test_recon_flow_uses_stationary_capture_and_pure_ranking() -> None:
    steps = _load(ROOT / "config/action_missions/recon_gps_v2.json")["steps"]
    names = [step["name"] for step in steps]
    assert "gps_recon_area_scan" not in names
    assert names.count("recon_score_view") == 2
    assert names.count("recon_rank_views") == 1
    rank = next(step for step in steps if step["name"] == "recon_rank_views")
    assert rank["params"]["views"] == ["$recon_scan_view_2", "$recon_scan_view_4"]


def test_full_flow_replaces_visual_land_composite_with_atomic_steps() -> None:
    steps = _load(ROOT / "config/action_missions/rescue_2026_full_auto_v2.json")["steps"]
    names = [step["name"] for step in steps]
    assert "visual_land" not in names
    assert steps[-3]["label"] == "final_land_lock_h"
    assert steps[-2]["label"] == "final_land_align"
    assert steps[-1]["name"] == "land"
