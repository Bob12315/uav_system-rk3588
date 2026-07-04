"""Integration tests for Web UI routes — centerline-only field reference."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner
from web_ui.server import create_app


_STATIC_DIR = Path(__file__).resolve().parents[2] / "web_ui" / "static"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_runner():
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    runner = SystemRunner(config)

    # Mock drone telemetry for bind-current
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
    for route in app.routes:
        route_path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        if route_path == path and method in methods:
            return route.endpoint
    raise LookupError(f"No route for {method} {path}")


def test_field_profile_frontend_uses_available_dom_helper_and_v2_fields():
    source = (_STATIC_DIR / "js" / "field_profile.js").read_text(encoding="utf-8")

    assert "function setText(element, value, tone)" in source
    assert "dom.setText" not in source
    for field in (
        "data.anchor",
        "data.centerline_points",
        "data.current_start_error_m",
        "data.yaw_error_deg",
        "data.max_residual_m",
        "data.rms_residual_m",
        "data.centerline_residuals",
    ):
        assert field in source


def test_field_profile_frontend_dom_and_script_order_are_current():
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")

    for element_id in (
        "fpClPoints",
        "fpClDetails",
        "fpBindStartError",
        "fpBindYawError",
        "fpBindMaxResidual",
        "fpBindRmsResidual",
        "fpBindResiduals",
    ):
        assert f'id="{element_id}"' in html

    scripts = (
        "/static/js/api_client.js",
        "/static/js/format_utils.js",
        "/static/js/dom_utils.js",
        "/static/js/field_reference.js",
        "/static/js/field_profile.js?v=field-profile-persist-20260704",
        "/static/app.js?v=field-ref-bridge-fix-20260704",
    )
    positions = [html.index(script) for script in scripts]
    assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# status endpoints
# ---------------------------------------------------------------------------


def test_web_status_returns_snapshot():
    app = _make_app()
    fn = _endpoint(app, "GET", "/api/status")
    result = fn()
    assert "mission" in result
    assert "action_lab" in result


def test_web_field_reference_status():
    app = _make_app()
    fn = _endpoint(app, "GET", "/api/field-reference/status")
    result = fn()
    assert result["ok"] is True
    fr = result["field_reference"]
    assert "is_confirmed" in fr
    assert "active_source" in fr
    assert "synced_to_runtime" in fr


def test_web_action_mission_status():
    app = _make_app()
    fn = _endpoint(app, "GET", "/api/action-mission/status")
    result = fn()
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# profile endpoints
# ---------------------------------------------------------------------------


def test_web_field_profiles_list():
    app = _make_app()
    fn = _endpoint(app, "GET", "/api/field-profiles")
    result = fn()
    assert result["ok"] is True
    assert isinstance(result.get("profiles"), list)
    assert len(result["profiles"]) >= 1


def test_web_field_profiles_get():
    app = _make_app()
    fn = _endpoint(app, "GET", "/api/field-profiles/{profile_id}")
    result = fn(profile_id="example_competition_lane")
    assert result["ok"] is True
    assert result["profile_id"] == "example_competition_lane"


def test_web_field_profiles_bind_current():
    runner = _make_runner()
    app = create_app(runner, runner.config.ui)
    fn = _endpoint(app, "POST", "/api/field-profiles/{profile_id}/bind-current")
    result = fn(profile_id="example_competition_lane")
    assert result["ok"] is True
    assert result["synced_to_runtime"] is True
    assert result.get("field_heading_yaw_rad") is not None


# ---------------------------------------------------------------------------
# 410 Gone — old endpoints
# ---------------------------------------------------------------------------


def test_web_old_field_heading_confirm_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-heading/confirm")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410


def test_web_old_mark_origin_410():
    app = _make_app()
    fn = _endpoint(app, "POST", "/api/field-reference/mark-origin")
    try:
        fn()
        assert False, "expected HTTPException 410"
    except HTTPException as e:
        assert e.status_code == 410


def test_web_no_legacy_field_heading_active_source():
    """After bind, active_source must NOT be legacy_field_heading."""
    runner = _make_runner()
    runner.field_profile_bind_current("example_competition_lane")
    status = runner.field_reference_status()
    fr = status["field_reference"]
    assert fr["active_source"] == "field_profile_centerline"
