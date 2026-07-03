"""Tests for /api/field-profiles/* and /api/field-reference/* HTTP endpoints."""
from __future__ import annotations

from fastapi import HTTPException

from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner
from web_ui.server import create_app


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_runner():
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    # Mock drone telemetry so bind-current works without real hardware
    runner.field_reference_controller._get_drone_snapshot = lambda: {
        "global_position_valid": True,
        "lat": 34.0,
        "lon": 108.0,
        "local_position_valid": True,
        "local_x": 10.0,
        "local_y": 20.0,
        "local_z": -1.0,
        "gps_fix_type": 3,
        "satellites_visible": 12,
        "gps_eph": 1.0,
        "gps_epv": 1.0,
        "attitude_valid": True,
        "yaw": 0.3,
    }
    return runner


def _make_app(runner=None):
    if runner is None:
        runner = _make_runner()
    return create_app(runner, runner.config.ui)


def _endpoint(app, method, path):
    """Find a route endpoint function by method and path."""
    for route in app.routes:
        route_path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        if route_path == path and method in methods:
            return route.endpoint
    raise LookupError(f"No route for {method} {path}")


# ---------------------------------------------------------------------------
# profile list
# ---------------------------------------------------------------------------


def test_api_list_profiles():
    runner = _make_runner()
    fn = getattr(runner, "field_profile_list")
    result = fn()
    assert result["ok"] is True
    assert isinstance(result.get("profiles"), list)
    assert len(result["profiles"]) >= 1
    assert any("example_competition_lane" in str(p) for p in result["profiles"])


# ---------------------------------------------------------------------------
# profile get
# ---------------------------------------------------------------------------


def test_api_get_valid_profile():
    runner = _make_runner()
    fn = getattr(runner, "field_profile_get")
    result = fn("example_competition_lane")
    assert result["ok"] is True
    assert result["profile_id"] == "example_competition_lane"
    assert result["schema_version"] == 2
    assert "anchor" in result
    assert "centerline_points" in result


def test_api_get_missing_profile():
    runner = _make_runner()
    fn = getattr(runner, "field_profile_get")
    result = fn("nonexistent_profile_xyz")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# profile validate
# ---------------------------------------------------------------------------


def test_api_validate_valid_profile():
    runner = _make_runner()
    fn = getattr(runner, "field_profile_validate")
    result = fn("example_competition_lane")
    assert result["ok"] is True


def test_api_validate_missing_profile():
    runner = _make_runner()
    fn = getattr(runner, "field_profile_validate")
    result = fn("nonexistent_profile_xyz")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# bind-current
# ---------------------------------------------------------------------------


def test_api_bind_current_success():
    runner = _make_runner()
    fn = getattr(runner, "field_profile_bind_current")
    result = fn("example_competition_lane")
    assert result["ok"] is True
    assert result.get("synced_to_runtime") is True
    assert result.get("field_heading_yaw_rad") is not None
    assert result.get("field_heading_deg") is not None
    assert result.get("origin_local_n_m") is not None
    assert result.get("origin_local_e_m") is not None
    assert result.get("origin_local_z_m") is not None
    assert result.get("current_start_error_m") is not None
    assert result.get("baseline_m") is not None
    assert isinstance(result.get("centerline_residuals"), list)
    assert len(result["centerline_residuals"]) >= 4


def test_api_bind_current_missing_profile():
    runner = _make_runner()
    fn = getattr(runner, "field_profile_bind_current")
    result = fn("nonexistent_profile_xyz")
    assert result["ok"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# field-reference status
# ---------------------------------------------------------------------------


def test_api_field_reference_status_after_bind():
    runner = _make_runner()
    bind_fn = getattr(runner, "field_profile_bind_current")
    bind_fn("example_competition_lane")

    status_fn = getattr(runner, "field_reference_status")
    result = status_fn()
    assert result["ok"] is True
    fr = result["field_reference"]
    assert fr["is_confirmed"] is True
    assert fr["active_source"] == "field_profile_centerline"
    assert fr["synced_to_runtime"] is True


def test_api_field_reference_status_before_bind():
    runner = _make_runner()
    status_fn = getattr(runner, "field_reference_status")
    result = status_fn()
    assert result["ok"] is True
    fr = result["field_reference"]
    assert fr["active_source"] == "none"


# ---------------------------------------------------------------------------
# 410 Gone — old endpoints
# ---------------------------------------------------------------------------


def test_api_field_heading_confirm_returns_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-heading/confirm")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410


def test_api_mark_origin_returns_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-reference/mark-origin")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410


def test_api_mark_forward_returns_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-reference/mark-forward")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410


def test_api_use_current_yaw_returns_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-reference/use-current-yaw")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410


def test_api_set_manual_heading_returns_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-reference/set-manual-heading")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410


def test_api_field_reference_confirm_returns_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-reference/confirm")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410
