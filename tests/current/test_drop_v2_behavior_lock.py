"""Regression lock for the GPS drop V2 public behaviour.

The detailed phase/failure matrix remains in ``test_feature3_gps_drop_control``;
this file makes the V2 template and the externally visible safety contract an
explicit baseline for later recon-flow reuse.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DROP_V2 = ROOT / "config/action_missions/drop_two_targets_v2.json"


def test_drop_v2_sequence_contract_is_locked() -> None:
    data = json.loads(DROP_V2.read_text(encoding="utf-8"))
    steps = data["steps"]
    assert [step["name"] for step in steps] == [
        "takeoff", "gps_multi_view_localize", "select_drop_targets",
        "gps_drop_sequence", "goto_waypoint", "land",
    ]
    drop = steps[3]
    assert drop["save_as"] == "drop_sequence"
    assert drop["params"]["climb_after_drop_m"] == 2.5
    assert drop["params"]["climb_tolerance_z_m"] == 0.1
    assert len(drop["params"]["payloads"]) == 2
    assert drop["params"]["align_descend"]["config"]["payload_offset_enabled"] is True


def test_drop_v2_failure_and_stop_contract_is_covered_by_phase_suite() -> None:
    """Keep the stable failure names and stop primitives discoverable."""
    text = (ROOT / "missions/common/actions/gps_drop_sequence.py").read_text(encoding="utf-8")
    for required in (
        "goto_timeout", "no_lockable_drop_targets", "align_descend_timeout",
        "payload_release_failed", "climb_goto_failed", "climb_timeout",
        "_zero_velocity_command", "_clear_continuous_command",
    ):
        assert required in text
    assert "test_climb_altitude_gate_wins_timeout_boundary" in (
        ROOT / "tests/current/test_feature3_gps_drop_control.py"
    ).read_text(encoding="utf-8")
