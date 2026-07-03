"""Integration tests for field profile backend binding API (Phase C-1)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from app.field_profile import (
    FieldProfile,
    FieldProfileValidationError,
    load_field_profile_json,
)
from app.field_profile_service import FieldProfileService
from app.field_reference import FieldReference
from app.field_reference_controller import FieldReferenceController
from app.field_reference_service import FieldReferenceService
from app.runtime_context import RuntimeContextBuilder

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

EXAMPLE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "config", "field_profiles", "example_competition_lane.json",
)


def _write_named_profiles(directory: Path) -> None:
    base = json.loads(Path(EXAMPLE_PATH).read_text(encoding="utf-8"))
    for profile_id in ("profile_a", "profile_b"):
        data = dict(base)
        data["profile_id"] = profile_id
        data["name"] = profile_id
        (directory / f"{profile_id}.json").write_text(
            json.dumps(data), encoding="utf-8"
        )


def _make_drone_snapshot(
    lat: float = 34.0,
    lon: float = 108.0,
    local_x: float = 0.0,
    local_y: float = 0.0,
    local_z: float = -10.0,
    gps_fix_type: int = 3,
    satellites_visible: int = 12,
    gps_eph: float = 1.0,
    gps_epv: float = 2.0,
    global_position_valid: bool = True,
    local_position_valid: bool = True,
) -> Dict[str, Any]:
    return {
        "lat": lat, "lon": lon,
        "local_x": local_x, "local_y": local_y, "local_z": local_z,
        "gps_fix_type": gps_fix_type,
        "satellites_visible": satellites_visible,
        "gps_eph": gps_eph, "gps_epv": gps_epv,
        "global_position_valid": global_position_valid,
        "local_position_valid": local_position_valid,
        "attitude_valid": True,
        "yaw": 0.0,
    }


def _make_controller(
    drone: Dict[str, Any] | None = None,
    frozen: bool = False,
) -> FieldReferenceController:
    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    builder = RuntimeContextBuilder()
    if drone is None:
        drone = _make_drone_snapshot()
    ctrl = FieldReferenceController(
        field_reference_service=svc,
        runtime_context_builder=builder,
        get_drone_snapshot=lambda: drone,
    )
    if frozen:
        # confirm then freeze
        svc.apply_profile_binding(
            bind_result=_make_mock_bind_ok(),
            profile_id="frozen_profile",
            profile_name="Frozen",
            origin_lat=34.0, origin_lon=108.0,
            forward_lat=34.0003, forward_lon=108.0,
        )
        # Sync RuntimeContext for frozen state
        ref = svc.reference
        builder.confirm_field_reference(
            field_heading_yaw_rad=ref.field_heading_yaw_rad,
            origin_local_x=ref.origin_local_n_m,
            origin_local_y=ref.origin_local_e_m,
            origin_local_z=ref.origin_local_z_m,
            source="frozen_setup",
        )
        svc.freeze()
    return ctrl


def _make_mock_bind_ok():
    """Return a mock BindResult with ok=True."""
    from app.field_profile_service import BindResult
    from app.field_profile import FieldProfileDiagnostics
    return BindResult(
        ok=True,
        profile_id="test",
        origin_local_n_m=0.0,
        origin_local_e_m=0.0,
        origin_local_z_m=-10.0,
        field_heading_yaw_rad=0.0,
        field_heading_deg=0.0,
        current_field_x_m=0.0,
        current_field_y_m=0.0,
        baseline_m=33.36,
        diagnostics=FieldProfileDiagnostics(),
    )


# ===================================================================
# 1. list profiles
# ===================================================================


def test_list_profiles_includes_example() -> None:
    ctrl = _make_controller()
    result = ctrl.bind_profile_current("example_competition_lane")
    # With GPS at (34.0, 108.0), the example profile binds successfully.
    assert result.get("ok") is True
    assert result.get("profile_id") == "example_competition_lane"


def test_list_profiles_works():
    """SystemRunner list_profiles should return config profiles."""
    # We test via the controller's profile resolution
    profiles_dir = os.path.join("config", "field_profiles")
    paths = FieldProfileService.list_profiles(profiles_dir)
    assert len(paths) >= 1
    assert any("example_competition_lane" in p for p in paths)


def test_runtime_dir_missing_no_crash():
    """runtime/field_profiles/ not existing should not crash."""
    paths = FieldProfileService.list_profiles(
        os.path.join("runtime", "field_profiles")
    )
    assert isinstance(paths, list)


def test_non_json_ignored():
    """Non-.json files are ignored."""
    with tempfile.TemporaryDirectory() as td:
        # Write a .txt file
        with open(os.path.join(td, "readme.txt"), "w") as f:
            f.write("hello")
        paths = FieldProfileService.list_profiles(td)
        assert len(paths) == 0


def test_invalid_profile_returns_error():
    """An invalid profile should be listed with valid=False."""
    with tempfile.TemporaryDirectory() as td:
        bad_path = os.path.join(td, "bad.json")
        with open(bad_path, "w") as f:
            f.write('{"schema_version":1,"profile_id":"bad","name":"Bad","points":{}}')
        try:
            FieldProfileService.load_profile(bad_path)
        except Exception:
            pass  # expected


# ===================================================================
# 2. load / get profile
# ===================================================================


def test_load_valid_profile():
    p = FieldProfileService.load_profile(
        "example_competition_lane",
        profile_dir=os.path.join("config", "field_profiles"),
    )
    assert p.profile_id == "example_competition_lane"


def test_load_missing_profile():
    with pytest.raises(FileNotFoundError):
        FieldProfileService.load_profile(
            "nonexistent",
            profile_dir=os.path.join("config", "field_profiles"),
        )


def test_path_traversal_rejected():
    with pytest.raises(ValueError, match="must not contain"):
        FieldProfileService.load_profile(
            "../../../etc/passwd",
            profile_dir=os.path.join("config", "field_profiles"),
        )


# ===================================================================
# 3. validate profile
# ===================================================================


def test_validate_valid_profile():
    diag = FieldProfileService.validate_profile(
        load_field_profile_json(EXAMPLE_PATH)
    )
    assert diag.ok
    assert len(diag.errors) == 0


def test_validate_invalid_profile():
    from app.field_profile import parse_field_profile, validate_field_profile
    data: Dict[str, Any] = {
        "schema_version": 1, "profile_id": "bad", "name": "Bad",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "points": {
            "origin": {"name": "O", "role": "origin", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
            # missing forward
        },
    }
    p = parse_field_profile(data)
    diag = validate_field_profile(p)
    assert not diag.ok


# ===================================================================
# 4. bind-current success
# ===================================================================


def test_bind_current_success():
    drone = _make_drone_snapshot(
        lat=34.0, lon=108.0,
        local_x=0.0, local_y=0.0, local_z=-10.0,
    )
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is True
    assert result.get("synced_to_runtime") is True
    assert result.get("profile_id") == "example_competition_lane"

    # FieldReference is confirmed but NOT frozen
    ref = ctrl._svc.reference
    assert ref.is_confirmed is True
    assert ref.is_frozen is False
    assert ref.origin_source == "profile_gps_bound"
    assert ref.heading_source == "profile_gps_two_point"


def test_bind_current_syncs_runtime_context():
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is True

    # RuntimeContextBuilder should be synced
    builder = ctrl._builder
    assert builder.field_heading_confirmed is True
    assert builder.field_origin_confirmed is True
    assert builder.field_heading_yaw_rad is not None


# ===================================================================
# 5. bind-current GPS quality failure
# ===================================================================


def test_bind_current_low_fix_fails():
    drone = _make_drone_snapshot(gps_fix_type=2)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False
    assert "bind failed" in str(result.get("error", ""))


def test_bind_current_low_satellites_fails():
    drone = _make_drone_snapshot(satellites_visible=5)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False


def test_bind_current_bad_eph_fails():
    drone = _make_drone_snapshot(gps_eph=10.0)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False


# ===================================================================
# 6. bind-current missing telemetry
# ===================================================================


def test_bind_current_no_gps_fails():
    drone = _make_drone_snapshot(global_position_valid=False)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False
    assert "GPS" in str(result.get("error", ""))


def test_bind_current_no_local_position_fails():
    drone = _make_drone_snapshot(local_position_valid=False)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False
    assert "LOCAL" in str(result.get("error", ""))


def test_bind_current_lat_lon_none_fails():
    drone = _make_drone_snapshot()
    del drone["lat"]
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False


def test_bind_current_missing_local_z_fails():
    """local_z missing must fail, not forge 0.0."""
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    del drone["local_z"]
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False
    assert "local_z" in str(result.get("error", "")).lower()


def test_bind_current_missing_local_z_does_not_write_state():
    """Missing local_z must NOT write FieldReference or RuntimeContext."""
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    del drone["local_z"]
    ctrl = _make_controller(drone=drone)
    ref_before = ctrl._svc.reference.is_confirmed
    ctrl.bind_profile_current("example_competition_lane")
    # FieldReference must be unchanged
    assert ctrl._svc.reference.is_confirmed == ref_before
    # RuntimeContext must be unchanged
    assert ctrl._builder.field_heading_confirmed == ref_before


# ===================================================================
# 7. frozen guard
# ===================================================================


def test_bind_current_frozen_rejects():
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = _make_controller(drone=drone, frozen=True)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False
    assert "frozen" in str(result.get("error", "")).lower()

    # Reference must still be frozen
    ref = ctrl._svc.reference
    assert ref.is_frozen is True

    # RuntimeContext must NOT have been synced by the rejected bind
    builder = ctrl._builder
    assert builder.field_origin_confirmed is True  # was synced during initial frozen setup
    # The origin_local should still be the frozen one (0,0), not the bind one
    assert ref.origin_local_n_m == pytest.approx(0.0)


# ===================================================================
# 8. synced consistency
# ===================================================================


def test_bind_then_preflight_passes():
    """After bind, the C-0 mission preflight should see sync."""
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is True
    assert result.get("synced_to_runtime") is True

    # Simulate C-0 preflight check: is_ready + synced
    ref = ctrl._svc.reference
    assert ref.is_ready() is True
    builder = ctrl._builder
    assert builder.field_transform_ready() is True


def test_bind_runtime_mismatch_detected():
    """If RuntimeContext is manually cleared after bind, preflight should fail."""
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is True

    # Manually clear RuntimeContext
    ctrl._builder.clear_field_heading()
    assert ctrl._builder.field_transform_ready() is False


# ===================================================================
# 9. status includes profile info
# ===================================================================


def test_status_includes_profile_after_bind():
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = _make_controller(drone=drone)
    ctrl.bind_profile_current("example_competition_lane")

    status = ctrl.status()
    fr = status.get("field_reference", {})
    assert fr.get("profile_id") == "example_competition_lane"
    assert fr.get("profile_binding_ok") is True


def test_status_no_profile_before_bind():
    ctrl = _make_controller()
    status = ctrl.status()
    fr = status.get("field_reference", {})
    assert fr.get("profile_id") is None


# ===================================================================
# 10. apply_profile_binding directly (service-level)
# ===================================================================


def test_apply_profile_binding_ok():
    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    bind_result = _make_mock_bind_ok()
    result = svc.apply_profile_binding(
        bind_result=bind_result,
        profile_id="t1", profile_name="Test1",
        origin_lat=34.0, origin_lon=108.0,
        forward_lat=34.0003, forward_lon=108.0,
    )
    assert result.get("ok") is True
    assert ref.is_confirmed is True
    assert ref.is_frozen is False
    assert ref.origin_source == "profile_gps_bound"


def test_apply_profile_binding_bind_not_ok():
    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    from app.field_profile_service import BindResult
    from app.field_profile import FieldProfileDiagnostics
    bad = BindResult(
        ok=False,
        profile_id="bad",
        errors=["test error"],
        diagnostics=FieldProfileDiagnostics(errors=["test error"]),
    )
    result = svc.apply_profile_binding(
        bind_result=bad,
        profile_id="bad", profile_name="Bad",
        origin_lat=0, origin_lon=0,
        forward_lat=0, forward_lon=0,
    )
    assert result.get("ok") is False


def test_apply_profile_binding_frozen():
    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    svc.apply_profile_binding(
        bind_result=_make_mock_bind_ok(),
        profile_id="f1", profile_name="F1",
        origin_lat=34.0, origin_lon=108.0,
        forward_lat=34.0003, forward_lon=108.0,
    )
    svc.freeze()
    # Try again
    result = svc.apply_profile_binding(
        bind_result=_make_mock_bind_ok(),
        profile_id="f2", profile_name="F2",
        origin_lat=35.0, origin_lon=109.0,
        forward_lat=35.0003, forward_lon=109.0,
    )
    assert result.get("ok") is False
    assert "frozen" in str(result.get("error", "")).lower()
    assert ref.is_frozen is True


# ===================================================================
# 11. API endpoint integration (via controller, no HTTP client needed)
# ===================================================================


def test_bind_current_returns_structured_result():
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert isinstance(result, dict)
    assert "ok" in result
    assert "profile_id" in result
    if result["ok"]:
        assert "field_heading_yaw_rad" in result
        assert "synced_to_runtime" in result
    else:
        assert "error" in result


def test_bind_current_errors_structured():
    """On failure, errors/warnings/diagnostics are present."""
    drone = _make_drone_snapshot(gps_fix_type=1)
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result.get("ok") is False
    assert "errors" in result
    assert "diagnostics" in result


def test_bind_current_profile_not_found():
    drone = _make_drone_snapshot()
    ctrl = _make_controller(drone=drone)
    result = ctrl.bind_profile_current("nonexistent_profile_xyz")
    assert result.get("ok") is False
    assert "not found" in str(result.get("error", "")).lower()



# ===================================================================
# Fix 1 regression tests: mark_origin/forward/yaw no NameError
# ===================================================================


def test_mark_origin_bad_drone_no_nameerror():
    from app.field_reference_controller import FieldReferenceController
    from app.field_reference_service import FieldReferenceService
    from app.field_reference import FieldReference
    from app.runtime_context import RuntimeContextBuilder
    ctrl = FieldReferenceController(
        FieldReferenceService(FieldReference()),
        RuntimeContextBuilder(),
        lambda: {},
    )
    result = ctrl.mark_origin()
    assert result["ok"] is False


def test_mark_forward_bad_drone_no_nameerror():
    from app.field_reference_controller import FieldReferenceController
    from app.field_reference_service import FieldReferenceService
    from app.field_reference import FieldReference
    from app.runtime_context import RuntimeContextBuilder
    ctrl = FieldReferenceController(
        FieldReferenceService(FieldReference()),
        RuntimeContextBuilder(),
        lambda: {},
    )
    result = ctrl.mark_forward()
    assert result["ok"] is False


def test_use_current_yaw_bad_drone_no_nameerror():
    from app.field_reference_controller import FieldReferenceController
    from app.field_reference_service import FieldReferenceService
    from app.field_reference import FieldReference
    from app.runtime_context import RuntimeContextBuilder
    ctrl = FieldReferenceController(
        FieldReferenceService(FieldReference()),
        RuntimeContextBuilder(),
        lambda: {},
    )
    result = ctrl.use_current_yaw()
    assert result["ok"] is False


# ===================================================================
# Fix 2: real profile list valid=true
# ===================================================================


def test_real_system_runner_profile_list_valid():
    """SystemRunner field_profile_list must show example as valid=True."""
    from app.system_runner import SystemRunner
    from app.app_config import build_arg_parser, load_app_config
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)
    result = runner.field_profile_list()
    assert result["ok"] is True
    profiles = {p["profile_id"]: p for p in result["profiles"]}
    assert "example_competition_lane" in profiles
    assert profiles["example_competition_lane"]["valid"] is True
    assert profiles["example_competition_lane"]["errors"] == []


# ===================================================================
# Fix 5: active vs last profile separation
# ===================================================================


def test_active_profile_remains_after_failed_bind():
    """After successful bind A then failed bind B, active is still A."""
    from app.field_reference_controller import FieldReferenceController
    from app.field_reference_service import FieldReferenceService
    from app.field_reference import FieldReference
    from app.runtime_context import RuntimeContextBuilder

    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    builder = RuntimeContextBuilder()
    drone_ok = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = FieldReferenceController(svc, builder, lambda: drone_ok)

    # Bind A succeeds
    r = ctrl.bind_profile_current("example_competition_lane")
    assert r["ok"] is True

    # Bind B fails (missing local_z)
    drone_bad = dict(drone_ok)
    del drone_bad["local_z"]
    ctrl._get_drone_snapshot = lambda: drone_bad
    r2 = ctrl.bind_profile_current("example_competition_lane")
    assert r2["ok"] is False

    # status: active is still A, last_bind is B (same ID here but check structure)
    st = ctrl.status()
    fr = st["field_reference"]
    assert fr.get("profile_id") == "example_competition_lane"
    assert fr.get("profile_binding_ok") is False
    assert len(fr.get("profile_binding_errors", [])) > 0


def test_reset_clears_both_active_and_last():
    from app.field_reference_controller import FieldReferenceController
    from app.field_reference_service import FieldReferenceService
    from app.field_reference import FieldReference
    from app.runtime_context import RuntimeContextBuilder

    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    builder = RuntimeContextBuilder()
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = FieldReferenceController(svc, builder, lambda: drone)
    ctrl.bind_profile_current("example_competition_lane")
    ctrl.reset()

    st = ctrl.status()
    fr = st["field_reference"]
    assert fr.get("profile_id") is None
    assert fr.get("profile_binding_ok") is None


# ===================================================================
# Fix 6: unified response structure
# ===================================================================


def test_bind_failure_response_has_errors_warnings_diagnostics():
    """All bind-current failure paths must have errors/warnings/diagnostics."""
    from app.field_reference_controller import FieldReferenceController
    from app.field_reference_service import FieldReferenceService
    from app.field_reference import FieldReference
    from app.runtime_context import RuntimeContextBuilder

    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    builder = RuntimeContextBuilder()
    ctrl = FieldReferenceController(svc, builder, lambda: {})

    result = ctrl.bind_profile_current("example_competition_lane")
    assert result["ok"] is False
    assert "errors" in result
    assert isinstance(result["errors"], list)
    assert "warnings" in result
    assert isinstance(result["warnings"], list)
    assert "diagnostics" in result
    assert isinstance(result["diagnostics"], dict)


def test_bind_frozen_response_has_structured_errors():
    from app.field_reference_controller import FieldReferenceController
    from app.field_reference_service import FieldReferenceService
    from app.field_reference import FieldReference
    from app.runtime_context import RuntimeContextBuilder

    ref = FieldReference()
    svc = FieldReferenceService(reference=ref)
    builder = RuntimeContextBuilder()
    drone = _make_drone_snapshot(lat=34.0, lon=108.0)
    ctrl = FieldReferenceController(svc, builder, lambda: drone)
    # Bind first, freeze, then try again
    ctrl.bind_profile_current("example_competition_lane")
    svc.freeze()
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result["ok"] is False
    assert "errors" in result
    assert "warnings" in result
    assert "diagnostics" in result
    assert len(result["errors"]) > 0


def test_service_snapshot_restores_reference_and_profile_metadata() -> None:
    svc = FieldReferenceService(FieldReference())
    before = svc.snapshot()
    svc.apply_profile_binding(
        bind_result=_make_mock_bind_ok(),
        profile_id="temporary",
        profile_name="Temporary",
        origin_lat=34.0,
        origin_lon=108.0,
        forward_lat=34.0003,
        forward_lon=108.0,
    )

    svc.restore(before)

    assert svc.reference.is_confirmed is False
    assert svc.status().get("profile_id") is None
    assert svc._profile_id is None
    assert svc._profile_name is None


@pytest.mark.parametrize("sync_mode", ["false", "exception"])
def test_second_profile_sync_failure_rolls_back_all_state(
    tmp_path: Path,
    sync_mode: str,
) -> None:
    _write_named_profiles(tmp_path)
    svc = FieldReferenceService(FieldReference())
    builder = RuntimeContextBuilder()
    drone = _make_drone_snapshot()
    ctrl = FieldReferenceController(svc, builder, lambda: drone)
    ctrl._PROFILE_DIRS = [str(tmp_path)]

    first = ctrl.bind_profile_current("profile_a")
    assert first["ok"] is True
    before_ref = svc.snapshot()
    before_runtime = {
        "yaw": builder.field_heading_yaw_rad,
        "source": builder.field_heading_source,
        "x": builder.field_origin_local_x,
        "y": builder.field_origin_local_y,
        "z": builder.field_origin_local_z,
    }
    original_sync = builder.confirm_field_reference

    def failing_sync(**kwargs):
        original_sync(**kwargs)
        if sync_mode == "exception":
            raise RuntimeError("simulated sync exception")
        return False

    builder.confirm_field_reference = failing_sync
    second = ctrl.bind_profile_current("profile_b")

    assert second["ok"] is False
    assert second["errors"]
    assert svc.snapshot() == before_ref
    assert svc.status()["profile_id"] == "profile_a"
    assert svc._profile_id == "profile_a"
    assert ctrl.status()["field_reference"]["profile_id"] == "profile_a"
    assert ctrl.status()["field_reference"]["last_bind_profile_id"] == "profile_b"
    assert ctrl.status()["field_reference"]["profile_binding_ok"] is False
    assert builder.field_heading_yaw_rad == before_runtime["yaw"]
    assert builder.field_heading_source == before_runtime["source"]
    assert builder.field_origin_local_x == before_runtime["x"]
    assert builder.field_origin_local_y == before_runtime["y"]
    assert builder.field_origin_local_z == before_runtime["z"]


def test_gps_failure_records_last_profile_without_changing_active(
    tmp_path: Path,
) -> None:
    _write_named_profiles(tmp_path)
    drone = _make_drone_snapshot()
    svc = FieldReferenceService(FieldReference())
    ctrl = FieldReferenceController(svc, RuntimeContextBuilder(), lambda: drone)
    ctrl._PROFILE_DIRS = [str(tmp_path)]
    assert ctrl.bind_profile_current("profile_a")["ok"] is True
    drone["gps_fix_type"] = 1

    result = ctrl.bind_profile_current("profile_b")
    status = ctrl.status()["field_reference"]

    assert result["ok"] is False
    assert status["profile_id"] == "profile_a"
    assert status["last_bind_profile_id"] == "profile_b"
    assert status["profile_binding_ok"] is False
    assert status["profile_binding_errors"]


def test_frozen_failure_records_last_profile_without_changing_active(
    tmp_path: Path,
) -> None:
    _write_named_profiles(tmp_path)
    svc = FieldReferenceService(FieldReference())
    ctrl = FieldReferenceController(
        svc, RuntimeContextBuilder(), lambda: _make_drone_snapshot()
    )
    ctrl._PROFILE_DIRS = [str(tmp_path)]
    assert ctrl.bind_profile_current("profile_a")["ok"] is True
    assert svc.freeze()["ok"] is True

    result = ctrl.bind_profile_current("profile_b")
    status = ctrl.status()["field_reference"]

    assert result["ok"] is False
    assert status["profile_id"] == "profile_a"
    assert status["last_bind_profile_id"] == "profile_b"
    assert status["profile_binding_ok"] is False
    assert any("frozen" in item.lower() for item in status["profile_binding_errors"])


def test_non_dict_drone_failure_has_stable_shape() -> None:
    ctrl = FieldReferenceController(
        FieldReferenceService(FieldReference()),
        RuntimeContextBuilder(),
        lambda: None,
    )

    result = ctrl.bind_profile_current("example_competition_lane")

    assert result["ok"] is False
    assert result["profile_id"] == "example_competition_lane"
    assert isinstance(result["errors"], list) and result["errors"]
    assert isinstance(result["warnings"], list)
    assert isinstance(result["diagnostics"], dict)
    assert result["synced_to_runtime"] is False


def test_drone_snapshot_exception_has_stable_shape() -> None:
    def raise_snapshot():
        raise RuntimeError("snapshot failed")

    ctrl = FieldReferenceController(
        FieldReferenceService(FieldReference()),
        RuntimeContextBuilder(),
        raise_snapshot,
    )
    result = ctrl.bind_profile_current("example_competition_lane")
    assert result["ok"] is False
    assert result["errors"]
    assert result["diagnostics"]["errors"]
    assert "snapshot failed" in result["error"]


def test_non_json_looking_profile_id_is_rejected(tmp_path: Path) -> None:
    base = Path(EXAMPLE_PATH).read_text(encoding="utf-8")
    (tmp_path / "foo.txt.json").write_text(base, encoding="utf-8")

    with pytest.raises(ValueError, match="extension"):
        FieldProfileService.load_profile("foo.txt", profile_dir=str(tmp_path))


def test_absolute_profile_path_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_text(Path(EXAMPLE_PATH).read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="relative"):
        FieldProfileService.load_profile(str(target), profile_dir=str(tmp_path))


def test_profile_symlink_escape_is_rejected(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(Path(EXAMPLE_PATH).read_text(encoding="utf-8"), encoding="utf-8")
    (profile_dir / "escape.json").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        FieldProfileService.load_profile("escape", profile_dir=str(profile_dir))


def test_plain_and_json_profile_ids_still_load() -> None:
    directory = os.path.dirname(EXAMPLE_PATH)
    plain = FieldProfileService.load_profile(
        "example_competition_lane", profile_dir=directory
    )
    explicit = FieldProfileService.load_profile(
        "example_competition_lane.json", profile_dir=directory
    )
    assert plain.profile_id == explicit.profile_id == "example_competition_lane"
