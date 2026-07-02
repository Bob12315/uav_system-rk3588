from missions.common.actions.recon_inspect_target import ReconInspectTargetAction
from missions.common.actions.result import ActionResult


class _Child:
    def __init__(self, *, done=True, failed=False, reason="ok", height=1.5):
        self.result = ActionResult(done=done, failed=failed, reason=reason, detail={"height_m": height})
    def update(self, context):
        return self.result
    def stop(self):
        pass


def _action(index=0, observe_updates=1, **params):
    action = ReconInspectTargetAction()
    action.start({"targets": [{"id": "target_0", "class_name": "bucket", "local_x": 0.3, "local_y": 5.1}],
                  "target_index": index, "observe": {"observe_time_s": observe_updates * 0.1,
                  "expected_dt_s": 0.1, "sign_class_names": ["yiran"]}, **params})
    return action


def _to_align(action):
    action._start_goto()
    action.child = _Child(reason="waypoint_reached")
    action.update({})
    action.child = _Child(reason="target_locked")
    action.update({})


def test_complete_flow_detects_best_sign_and_zeroes_first_observe_frame():
    action = _action()
    _to_align(action)
    action.child = _Child(reason="finish_altitude_reached")
    result = action.update({"scene": {"detections": [{"class_name": "yiran", "confidence": 0.86,
                            "bbox": [100, 120, 180, 210], "track_id": 12}]}})
    assert result.done and not result.failed
    assert result.detail["status"] == "detected"
    assert result.detail["sign_class"] == "yiran"
    zero_action = result.actions[0]
    assert zero_action["action_type"] == "flight_command"
    assert zero_action["params"]["frame"] == "BODY_NED"
    assert zero_action["once"] is False
    assert (zero_action["params"]["vx_cmd"], zero_action["params"]["vy_cmd"],
            zero_action["params"]["vz_cmd"]) == (0.0, 0.0, 0.0)


def test_missing_target_index_is_successful_skip():
    result = _action(index=3).update({})
    assert result.done and not result.failed
    assert result.reason == "skipped_missing_target"
    assert result.detail["status"] == "skipped_missing_target"


def test_observe_without_sign_is_normal_and_zeroes_every_update():
    action = _action(observe_updates=2)
    _to_align(action)
    action.child = _Child(reason="finish_altitude_reached")
    first = action.update({"scene": {"detections": []}})
    second = action.update({"scene": {"detections": []}})
    assert not first.done and second.done
    assert second.detail["status"] == "no_sign" and second.detail["confidence"] == 0.0
    for result in (first, second):
        action_envelope = result.actions[0]
        assert action_envelope["action_type"] == "flight_command"
        assert isinstance(action_envelope["params"], dict)
        command = action_envelope["params"]
        assert command["vx_cmd"] == command["vy_cmd"] == command["vz_cmd"] == 0.0
        assert action_envelope["once"] is False


def test_lock_failure_finishes_current_target_without_failing_mission():
    action = _action()
    action._start_goto()
    action.child = _Child(reason="waypoint_reached")
    action.update({})
    action.child = _Child(done=False, failed=True, reason="target_lock_timeout")
    result = action.update({})
    assert result.done and not result.failed and result.detail["status"] == "lock_failed"


def test_align_failure_finishes_current_target_without_failing_mission():
    action = _action()
    _to_align(action)
    action.child = _Child(done=False, failed=True, reason="align_descend_timeout", height=2.1)
    result = action.update({})
    assert result.done and not result.failed and result.detail["status"] == "align_failed"
    assert result.detail["height_m"] == 2.1


def test_default_align_configuration_disables_payload_offset_and_finishes_at_1_5m():
    action = _action()
    assert action.align_params["finish_altitude_m"] == 1.5
    assert action.align_params["config"]["min_altitude_m"] == 1.3
    assert action.align_params["config"]["payload_offset_enabled"] is False
