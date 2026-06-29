from missions.common.actions.recon_inspect_targets import ReconInspectTargetsAction
from missions.common.actions.result import ActionResult


class _DoneChild:
    def __init__(self, reason="ok", height=2.0):
        self.reason, self.height = reason, height
    def update(self, context):
        return ActionResult(done=True, reason=self.reason, detail={"height_m": self.height})
    def stop(self):
        pass


def _action(targets, capture_updates=1):
    action = ReconInspectTargetsAction()
    action.start({"targets": targets, "capture_sign": {"capture_updates": capture_updates,
        "min_sign_confidence": 0.35, "sign_class_names": ["yiran"]},
        "align_descend": {"finish_altitude_m": 2.0, "config": {"min_altitude_m": 1.8,
        "payload_offset_enabled": False}}})
    return action


def _force_to_capture(action):
    action._start_target()
    action.child = _DoneChild("waypoint_reached")
    action.update({})
    action.child = _DoneChild("target_locked")
    action.update({})
    action.child = _DoneChild("finish_altitude_reached")
    action.update({})


def test_capture_detected_and_no_sign_for_fewer_than_five():
    action = _action([{"id": "a", "class_name": "bucket", "local_x": 0, "local_y": 5},
                      {"id": "b", "class_name": "bucket", "local_x": 1, "local_y": 5}])
    _force_to_capture(action)
    action.update({"scene": {"detections": [{"class_name": "yiran", "confidence": 0.86, "track_id": 12}]}})
    action.current_target_index += 1
    action.state = "init"
    _force_to_capture(action)
    result = action.update({"scene": {"detections": []}})
    result = action.update({})
    assert result.done
    assert result.detail["detected_sign_count"] == 1
    assert result.detail["no_sign_count"] == 1
    assert {item["status"] for item in result.detail["recon_report"]} == {"detected", "no_sign"}


def test_goto_failure_continues_to_next_target():
    action = _action([{"local_x": 0, "local_y": 5}, {"local_x": 1, "local_y": 5}])
    action._start_target()
    action.child = type("Failed", (), {"update": lambda self, ctx: ActionResult(failed=True, reason="goto_timeout", detail={}), "stop": lambda self: None})()
    action.update({})
    assert action.state == "next_target"
    assert action.recon_report[0]["status"] == "goto_failed"


def test_align_configuration_forces_no_payload_offset_and_two_meter_finish():
    action = _action([{"local_x": 0, "local_y": 5}])
    action._start_target()
    action.state = "target_lock"
    action._advance_child_stage()
    assert action.child.finish_altitude_m == 2.0
    assert action.child.config.min_altitude_m == 1.8
    assert action.child.config.payload_offset_enabled is False


def test_empty_targets_fails():
    result = _action([]).update({})
    assert result.failed and result.reason == "no_recon_targets"


def test_five_targets_three_signs_two_no_sign_and_complete_report():
    targets = [{"id": f"b{i}", "class_name": "bucket", "local_x": i, "local_y": 5,
                "rank": i + 1} for i in range(5)]
    action = _action(targets)
    for index in range(5):
        if index:
            action.current_target_index = index
            action.state = "init"
        _force_to_capture(action)
        detections = ([{"class_name": "yiran", "confidence": 0.8 + index / 100,
                        "bbox": [1, 2, 3, 4], "track_id": index}]
                      if index < 3 else [])
        action.update({"scene": {"detections": detections}})
    action.current_target_index = 5
    action.state = "done"
    result = action.update({})
    assert result.done
    assert result.detail["detected_sign_count"] == 3
    assert result.detail["no_sign_count"] == 2
    assert result.detail["failed_count"] == 0
    required = {"target_id", "rank", "class_name", "local_x", "local_y", "field_x",
                "field_y", "status", "sign_class", "confidence", "bbox", "track_id",
                "goto_reason", "lock_reason", "align_reason", "height_m"}
    assert all(required <= item.keys() for item in result.detail["recon_report"])


def test_align_failure_is_recorded_and_continues():
    action = _action([{"local_x": 0, "local_y": 5}, {"local_x": 1, "local_y": 5}])
    action._start_target()
    action.state = "align_descend"
    action.child = type("Failed", (), {"update": lambda self, ctx: ActionResult(
        failed=True, reason="align_timeout", detail={"height_m": 2.4}), "stop": lambda self: None})()
    result = action.update({})
    assert not result.failed
    assert result.actions == []
    assert action.recon_report[0]["status"] == "align_failed"
    assert action.recon_report[0]["height_m"] == 2.4
