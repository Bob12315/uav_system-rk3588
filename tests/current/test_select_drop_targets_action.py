from __future__ import annotations

import pytest

from missions.common.actions.select_drop_targets import SelectDropTargetsAction


def _select(objects, **params):
    action = SelectDropTargetsAction()
    action.start({"objects": objects, **params})
    return action.update({})


def test_select_drop_targets_update_before_start_fails() -> None:
    action = SelectDropTargetsAction()

    result = action.update({})

    assert result.failed is True
    assert result.reason == "action_not_started"


def test_select_drop_targets_selects_bucket_1_and_bucket_2() -> None:
    result = _select(
        [
            {"id": "b3", "class_name": "bucket_3", "local_x": 2, "local_y": 30, "seen_count": 3},
            {"id": "b1", "class_name": "bucket_1", "local_x": 0, "local_y": 30, "seen_count": 3},
            {"id": "b2", "class_name": "bucket_2", "local_x": 1, "local_y": 30, "seen_count": 3},
        ]
    )

    assert result.done is True
    assert result.reason == "drop_targets_selected"
    selected = result.detail["selected_targets"]
    assert selected[0]["id"] == "b1"
    assert selected[1]["id"] == "b2"
    assert selected[0]["rank"] == 1
    assert result.actions == []


def test_select_drop_targets_allow_fewer_accepts_one_target() -> None:
    result = _select(
        [{"id": "b1", "class_name": "bucket", "local_x": 1, "local_y": 2, "seen_count": 2}],
        target_count=2,
        allow_fewer=True,
        single_target_servo_outputs=[
            {"channel": 8, "release_pwm": 1750},
            {"channel": 9, "release_pwm": 1815},
        ],
        multi_target_first_servo_outputs=[{"channel": 8, "release_pwm": 1750}],
    )

    assert result.done is True
    assert result.failed is False
    assert result.detail["selected_count"] == 1
    assert result.detail["allow_fewer"] is True
    assert [item["channel"] for item in result.detail["first_release_servo_outputs"]] == [8, 9]


def test_select_drop_targets_two_targets_uses_first_payload_only() -> None:
    result = _select(
        [
            {"id": "b1", "class_name": "bucket", "local_x": 1, "local_y": 2, "seen_count": 2},
            {"id": "b2", "class_name": "bucket", "local_x": 3, "local_y": 4, "seen_count": 2},
        ],
        target_count=2,
        allow_fewer=True,
        single_target_servo_outputs=[{"channel": 8}, {"channel": 9}],
        multi_target_first_servo_outputs=[{"channel": 8}],
    )

    assert result.done is True
    assert [item["channel"] for item in result.detail["first_release_servo_outputs"]] == [8]


def test_select_drop_targets_uses_xy_as_local_xy_fallback() -> None:
    result = _select(
        [
            {"id": "b1", "class_name": "bucket_1", "x": 0.5, "y": 30.5, "seen_count": 3},
        ],
        target_count=1,
    )

    selected = result.detail["selected_targets"][0]
    assert selected["local_x"] == 0.5
    assert selected["local_y"] == 30.5
    assert selected["x"] == 0.5
    assert selected["y"] == 30.5


def test_select_drop_targets_filters_low_seen_count() -> None:
    result = _select(
        [{"id": "b1", "class_name": "bucket_1", "local_x": 0, "local_y": 30, "seen_count": 1}],
        target_count=1,
    )

    assert result.failed is True
    assert result.reason == "no_valid_drop_targets"
    assert result.detail["rejected_objects"][0]["reason"] == "low_seen_count"


def test_select_drop_targets_filters_unknown_class() -> None:
    result = _select(
        [{"id": "u1", "class_name": "unknown", "local_x": 0, "local_y": 30, "seen_count": 3}],
        target_count=1,
    )

    assert result.failed is True
    assert result.detail["rejected_objects"][0]["reason"] == "unknown_class"


def test_select_drop_targets_filters_missing_xy() -> None:
    result = _select(
        [{"id": "b1", "class_name": "bucket_1", "seen_count": 3}],
        target_count=1,
    )

    assert result.failed is True
    assert result.detail["rejected_objects"][0]["reason"] == "missing_xy"


def test_select_drop_targets_fails_when_candidates_less_than_target_count() -> None:
    result = _select(
        [{"id": "b1", "class_name": "bucket_1", "local_x": 0, "local_y": 30, "seen_count": 3}],
        target_count=2,
    )

    assert result.failed is True
    assert result.reason == "not_enough_drop_targets"


def test_select_drop_targets_fails_when_objects_empty() -> None:
    result = _select([])

    assert result.failed is True
    assert result.reason == "no_drop_objects"


