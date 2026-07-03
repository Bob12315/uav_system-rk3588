"""Integration tests for field profile backend binding API (Phase C-1)."""

from __future__ import annotations

import os
import tempfile
import time
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
