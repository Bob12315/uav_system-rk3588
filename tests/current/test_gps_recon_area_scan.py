from __future__ import annotations

import pytest

from missions.common.actions.gps_recon_area_scan import DANGER_SIGN_CLASS_NAMES, GpsReconAreaScanAction
from missions.common.actions.result import ActionResult


WAYPOINTS = [
    {"x": -3.0, "y": 56.0, "altitude_m": 3.0},
    {"x": 3.0, "y": 56.0, "altitude_m": 3.0},
    {"x": 3.0, "y": 58.0, "altitude_m": 3.0},
    {"x": -3.0, "y": 58.0, "altitude_m": 3.0},
]


class FakeGoto:
    created: list["FakeGoto"] = []

    def __init__(self):
        self.params = {}
        self.done = False
        self.failed = False
        self.stopped = False
        self.created.append(self)

    def start(self, params): self.params = dict(params)
    def update(self, context):
        return ActionResult(failed=self.failed, done=self.done, actions=[] if self.done else [{"action_type": "global_goto"}])
    def stop(self): self.stopped = True


@pytest.fixture
def action(monkeypatch):
    import missions.common.actions.gps_recon_area_scan as module
    FakeGoto.created = []
    monkeypatch.setattr(module, "GotoWaypointAction", FakeGoto)
    value = GpsReconAreaScanAction()
    value.start({"waypoints": WAYPOINTS, "waypoint_mode": "field", "target_frame": "global", "yaw_mode": "field_heading", "scoring_target_indices": [1, 3]})
    return value


def scene(frame_id, detections): return {"scene": {"frame_id": frame_id, "detections": detections}}


def arrive(action):
    action.goto_action.done = True
    return action.update({})


def test_only_explicit_horizontal_target_indices_are_scored(action):
    action.update(scene("p0", [{"class_name": "baozha", "confidence": .9}]))
    arrive(action)  # reached P0; next segment targets P1
    action.update(scene("p1", [{"class_name": "baozha", "confidence": .7}]))
    arrive(action)  # reached P1; next segment targets P2
    action.update(scene("p2", [{"class_name": "baozha", "confidence": .8}]))
    arrive(action)  # reached P2; next segment targets P3
    action.update(scene("p3", [{"class_name": "baozha", "confidence": .6}]))
    assert action._ranking()[0]["seen_frames"] == 2
    assert action._ranking()[0]["confidence_sum"] == pytest.approx(1.3)


def test_unique_frames_filters_classes_and_uses_best_box_per_class(action):
    arrive(action)
    frame = scene("same", [
        {"class_name": "baozha", "confidence": .61}, {"class_name": "baozha", "confidence": .72},
        {"class_name": "fushi", "confidence": .84}, {"class_name": "bucket", "confidence": .91},
        {"class_name": "H", "confidence": .88}, {"class_name": "ciji", "confidence": .34},
    ])
    action.update(frame)
    action.update(frame)
    ranking = {item["class_name"]: item for item in action._ranking()}
    assert ranking["baozha"]["confidence_sum"] == pytest.approx(.72)
    assert ranking["fushi"]["confidence_sum"] == pytest.approx(.84)
    assert ranking["ciji"]["seen_frames"] == 0
    assert action.scored_unique_frame_count == 1
    assert action.duplicate_frame_count == 1
    assert action.valid_sign_frame_count == 1
    assert action.observed_unique_frame_count == 1
    assert "bucket" not in ranking and "H" not in ranking


def test_missing_identity_is_not_scored_and_ranking_is_complete_and_stable(action):
    arrive(action)
    action.update({"scene": {"detections": [{"class_name": "baozha", "confidence": .9}]}})
    action.update(scene("one", [{"class_name": "shenghua", "confidence": .8}, {"class_name": "baozha", "confidence": .8}]))
    ranking = action._ranking()
    assert len(ranking) == 10
    assert [item["class_name"] for item in ranking[:2]] == ["baozha", "shenghua"]
    assert ranking[0]["hit_ratio"] == pytest.approx(1.0)
    assert action.missing_frame_identity_count >= 1


