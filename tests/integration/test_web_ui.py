"""Integration tests for Web UI routes — centerline-only field reference."""
from __future__ import annotations

import asyncio
from pathlib import Path
import threading

from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

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

    # Competition panel uses inline setText helper and UavApi
    assert "function setText(id, text)" in source
    assert "window.UavApi" in source or "var api = window.UavApi" in source
    # Competition-specific elements
    for field in (
        "cfsForwardLat",
        "cfsForwardLon",
        "cfsStart",
        "cfsFinalize",
        "cfsCancel",
        "cfsReset",
        "onFieldReferenceStatus",
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
        "/static/js/field_profile.js",
        "/static/app.js",
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


def test_get_action_status_is_read_only():
    runner = _make_runner()
    runner.action_lab_tick = lambda: (_ for _ in ()).throw(
        AssertionError("GET status must not advance an Action")
    )
    runner.action_lab_status_payload = lambda: {
        "status": {"state": "running"},
        "send_actions_effective": False,
    }
    app = _make_app(runner)

    result = _endpoint(app, "GET", "/api/actions/status")()

    assert result["ok"] is True
    assert result["action_lab"]["status"]["state"] == "running"


def test_status_websocket_snapshot_does_not_block_event_loop_or_overlap():
    runner = _make_runner()
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    active = 0
    max_active = 0
    worker_thread_ids = []

    def blocking_snapshot():
        nonlocal calls, active, max_active
        calls += 1
        active += 1
        max_active = max(max_active, active)
        worker_thread_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(timeout=2.0)
        active -= 1
        return {"sequence": calls}

    runner.web_status_snapshot = blocking_snapshot
    app = _make_app(runner)
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/ws/status"
    )

    class DisconnectAfterOneMessage:
        async def accept(self):
            return None

        async def send_json(self, _snapshot):
            raise WebSocketDisconnect()

    async def scenario():
        main_thread_id = threading.get_ident()
        websocket_task = asyncio.create_task(endpoint(DisconnectAfterOneMessage()))
        assert await asyncio.to_thread(entered.wait, 1.0)
        heartbeat_completed = False

        async def heartbeat():
            nonlocal heartbeat_completed
            await asyncio.sleep(0.01)
            heartbeat_completed = True

        await heartbeat()
        assert heartbeat_completed is True
        release.set()
        await asyncio.wait_for(websocket_task, timeout=1.0)
        return main_thread_id

    main_thread_id = asyncio.run(scenario())

    assert calls == 1
    assert max_active == 1
    assert worker_thread_ids[0] != main_thread_id


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