def test_select_drop_targets_deduplicates_nearby_candidates() -> None:
    result = _select(
        [
            {"id": "b1", "class_name": "bucket_1", "local_x": 0.0, "local_y": 30.0, "seen_count": 3},
            {"id": "b2", "class_name": "bucket_2", "local_x": 0.1, "local_y": 30.1, "seen_count": 3},
            {"id": "b3", "class_name": "bucket_3", "local_x": 1.0, "local_y": 30.0, "seen_count": 3},
        ],
        target_count=2,
        deduplicate_radius_m=0.35,
    )

    selected_ids = [item["id"] for item in result.detail["selected_targets"]]
    rejected_reasons = [item["reason"] for item in result.detail["rejected_objects"]]
    assert selected_ids == ["b1", "b3"]
    assert "duplicate_near_selected" in rejected_reasons


def test_select_drop_targets_target_count_one_selects_highest_score() -> None:
    result = _select(
        [
            {"id": "b2", "class_name": "bucket_2", "local_x": 1, "local_y": 30, "seen_count": 3},
            {"id": "b1", "class_name": "bucket_1", "local_x": 0, "local_y": 30, "seen_count": 3},
        ],
        target_count=1,
    )

    assert result.done is True
    assert result.detail["selected_targets"] == [result.detail["selected_targets"][0]]
    assert result.detail["selected_targets"][0]["id"] == "b1"
    assert result.detail["selected_count"] == 1


def test_select_drop_targets_prefers_zone_center_when_other_scores_tie() -> None:
    result = _select(
        [
            {"id": "far", "class_name": "bucket", "local_x": 5.0, "local_y": 30.0, "seen_count": 3},
            {"id": "near", "class_name": "bucket", "local_x": 0.1, "local_y": 30.0, "seen_count": 3},
        ],
        target_count=1,
        zone_center={"x": 0.0, "y": 30.0},
    )

    assert result.detail["selected_targets"][0]["id"] == "near"


@pytest.mark.parametrize(
    "params",
    [
        {"objects": "bad"},
        {"objects": [], "target_count": 0},
        {"objects": [], "score_table": []},
        {"objects": [], "deduplicate_radius_m": -0.1},
    ],
)
def test_select_drop_targets_rejects_invalid_params(params) -> None:
    action = SelectDropTargetsAction()

    with pytest.raises(ValueError):
        action.start(params)


def test_select_drop_targets_done_update_returns_cached_result() -> None:
    action = SelectDropTargetsAction()
    action.start(
        {
            "objects": [
                {"id": "b1", "class_name": "bucket_1", "local_x": 0, "local_y": 30, "seen_count": 3},
            ],
            "target_count": 1,
        }
    )

    first = action.update({})
    second = action.update({})

    assert first.done is True
    assert second.done is True
    assert second.reason == first.reason
    assert second.detail == first.detail


# ── zone_center_mode tests ──────────────────────────────────────────────


def test_select_drop_targets_zone_center_mode_local_default():
    """zone_center_mode 默认 local，行为与旧版一致。"""
    result = _select(
        [
            {"id": "far", "class_name": "bucket", "local_x": 5.0, "local_y": 30.0, "seen_count": 3},
            {"id": "near", "class_name": "bucket", "local_x": 0.1, "local_y": 30.0, "seen_count": 3},
        ],
        target_count=1,
        zone_center={"x": 0.0, "y": 30.0},
    )
    assert result.detail["selected_targets"][0]["id"] == "near"


def test_select_drop_targets_zone_center_mode_field_heading_zero():
    """zone_center_mode=field heading=0 时 field 中心转换正确并影响排序。"""
    ctx = {
        "field_heading_confirmed": True,
        "field_origin_confirmed": True,
        "field_heading_yaw_rad": 0.0,
        "field_origin_local_x": 100.0,
        "field_origin_local_y": 200.0,
    }
    # field zone_center (0, 32.5) at origin (100,200) → local (132.5, 200)
    # near: (132.5, 200) distance=0, far: (100, 232.5) distance≈45.96
    near = {"id": "near", "class_name": "bucket", "local_x": 132.5, "local_y": 200.0,
            "seen_count": 3}
    far = {"id": "far", "class_name": "bucket", "local_x": 100.0, "local_y": 232.5,
           "seen_count": 3}
    action = SelectDropTargetsAction()
    action.start({"objects": [far, near], "target_count": 1, "allow_fewer": True,
                  "zone_center": {"x": 0.0, "y": 32.5},
                  "zone_center_mode": "field"})
    result = action.update(ctx)
    assert result.done
    assert result.detail["selected_targets"][0]["id"] == "near"


def test_select_drop_targets_zone_center_mode_field_missing_context():
    """zone_center_mode=field 但 context 缺失 → failed。"""
    action = SelectDropTargetsAction()
    action.start({"objects": [{"id": "b1", "class_name": "bucket", "local_x": 1, "local_y": 2,
                               "seen_count": 3}],
                  "target_count": 1, "allow_fewer": True,
                  "zone_center": {"x": 0.0, "y": 32.5},
                  "zone_center_mode": "field"})
    result = action.update({})
    assert result.failed
    assert result.reason == "missing_field_reference_for_zone_center"