def test_all_zero_scores_complete_normally_and_gotos_are_exact(action):
    for index in range(4):
        params = FakeGoto.created[index].params
        assert params["x"] == WAYPOINTS[index]["x"]
        assert params["y"] == WAYPOINTS[index]["y"]
        assert params["altitude_m"] == pytest.approx(3.0)
        assert params["waypoint_mode"] == "field"
        assert params["target_frame"] == "global"
        assert params["yaw_mode"] == "field_heading"
        if index < 3:
            arrive(action)
    result = arrive(action)
    assert result.done and not result.failed
    assert [item["class_name"] for item in result.detail["ranking"]] == DANGER_SIGN_CLASS_NAMES
    assert all(item["confidence_sum"] == 0 for item in result.detail["ranking"])


def test_stop_stops_active_goto(action):
    goto = action.goto_action
    action.stop()
    assert goto.stopped is True
    assert action.update({}).done is True


def test_five_waypoint_route_without_scoring_skips_scene_processing(monkeypatch):
    import missions.common.actions.gps_recon_area_scan as module
    FakeGoto.created = []
    monkeypatch.setattr(module, "GotoWaypointAction", FakeGoto)
    route = [
        {"x": -2.0, "y": 56.0, "altitude_m": 4.0},
        {"x": 2.0, "y": 56.0, "altitude_m": 4.0},
        {"x": 2.0, "y": 59.0, "altitude_m": 4.0},
        {"x": -2.0, "y": 59.0, "altitude_m": 4.0},
        {"x": 0.0, "y": 57.5, "altitude_m": 4.0},
    ]
    value = GpsReconAreaScanAction()
    value.start({"waypoints": route, "scoring_target_indices": []})
    for index in range(len(route)):
        assert FakeGoto.created[index].params["x"] == route[index]["x"]
        value.goto_action.done = True
        result = value.update(scene(f"route-{index}", [{"class_name": "baozha", "confidence": .9}]))

    assert result.done
    assert result.detail["ranking_mode"] is False
    assert result.detail["ranking"] == []
    assert result.detail["scan_summary"]["observed_unique_frame_count"] == 0


def test_approach_frame_is_consumed_before_first_scoring_segment(action):
    frame_a = scene("approach-A", [{"class_name": "baozha", "confidence": .9}])
    action.update(frame_a)  # flying to P0: observe but do not score
    action.goto_action.done = True
    action.update(frame_a)  # arrives P0 with the same stale scene
    action.update(frame_a)  # P0 -> P1: must still not score A
    action.update(scene("fresh-C", [{"class_name": "baozha", "confidence": .7}]))

    ranked = {item["class_name"]: item for item in action._ranking()}
    assert ranked["baozha"]["seen_frames"] == 1
    assert ranked["baozha"]["confidence_sum"] == pytest.approx(.7)
    assert action.non_scoring_unique_frame_count == 1
    assert action.scored_unique_frame_count == 1


def test_connector_frame_is_consumed_before_second_scoring_segment(action):
    arrive(action)  # P0 -> P1
    action.goto_action.done = True
    action.update(scene("scoring-A", []))  # reach P1; start connector P1 -> P2
    frame_b = scene("connector-B", [{"class_name": "fushi", "confidence": .9}])
    action.update(frame_b)
    action.goto_action.done = True
    action.update(frame_b)  # reach P2 with the same connector frame
    action.update(frame_b)  # P2 -> P3: B must not score
    action.update(scene("fresh-C", [{"class_name": "fushi", "confidence": .6}]))

    ranked = {item["class_name"]: item for item in action._ranking()}
    assert ranked["fushi"]["seen_frames"] == 1
    assert ranked["fushi"]["confidence_sum"] == pytest.approx(.6)
    assert action.non_scoring_unique_frame_count >= 1
