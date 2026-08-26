from __future__ import annotations

import json
from pathlib import Path

from missions.common.actions.action_lab import create_action_lab_registry


ROOT = Path(__file__).parents[2]
FORMAL_TEMPLATES = tuple((ROOT / "config/action_missions").glob("*.json"))
RETIRED_COMPOSITES = {
    "drop_sequence", "recon_sequence", "gps_drop_sequence", "gps_recon_sequence",
    "gps_multi_view_localize", "gps_recon_area_scan", "multi_view_localize",
    "recon_scan", "survey_area", "recon_inspect_target", "recon_descend_observe",
    "visual_land",
}
RETIRED_RECON_ACTIONS = {
    "select_recon_targets", "build_recon_report",
}


def test_formal_templates_are_explicit_atomic_subflows() -> None:
    for path in FORMAL_TEMPLATES:
        names = {step["name"] for step in json.loads(path.read_text())["steps"]}
        assert names.isdisjoint(RETIRED_COMPOSITES), path


def test_runtime_registry_does_not_publish_composite_actions() -> None:
    names = set(create_action_lab_registry().list())
    assert names.isdisjoint(RETIRED_COMPOSITES)
    assert names.isdisjoint(RETIRED_RECON_ACTIONS)


def test_production_actions_do_not_construct_child_actions() -> None:
    action_dir = ROOT / "missions/common/actions"
    source = "\n".join(path.read_text() for path in action_dir.glob("*.py"))
    for retired in RETIRED_COMPOSITES:
        assert f'"{retired}"' not in source
    assert "Action()" not in source


def test_align_descend_is_a_self_contained_action() -> None:
    path = ROOT / "missions/common/actions/align_descend.py"
    source = path.read_text()
    assert len(source.splitlines()) < 350
    assert "guidance.align_descend" not in source
    assert "missions.common.lifecycle.align_descend" not in source
    assert not (ROOT / "guidance/align_descend.py").exists()
