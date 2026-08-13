"""Tests for drop_workflow selected_targets state machine (Phase 4.1)."""
from __future__ import annotations


def test_result_service_owns_drop_workflow_helpers():
    """Drop workflow state and helpers belong to ResultService, not the runner."""
    from application.result_service import ResultService
    from application.runner import SystemRunner

    for name in (
        "_workflow_targets", "_rank_by_target_id", "_rank_by_target_xy",
        "_drop_rank_from_result", "_save_drop_workflow_from_action_result",
        "_ensure_drop_workflow",
    ):
        assert hasattr(ResultService, name)
        assert not hasattr(SystemRunner, name)


def test_drop_rank_from_result_by_id():
    """Rank inferred via target_id matching."""
    from application.runner import SystemRunner
    from app.config import build_arg_parser, load_app_config
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    # Set up workflow with two selected targets
    wf = runner.result_service._ensure_drop_workflow()
    wf["selected_targets"] = [
        {"id": "obj_a", "target_id": "obj_a", "status": "selected", "rank": 1, "locked": False, "released": False},
        {"id": "obj_b", "target_id": "obj_b", "status": "selected", "rank": 2, "locked": False, "released": False},
    ]

    # target_lock with detail.target_id matching obj_b -> rank 2
    detail = {"target_id": "obj_b", "locked_track_id": 42}
    rank = runner.result_service._drop_rank_from_result("target_lock", detail)
    assert rank == 2

    # target_lock with detail.target containing target_id
    detail2 = {"target": {"target_id": "obj_a"}}
    rank2 = runner.result_service._drop_rank_from_result("target_lock", detail2)
    assert rank2 == 1


def test_drop_rank_from_result_by_key():
    """Rank inferred via key/payload_id patterns."""
    from application.runner import SystemRunner
    from app.config import build_arg_parser, load_app_config
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    wf = runner.result_service._ensure_drop_workflow()
    wf["selected_targets"] = [
        {"id": "t1", "target_id": "t1", "status": "released", "rank": 1, "locked": True, "released": True},
        {"id": "t2", "target_id": "t2", "status": "selected", "rank": 2, "locked": False, "released": False},
    ]

    # payload_2 -> rank 2
    detail = {"payload_id": "payload_2", "target_id": "t2"}
    rank = runner.result_service._drop_rank_from_result("payload_release", detail)
    assert rank == 2


def test_drop_rank_from_result_by_xy():
    """Rank inferred via coordinate matching."""
    from application.runner import SystemRunner
    from app.config import build_arg_parser, load_app_config
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    wf = runner.result_service._ensure_drop_workflow()
    wf["selected_targets"] = [
        {"id": "t1", "x": 10.0, "y": 20.0, "status": "selected", "rank": 1, "locked": False, "released": False},
        {"id": "t2", "x": -5.0, "y": 30.0, "status": "selected", "rank": 2, "locked": False, "released": False},
    ]

    # target at (-5.0, 30.0) should match t2 (rank 2)
    detail = {"target": {"x": -5.0, "y": 30.0}}
    rank = runner.result_service._drop_rank_from_result("target_lock", detail)
    assert rank == 2

    # target at (10.1, 20.1) should match t1 (rank 1)
    detail2 = {"target": {"x": 10.1, "y": 20.1}}
    rank2 = runner.result_service._drop_rank_from_result("target_lock", detail2)
    assert rank2 == 1


def test_select_drop_targets_builds_canonical():
    """select_drop_targets builds canonical selected_targets with status fields."""
    from application.runner import SystemRunner
    from app.config import build_arg_parser, load_app_config
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    result = {
        "done": True,
        "detail": {
            "selected_targets": [
                {"id": "a", "x": 1.0, "y": 2.0},
                {"id": "b", "x": 3.0, "y": 4.0},
            ],
            "selected_count": 2,
        },
    }
    runner.result_service._save_drop_workflow_from_action_result("select_drop_targets", result)
    wf = runner.result_service._ensure_drop_workflow()
    targets = wf["selected_targets"]
    assert len(targets) == 2
    for t in targets:
        assert t.get("status") == "selected"
        assert t.get("locked") is False
        assert t.get("released") is False


def test_target_lock_then_release_preserves_states():
    """target_lock_0 then payload_release_1 preserves target states."""
    from application.runner import SystemRunner
    from app.config import build_arg_parser, load_app_config
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    # Setup: two selected targets
    runner.result_service._save_drop_workflow_from_action_result("select_drop_targets", {
        "done": True,
        "detail": {
            "selected_targets": [
                {"id": "t1", "x": 1.0, "y": 2.0},
                {"id": "t2", "x": 3.0, "y": 4.0},
            ],
            "selected_count": 2,
        },
    })

    # target_lock for t1
    runner.result_service._save_drop_workflow_from_action_result("target_lock", {
        "done": True,
        "detail": {"target_id": "t1", "locked_track_id": 1},
    })
    wf = runner.result_service._ensure_drop_workflow()
    assert wf["selected_targets"][0]["status"] == "locked"
    assert wf["selected_targets"][1]["status"] == "selected"

    # payload_release for t1
    runner.result_service._save_drop_workflow_from_action_result("payload_release", {
        "done": True,
        "detail": {"payload_id": "payload_1", "target_id": "t1", "release_sent": True},
    })
    wf = runner.result_service._ensure_drop_workflow()
    assert wf["selected_targets"][0]["status"] == "released"
    assert wf["selected_targets"][0]["released"] is True
    assert wf["selected_targets"][1]["status"] == "selected"
    assert wf["current_rank"] == 2

    # target_lock for t2 — must not overwrite t1
    runner.result_service._save_drop_workflow_from_action_result("target_lock", {
        "done": True,
        "detail": {"target_id": "t2", "locked_track_id": 2},
    })
    wf = runner.result_service._ensure_drop_workflow()
    assert wf["selected_targets"][0]["status"] == "released"  # preserved!
    assert wf["selected_targets"][1]["status"] == "locked"

    # land must not clear states
    runner.result_service._save_drop_workflow_from_action_result("land", {"done": True, "detail": {}})
    wf = runner.result_service._ensure_drop_workflow()
    assert wf["selected_targets"][0]["status"] == "released"
    assert wf["selected_targets"][1]["status"] == "locked"


def test_released_target_not_overwritten_by_lock():
    """A released target must not be overwritten by a subsequent target_lock."""
    from application.runner import SystemRunner
    from app.config import build_arg_parser, load_app_config
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    runner.result_service._save_drop_workflow_from_action_result("select_drop_targets", {
        "done": True,
        "detail": {
            "selected_targets": [
                {"id": "t1", "x": 1.0, "y": 2.0},
                {"id": "t2", "x": 3.0, "y": 4.0},
            ],
        },
    })

    # release t1
    runner.result_service._save_drop_workflow_from_action_result("payload_release", {
        "done": True,
        "detail": {"payload_id": "payload_1", "target_id": "t1", "release_sent": True},
    })
    wf = runner.result_service._ensure_drop_workflow()
    assert wf["selected_targets"][0]["status"] == "released"

    # target_lock that accidentally maps to t1 must not overwrite
    runner.result_service._save_drop_workflow_from_action_result("target_lock", {
        "done": True,
        "detail": {"target_id": "t1", "locked_track_id": 99},
    })
    wf = runner.result_service._ensure_drop_workflow()
    # t1 status must remain released, not become locked
    assert wf["selected_targets"][0]["status"] == "released"
    assert wf["selected_targets"][0]["released"] is True
