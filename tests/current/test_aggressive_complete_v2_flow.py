"""Regression coverage for the aggressive complete-v2 competition flow."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.coordinate_transform import field_to_gps_from_origin
from missions.common.actions import gps_drop_sequence as drop_module
from missions.common.actions.gps_drop_sequence import GpsDropSequenceAction
from missions.common.actions.result import ActionResult
from missions.common.actions.takeoff import TakeoffAction


ROOT = Path(__file__).resolve().parents[2]
MISSION = ROOT / "config/action_missions/rescue_2026_full_auto_v2.json"
PAYLOADS = [
    {"payload_id": "p1", "servo_outputs": [{"channel": 8, "release_pwm": 1750, "hold_pwm": 1250}]},
    {"payload_id": "p2", "servo_outputs": [{"channel": 9, "release_pwm": 1815, "hold_pwm": 1185}]},
]


class _Goto:
    starts: list[dict] = []

    def start(self, params):
        type(self).starts.append(dict(params))

    def update(self, context):
        return ActionResult(done=True)


class _Lock:
    starts: list[dict] = []

    def start(self, params):
        type(self).starts.append(dict(params))

    def update(self, context):
        return ActionResult(done=True)


class _Align(_Lock):
    pass


@pytest.fixture
def drop_children(monkeypatch):
    _Goto.starts = []
    _Lock.starts = []
    _Align.starts = []
    monkeypatch.setattr(drop_module, "GotoWaypointAction", _Goto)
    monkeypatch.setattr(drop_module, "GpsTargetLockAction", _Lock)
    monkeypatch.setattr(drop_module, "AlignDescendAction", _Align)


def _field_reference() -> dict:
    return {
        "is_confirmed": True,
        "is_frozen": True,
        "is_ready_for_field_to_gps": True,
        "synced_to_runtime": True,
        "field_heading_yaw_rad": 0.25,
        "runtime_binding": {"state": "applied", "geometry": {"home": {"lat": 34.0, "lon": 108.0}}},
    }


def _drive(action: GpsDropSequenceAction, context: dict) -> list[ActionResult]:
    results = []
    for _ in range(20):
        result = action.update(context)
        results.append(result)
        if result.done or result.failed:
            return results
    raise AssertionError("drop sequence did not terminate")


def test_takeoff_duration_timeout_is_eight_second_cap() -> None:
    action = TakeoffAction()
    action.start({"max_duration_s": 8.0, "max_updates": 999})
    action.started_monotonic_s = time.monotonic() - 8.0
    result = action.update({"relative_altitude": 0.0})
    assert result.failed and result.reason == "takeoff_timeout"


def test_takeoff_reaching_height_before_duration_completes_normally() -> None:
    action = TakeoffAction()
    action.start({"altitude_m": 3.5, "altitude_tolerance_m": 0.35, "max_duration_s": 8.0})
    action.update({})
    action.update({})
    action.update({})
    result = action.update({"relative_altitude": 3.2})
    assert result.done and result.reason == "takeoff_altitude_reached"


def test_complete_v2_takeoff_timeout_continues_to_scan() -> None:
    steps = json.loads(MISSION.read_text())["steps"]
    takeoff = steps[0]
    assert takeoff["params"]["max_duration_s"] == 8.0
    assert takeoff["on_failed"] == {"action": "continue"}
    assert steps[1]["name"] == "gps_multi_view_localize"


def test_zero_target_flies_field_center_and_releases_without_lock_align_or_climb(drop_children) -> None:
    action = GpsDropSequenceAction()
    action.start({
        "targets": [], "payloads": PAYLOADS, "approach_altitude_m": 3.5,
        "no_target_strategy": "field_center_direct_dual_release",
        "no_target_field_center": {"x": 0.0, "y": 32.5, "altitude_m": 3.5},
        "release_wait_updates": 1,
    })
    results = _drive(action, {"field_reference": _field_reference()})
    expected = field_to_gps_from_origin(0.0, 32.5, 3.5, origin_lat=34.0, origin_lon=108.0, field_heading_yaw_rad=0.25)
    assert results[-1].done
    assert len(_Goto.starts) == 1
    assert _Goto.starts[0]["lat"] == pytest.approx(expected.lat)
    assert _Goto.starts[0]["lon"] == pytest.approx(expected.lon)
    assert _Goto.starts[0]["altitude_m"] == 3.5
    assert not _Lock.starts and not _Align.starts
    release_channels = [a["params"]["channel"] for r in results for a in r.actions if a.get("action_type") == "set_servo" and a["params"]["pwm"] in (1750, 1815)]
    assert release_channels == [8, 9]
    assert not any(r.detail.get("phase") == "climb" for r in results)


def test_single_and_dual_climb_heights_preserve_their_distinct_strategies(drop_children) -> None:
    single = GpsDropSequenceAction()
    single.start({"targets": [{"valid": True, "lat": 34.1, "lon": 108.1, "target_id": "one"}], "payloads": PAYLOADS, "approach_altitude_m": 3.5, "climb_after_drop_m": 2.5, "single_target_climb_after_release_m": 3.5, "release_wait_updates": 1})
    _drive(single, {"drone": {"relative_altitude": 4.0}})
    assert [_Goto.starts[0]["altitude_m"], _Goto.starts[1]["altitude_m"]] == [3.5, 3.5]

    _Goto.starts = []
    dual = GpsDropSequenceAction()
    dual.start({"targets": [{"valid": True, "lat": 34.1, "lon": 108.1, "target_id": "one"}, {"valid": True, "lat": 34.2, "lon": 108.2, "target_id": "two"}], "payloads": PAYLOADS, "approach_altitude_m": 3.5, "climb_after_drop_m": 2.5, "release_wait_updates": 1})
    _drive(dual, {"drone": {"relative_altitude": 4.0}})
    assert [item["altitude_m"] for item in _Goto.starts] == [3.5, 2.5, 3.5, 2.5]


def test_complete_v2_descent_and_landing_parameters() -> None:
    steps = json.loads(MISSION.read_text())["steps"]
    drop = next(step["params"] for step in steps if step["name"] == "gps_drop_sequence")
    config = drop["align_descend"]["config"]
    assert (config["descend_speed_mps"], config["slow_descend_speed_mps"], config["unaligned_descend_speed_mps"]) == (0.24, 0.18, 0.06)
    assert drop["align_descend_max_updates"] == drop["align_descend"]["max_updates"] == 150
    land = next(step["params"] for step in steps if step["name"] == "visual_land")
    assert land["search_max_updates"] == 1 and land["blind_descend_speed_mps"] == 0.5
    land_config = land["align_descend"]["config"]
    assert (land_config["descend_speed_mps"], land_config["slow_descend_speed_mps"], land_config["unaligned_descend_speed_mps"]) == (0.5, 0.3, 0.3)
    assert land_config["descent_speed_stages"] == [{"max_altitude_m": 0.8, "max_descend_speed_mps": 0.25}, {"max_altitude_m": 2.5, "max_descend_speed_mps": 0.5}]
