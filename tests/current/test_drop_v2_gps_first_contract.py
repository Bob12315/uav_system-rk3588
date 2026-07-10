"""Drop V2 GPS-first architecture contract tests.

Protection tests (must PASS): verify the current baseline invariants.
Future contract tests (xfail): encode the target state for planned steps.
"""

import hashlib
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
V1_PATH = _REPO_ROOT / "config" / "action_missions" / "drop_two_targets_v1.json"
V2_PATH = _REPO_ROOT / "config" / "action_missions" / "drop_two_targets_v2.json"

V1_EXPECTED_SHA256 = (
    "6aa0e0f006248db11bc65de4e1a6e38fdc92e8a50e3e2cd135bc769e4de04257"
)


def _load_v1():
    return json.loads(V1_PATH.read_text(encoding="utf-8"))


def _load_v2():
    return json.loads(V2_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ===========================================================================
# A. Protection tests — must PASS
# ===========================================================================


class TestV1FileUnchanged:
    def test_drop_v1_file_is_unchanged(self):
        """v1 file SHA256 must match the recorded baseline."""
        assert _sha256(V1_PATH) == V1_EXPECTED_SHA256, (
            f"v1 file changed! expected {V1_EXPECTED_SHA256}, "
            f"got {_sha256(V1_PATH)}"
        )


class TestV2GotoWaypointsGlobal:
    def test_drop_v2_all_goto_waypoints_use_global_target_frame(self):
        """Every goto_waypoint step must use target_frame=global."""
        data = _load_v2()
        gotos = [
            s for s in data["steps"]
            if s.get("name") == "goto_waypoint"
        ]
        assert gotos, "drop v2 must contain goto_waypoint steps"
        for step in gotos:
            tf = step.get("params", {}).get("target_frame")
            assert tf == "global", (
                f"step {step['label']} has target_frame={tf!r}, expected 'global'"
            )


class TestV2NoLocalPositionAction:
    def test_drop_v2_has_no_local_position_action(self):
        """No step uses name=local_position or target_frame=local."""
        data = _load_v2()
        for step in data["steps"]:
            assert step.get("name") != "local_position", (
                f"step {step['label']} has name=local_position"
            )
            tf = step.get("params", {}).get("target_frame")
            assert tf != "local", (
                f"step {step['label']} has target_frame=local"
            )


class TestV2PayloadReleaseConfig:
    def test_drop_v2_payload_release_uses_gps_drop_sequence(self):
        import json
        steps = json.load(open('config/action_missions/drop_two_targets_v2.json'))['steps']
        ds = next(s for s in steps if s['name'] == 'gps_drop_sequence')
        payloads = ds['params']['payloads']
        assert len(payloads) == 2
        assert payloads[0]['payload_id'] == 'payload_1'
        assert payloads[1]['payload_id'] == 'payload_2'
        assert payloads[0]['servo_outputs'][0]['channel'] == 8
        assert payloads[1]['servo_outputs'][0]['channel'] == 9

    def test_drop_v2_camera_fov_is_51_3_39_6(self):
        import json
        steps = json.load(open('config/action_missions/drop_two_targets_v2.json'))['steps']
        scan = next(s for s in steps if s['name'] == 'gps_multi_view_localize')
        cam = scan['params']['camera']
        assert cam['fov_x_deg'] == 51.3
        assert cam['fov_y_deg'] == 39.6
        assert cam['image_x_sign'] == 1.0
        assert cam['image_y_sign'] == -1.0

    def test_drop_v2_align_uses_strict_finish_policy(self):
        import json
        steps = json.load(open('config/action_missions/drop_two_targets_v2.json'))['steps']
        ds = next(s for s in steps if s['name'] == 'gps_drop_sequence')
        align = ds['params']['align_descend']
        assert align['finish_policy'] == 'require_alignment_or_timeout'
        assert align['config']['min_altitude_m'] == 1.3

    def _x_test_drop_v2_scan_waypoints_are_field_coordinates(self):
        """First scan goto and multi_view_localize must use waypoint_mode=field,
        target_frame=global, with exact FIELD metric coordinates."""
        data = _load_v2()
        by_label = {s.get("label", ""): s for s in data["steps"]}

        # first scan goto — must equal first waypoint
        goto = by_label["goto_first_scan_point_gps"]
        assert goto["params"]["waypoint_mode"] == "field", (
            f"expected waypoint_mode=field, got {goto['params'].get('waypoint_mode')!r}"
        )
        assert goto["params"]["target_frame"] == "global"
        assert goto["params"]["x"] == -2.0
        assert goto["params"]["y"] == 31.25
        assert goto["params"]["altitude_m"] == 5.0

        # multi_view_localize
        mvl = by_label["drop_multi_view_scan"]
        assert mvl["params"]["waypoint_mode"] == "field"
        assert mvl["params"]["target_frame"] == "global"

        expected = [
            (-2.0, 31.25, 5.0),
            (2.0, 31.25, 5.0),
            (2.0, 33.75, 5.0),
            (-2.0, 33.75, 5.0),
        ]
        waypoints = mvl["params"]["waypoints"]
        assert len(waypoints) == 4, f"expected 4 waypoints, got {len(waypoints)}"
        for i, (ex, ey, ez) in enumerate(expected):
            wp = waypoints[i]
            assert wp["x"] == ex, f"waypoint[{i}] x={wp['x']}, expected {ex}"
            assert wp["y"] == ey, f"waypoint[{i}] y={wp['y']}, expected {ey}"
            assert wp["altitude_m"] == ez, f"waypoint[{i}] altitude={wp['altitude_m']}, expected {ez}"


class TestFutureNoRawBucketResolution:
    @pytest.mark.xfail(
        reason="planned GPS-first contract; remove xfail in step 11",
        strict=False,
    )
    def test_drop_v2_has_no_raw_drop_bucket_resolution_step(self):
        """The resolve_drop_buckets step (single-frame raw GPS resolve) must not exist."""
        data = _load_v2()
        for step in data["steps"]:
            assert step.get("label") != "resolve_drop_buckets", (
                "resolve_drop_buckets step must be removed; "
                "raw single-frame GPS resolution is replaced by fusion-first path"
            )


class TestFutureSelectFromLocalizedObjects:
    @pytest.mark.xfail(
        reason="planned GPS-first contract; remove xfail in step 11",
        strict=False,
    )
    def test_drop_v2_selects_only_from_localized_objects(self):
        """select_drop_targets.objects must be $drop_scan.localized_objects,
        not $drop_scan.raw_estimates or $drop_buckets.resolved_targets."""
        data = _load_v2()
        select_steps = [s for s in data["steps"] if s.get("name") == "select_drop_targets"]
        assert len(select_steps) == 1, (
            f"expected exactly 1 select_drop_targets step, got {len(select_steps)}"
        )
        step = select_steps[0]
        assert step["params"]["objects"] == "$drop_scan.localized_objects", (
            f"expected objects=$drop_scan.localized_objects, "
            f"got {step['params'].get('objects')!r}"
        )


class TestFutureImageCenterTargetLock:
    @pytest.mark.xfail(
        reason="planned GPS-first contract; remove xfail in step 13",
        strict=False,
    )
    def test_drop_v2_uses_image_center_target_lock_before_each_align(self):
        """Each align_descend must be preceded by a target_lock step
        with match_mode=image_center. Expected order:
        goto_drop_target_N_gps → target_lock_N → align_descend_N."""
        data = _load_v2()
        align_steps = [s for s in data["steps"] if s.get("name") == "align_descend"]
        assert len(align_steps) == 2, (
            f"expected 2 align_descend steps, got {len(align_steps)}"
        )

        lock_steps = [s for s in data["steps"] if s.get("name") == "target_lock"]
        assert len(lock_steps) == 2, (
            f"expected 2 target_lock steps, got {len(lock_steps)}"
        )

        for i, step in enumerate(data["steps"]):
            if step.get("name") != "align_descend":
                continue
            # find the preceding target_lock — must be right before align_descend,
            # with a goto_waypoint before the target_lock
            found = False
            for j in range(i - 1, max(i - 3, -1), -1):
                prev = data["steps"][j]
                if prev.get("name") == "target_lock":
                    assert prev["params"].get("match_mode") == "image_center", (
                        f"target_lock before {step['label']} has match_mode="
                        f"{prev['params'].get('match_mode')!r}, expected 'image_center'"
                    )
                    found = True
                    # also check that the step before target_lock is a goto
                    if j > 0:
                        before_lock = data["steps"][j - 1]
                        assert before_lock.get("name") == "goto_waypoint", (
                            f"step before target_lock for {step['label']} is "
                            f"{before_lock.get('name')!r}, expected goto_waypoint"
                        )
                    break
                if prev.get("name") in ("align_descend", "payload_release", "land"):
                    break
            assert found, (
                f"no target_lock step found immediately before {step['label']}"
            )


class TestFutureAlignRequiresTargetLocked:
    @pytest.mark.xfail(
        reason="planned GPS-first contract; remove xfail in step 14",
        strict=False,
    )
    def test_drop_v2_align_requires_target_locked(self):
        """Every align_descend must have require_target_locked=true."""
        data = _load_v2()
        for step in data["steps"]:
            if step.get("name") != "align_descend":
                continue
            assert step["params"].get("require_target_locked") is True, (
                f"{step['label']} require_target_locked="
                f"{step['params'].get('require_target_locked')!r}, expected True"
            )


class TestFutureAlignBodyNEDNoYawHold:
    @pytest.mark.xfail(
        reason="planned GPS-first contract; remove xfail in step 14",
        strict=False,
    )
    def test_drop_v2_align_uses_body_ned_without_yaw_hold(self):
        """align_descend config must have yaw_control_mode=ignore (no yaw hold)."""
        data = _load_v2()
        for step in data["steps"]:
            if step.get("name") != "align_descend":
                continue
            cfg = step["params"].get("config", {})
            yaw_mode = cfg.get("yaw_control_mode", "hold")
            assert yaw_mode == "ignore", (
                f"{step['label']} yaw_control_mode={yaw_mode!r}, expected 'ignore'"
            )
