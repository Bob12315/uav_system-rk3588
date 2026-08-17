from __future__ import annotations

import json

from contracts.action import ActionResult
from contracts.state import RuntimeSnapshot


def test_contract_snapshots_are_json_serializable() -> None:
    json.dumps(RuntimeSnapshot().to_dict())
    json.dumps(ActionResult(done=True).to_dict())


def test_action_result_compatibility_and_effect_view_share_values() -> None:
    result = ActionResult(effects=ActionResult.typed([{"action_type": "yolo_lock_target", "params": {"track_id": 1}}]))
    assert result.effects[0].action_type == result.actions[0]["action_type"]
    assert result.to_dict()["actions"][0]["action_type"] == "yolo_lock_target"
