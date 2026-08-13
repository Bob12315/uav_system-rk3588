"""Archived pre-single-source Field implementation tests.

Tests the new POST /api/field-reference/runtime-sampling/start endpoint
via the FieldService in real production paths.
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from field.profile import (
    load_field_profile_json,
)
from field.models import (
    normalize_longitude_deg,
)
from field.service import FieldService
from field.reference_service import FieldReferenceService
from field.context import RuntimeContextBuilder
from field.binding_orchestrator import RuntimeBindingOrchestrator
from field.coordinates import field_to_gps_from_origin
from app.config import build_arg_parser, load_app_config
from application.runner import SystemRunner
from web_ui.server import create_app


# ── helpers ──────────────────────────────────────────────────────────────────

def _drone_snapshot():
    return {
        "global_position_valid": True,
        "lat": 34.1234,
        "lon": 108.5678,
        "last_global_position_time": 1000.0,
        "gps_fix_type": 3,
        "satellites_visible": 12,
        "gps_eph": 1.0,
        "gps_epv": 2.0,
        "local_position_valid": False,
        "attitude_valid": False,
    }


def _make_controller():
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder(logger=MagicMock())
    return FieldService(builder, _drone_snapshot, field_reference_service=svc)


def _read_template():
    return load_field_profile_json(
        "config/field_profiles/competition_runtime_v3.json"
    )


def _sample_competition_baseline(distance_m):
    ctl = _make_controller()
    origin = _drone_snapshot()
    marker = field_to_gps_from_origin(
        0.0,
        distance_m,
        0.0,
        origin_lat=origin["lat"],
        origin_lon=origin["lon"],
        field_heading_yaw_rad=0.0,
    )
    assert ctl.start_competition_runtime_sampling(
        marker.lat, marker.lon, started_at_s=1000.0
    )["ok"] is True
    for index in range(21):
        snapshot = dict(origin)
        snapshot["last_global_position_time"] = 2000.0 + index
        ctl.observe_runtime_profile_sampling(
            snapshot, observed_at_s=1000.0 + index * 0.6
        )
    return ctl


# ── template validation ──────────────────────────────────────────────────────


class TestTemplate:
    def test_template_loads(self):
        p = _read_template()
        assert p.profile_id == "competition_runtime_v3"
        assert p.schema_version == 3

    def test_template_is_template_only(self):
        p = _read_template()
        assert p.extra.get("template_only") is True

    def test_template_geometry_fixed(self):
        p = _read_template()
        assert p.field_geometry.lane_half_width_m == 4.0
        assert p.field_geometry.drop_area_y_min == 30.0
        assert p.field_geometry.drop_area_y_max == 35.0

    def test_template_drop_scan_4_waypoints(self):
        p = _read_template()
        assert len(p.drop_scan.waypoints) == 4

    def test_template_gps_quality_fixed(self):
        p = _read_template()
        assert p.gps_quality.min_fix_type == 3
        assert p.gps_quality.min_satellites == 10
        assert p.gps_quality.max_eph == 2.5
        assert p.gps_quality.max_epv == 5.0

    def test_template_sampling_policy_fixed(self):
        p = _read_template()
        assert p.runtime_origin_sampling.min_samples == 20
        assert p.runtime_origin_sampling.sample_window_s == 12.0
        assert p.runtime_origin_sampling.max_horizontal_spread_m == 1.0
        assert p.runtime_origin_sampling.estimator == "median"

    def test_template_binding_policy_fixed(self):
        p = _read_template()
        assert p.binding_policy.min_baseline_m == 30.0
        assert p.binding_policy.warn_baseline_below_m == 50.0

    def test_template_placeholder_is_placeholder(self):
        p = _read_template()
        assert "placeholder" in p.forward_marker.name

    def test_template_disk_unchanged_after_controller_use(self):
        """Template file on disk must not be modified by session creation."""
        path = "config/field_profiles/competition_runtime_v3.json"
        before = Path(path).read_bytes()
        ctl = _make_controller()
        result = ctl.start_competition_runtime_sampling(
            34.1234567, 108.1234567, started_at_s=1000.0
        )
        assert result["ok"] is True
        after = Path(path).read_bytes()
        assert before == after, "template file modified on disk!"


# ── competition start endpoint ───────────────────────────────────────────────


class TestCompetitionStart:
    def test_valid_float_B_starts(self):
        ctl = _make_controller()
        result = ctl.start_competition_runtime_sampling(
            forward_marker_lat=34.1234567,
            forward_marker_lon=108.1234567,
            started_at_s=1000.0,
        )
        assert result.get("ok") is True
        assert result.get("state") == "sampling"

    def test_valid_int_B_starts(self):
        ctl = _make_controller()
        result = ctl.start_competition_runtime_sampling(
            forward_marker_lat=34.0,
            forward_marker_lon=108.0,
            started_at_s=1000.0,
        )
        assert result.get("ok") is True

    def test_lon_canonical_normalization(self):
        """Longitude 540 should normalize to 180 (canonical [-180,180))."""
        result = normalize_longitude_deg(540.0)
        assert -180.0 <= result < 180.0

    def test_double_start_returns_conflict(self):
        ctl = _make_controller()
        ctl.start_competition_runtime_sampling(34.0, 108.0, started_at_s=1000.0)
        result = ctl.start_competition_runtime_sampling(35.0, 109.0, started_at_s=1001.0)
        assert result.get("ok") is False
        assert result.get("state") == "sampling"

    def test_applied_blocks_start(self):
        ctl = _make_controller()
        # Force applied state
        ctl._runtime_binding._state = "applied"
        result = ctl.start_competition_runtime_sampling(34.0, 108.0, started_at_s=1000.0)
        assert result.get("ok") is False
        assert "applied" in str(result.get("error", "")).lower()

    def test_frozen_blocks_start(self):
        ctl = _make_controller()
        ctl._svc.reference.is_frozen = True
        result = ctl.start_competition_runtime_sampling(34.0, 108.0, started_at_s=1000.0)
        assert result.get("ok") is False
        assert "frozen" in str(result.get("error", "")).lower()

    def test_session_B_in_profile(self):
        ctl = _make_controller()
        ctl.start_competition_runtime_sampling(
            forward_marker_lat=34.1234567,
            forward_marker_lon=108.1234567,
            started_at_s=1000.0,
        )
        # Verify session metadata stored in orchestrator
        status = ctl._runtime_binding.status()
        assert status.get("template_profile_id") == "competition_runtime_v3"
        assert status.get("runtime_profile_id") == "competition_runtime_session"
        assert status.get("input_source") == "web_ui_runtime"
        assert status.get("forward_marker_lat") == pytest.approx(34.1234567)
        assert status.get("forward_marker_lon") == pytest.approx(108.1234567)

    def test_cancel_clears_session(self):
        ctl = _make_controller()
        ctl.start_competition_runtime_sampling(34.0, 108.0, started_at_s=1000.0)
        ctl.cancel_runtime_profile_sampling()
        status = ctl._runtime_binding.status()
        assert status.get("state") == "idle"
        assert status.get("template_profile_id") is None
        assert status.get("forward_marker_lat") is None

    def test_reset_clears_everything(self):
        ctl = _make_controller()
        ctl.start_competition_runtime_sampling(34.0, 108.0, started_at_s=1000.0)
        ctl.reset()
        status = ctl._runtime_binding.status()
        assert status.get("state") == "idle"
        assert ctl._svc.reference.is_confirmed is False
        assert ctl._svc.reference.is_frozen is False

    def test_applied_cancel_rejected(self):
        ctl = _make_controller()
        ctl._runtime_binding._state = "applied"
        result = ctl.cancel_runtime_profile_sampling()
        assert result.get("ok") is False
        assert "applied" in str(result.get("error", "")).lower()

    @pytest.mark.parametrize(
        "state",
        ["sampling", "sampling_failed", "candidate_ready", "apply_failed", "applied", "unexpected"],
    )
    def test_orchestrator_defensively_rejects_every_non_idle_state(self, state):
        orchestrator = RuntimeBindingOrchestrator(
            FieldReferenceService(), RuntimeContextBuilder()
        )
        orchestrator._state = state
        candidate = object()
        orchestrator._candidate = candidate
        result = orchestrator.start(_read_template(), started_at_s=1000.0)
        assert result["ok"] is False
        assert result["state"] == state
        assert orchestrator._candidate is candidate


# ── template-only rejection ──────────────────────────────────────────────────


class TestTemplateOnlyRejection:
    def test_template_only_rejected_by_old_start(self):
        ctl = _make_controller()
        result = ctl.start_runtime_profile_sampling(
            "competition_runtime_v3", started_at_s=1000.0
        )
        assert result.get("ok") is False
        assert "template-only" in str(result.get("error", "")).lower()

# ── preview / finalize consistency ───────────────────────────────────────────


class TestPreviewFinalize:
    def test_preview_no_side_effects(self):
        from field.calibration import RuntimeFieldBindingSampler
        profile = _read_template()
        sampler = RuntimeFieldBindingSampler(profile)
        sampler.start(started_at_s=1000.0)
        # Feed 25 valid samples
        for i in range(25):
            s = {
                "global_position_valid": True,
                "lat": 34.0003 + i * 0.0000005,
                "lon": 108.0 + i * 0.0000005,
                "last_global_position_time": float(1000 + i),
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "gps_eph": 1.0,
                "gps_epv": 2.0,
            }
            sampler.observe_snapshot(s, observed_at_s=1000.0 + i * 0.2)
        state_before = sampler._state
        # Preview should not change state
        candidate = sampler.preview_candidate(completed_at_s=1012.0)
        assert sampler._state == state_before
        assert sampler._candidate is None  # preview doesn't set _candidate
        assert candidate.origin_lat is not None

    def test_preview_and_finalize_same_result(self):
        from field.calibration import RuntimeFieldBindingSampler
        profile = _read_template()
        sampler = RuntimeFieldBindingSampler(profile)
        sampler.start(started_at_s=2000.0)
        for i in range(30):
            s = {
                "global_position_valid": True,
                "lat": 34.0003 + i * 0.0000002,
                "lon": 108.0 + i * 0.0000002,
                "last_global_position_time": float(2000 + i),
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "gps_eph": 1.0,
                "gps_epv": 2.0,
            }
            sampler.observe_snapshot(s, observed_at_s=2000.0 + i * 0.2)
        preview = sampler.preview_candidate(completed_at_s=2012.0)
        # Reset to re-run finalize from scratch
        sampler._candidate = None
        sampler._state = "sampling"
        final = sampler.finalize(completed_at_s=2012.0)
        assert preview.origin_lat == final.origin_lat
        assert preview.origin_lon == final.origin_lon
        assert preview.baseline_m == final.baseline_m
        assert preview.field_heading_yaw_rad == final.field_heading_yaw_rad
        assert preview.horizontal_spread_m == final.horizontal_spread_m

    def test_insufficient_samples_can_finalize_false(self):
        from field.calibration import RuntimeFieldBindingSampler
        profile = _read_template()
        sampler = RuntimeFieldBindingSampler(profile)
        sampler.start(started_at_s=3000.0)
        # Only 5 samples (need 20)
        for i in range(5):
            s = {
                "global_position_valid": True,
                "lat": 34.0003 + i * 0.0000005,
                "lon": 108.0 + i * 0.0000005,
                "last_global_position_time": float(3000 + i),
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "gps_eph": 1.0,
                "gps_epv": 2.0,
            }
            sampler.observe_snapshot(s, observed_at_s=3000.0 + i * 0.2)
        status = sampler.status(now_s=3006.0)
        assert status.can_finalize is False
        with pytest.raises(Exception):
            sampler.preview_candidate(completed_at_s=3012.0)

    def test_spread_exceeds_can_finalize_false(self):
        from field.calibration import RuntimeFieldBindingSampler
        profile = _read_template()
        sampler = RuntimeFieldBindingSampler(profile)
        sampler.start(started_at_s=4000.0)
        # Wide spread (10km apart)
        for i in range(25):
            s = {
                "global_position_valid": True,
                "lat": 34.0 + i * 0.05,  # ~5.5 km apart each
                "lon": 108.0 + i * 0.05,
                "last_global_position_time": float(4000 + i),
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "gps_eph": 1.0,
                "gps_epv": 2.0,
            }
            sampler.observe_snapshot(s, observed_at_s=4000.0 + i * 0.2)
        with pytest.raises(Exception):
            sampler.preview_candidate(completed_at_s=4012.0)
        assert sampler._state != "ready"


class TestBaselineWarningLifecycle:
    def test_below_minimum_baseline_fails_and_cannot_finalize(self):
        ctl = _sample_competition_baseline(20.0)
        status = ctl._runtime_binding.status(now_s=1013.0)
        assert status["state"] == "sampling_failed"
        assert status["sampling"]["can_finalize"] is False
        result = ctl.finalize_runtime_profile_binding(completed_at_s=1012.0)
        assert result["ok"] is False
        assert result["state"] == "sampling_failed"

    def test_warning_baseline_survives_automatic_finalize(self):
        ctl = _sample_competition_baseline(40.0)
        status = ctl._runtime_binding.status(now_s=1013.0)
        warnings = status["candidate_summary"]["warnings"]
        assert any("below warning threshold" in warning for warning in warnings)

        result = status["last_result"]
        assert result["ok"] is True
        assert result["state"] == "applied"
        assert any("below warning threshold" in warning for warning in result["warnings"])
        retained = ctl._runtime_binding.status()["candidate_summary"]["warnings"]
        assert retained == result["warnings"]

    def test_automatic_finalize_retains_orchestrator_baseline_warning(self):
        ctl = _sample_competition_baseline(40.0)
        orchestrator = ctl._runtime_binding
        warnings = orchestrator.status(now_s=1013.0)["candidate_summary"]["warnings"]
        assert any("below warning threshold" in warning for warning in warnings)

    def test_baseline_at_warning_threshold_has_no_baseline_warning(self):
        ctl = _sample_competition_baseline(50.0)
        status = ctl._runtime_binding.status(now_s=1013.0)
        warnings = status["candidate_summary"]["warnings"]
        assert not any("below warning threshold" in warning for warning in warnings)


# ── status payload ───────────────────────────────────────────────────────────


class TestStatusPayload:
    def test_status_includes_telemetry_lat_lon(self):
        ctl = _make_controller()
        status = ctl.status()
        telemetry = status.get("telemetry", {})
        assert "lat" in telemetry
        assert "lon" in telemetry
        assert "last_global_position_time" in telemetry

    def test_status_includes_runtime_binding_fields(self):
        ctl = _make_controller()
        ctl.start_competition_runtime_sampling(34.0, 108.0, started_at_s=1000.0)
        status = ctl.status()
        fr = status.get("field_reference", {})
        rb = fr.get("runtime_binding", {})
        assert "template_profile_id" in rb
        assert "runtime_profile_id" in rb
        assert "input_source" in rb
        assert "forward_marker_lat" in rb
        assert "forward_marker_lon" in rb
        assert "preview_error" in rb
        assert "sampling" in rb

    def test_sampling_failed_still_returns_sampling_data(self):
        from field.calibration import RuntimeFieldBindingSampler
        profile = _read_template()
        sampler = RuntimeFieldBindingSampler(profile)
        sampler.start(started_at_s=5000.0)
        for i in range(5):
            s = {
                "global_position_valid": True,
                "lat": 34.0003 + i * 0.0000005,
                "lon": 108.0 + i * 0.0000005,
                "last_global_position_time": float(5000 + i),
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "gps_eph": 1.0,
                "gps_epv": 2.0,
            }
            sampler.observe_snapshot(s, observed_at_s=5000.0 + i * 0.2)
        # Force failed state
        sampler._state = "failed"
        sampler._completed_at_s = 5006.0
        status = sampler.status(now_s=5006.0)
        # Should still return sampling data even in failed state
        assert status.state != "idle"
        assert status.accepted_samples == 5


# ── schema v2 retirement ────────────────────────────────────────────────────


class TestSchemaV3Only:
    def test_controller_has_no_v2_bind_current_entrypoint(self):
        ctl = _make_controller()
        assert not hasattr(ctl, "bind_profile_current")
        assert hasattr(ctl, "start_runtime_profile_sampling")
        assert hasattr(ctl, "start_competition_runtime_sampling")


# ── no mission/flight calls ──────────────────────────────────────────────────


class TestNoFlightCalls:
    def test_controller_imports_no_link_manager(self):
        src = Path("field/service.py").read_text()
        assert "LinkManager" not in src
        assert "send_body_velocity" not in src
        assert "set_servo" not in src

    def test_orchestrator_imports_no_link_manager(self):
        src = Path("field/binding_orchestrator.py").read_text()
        assert "LinkManager" not in src

    def test_system_runner_competition_method_safe(self):
        src = Path("application/runner.py").read_text()
        # The competition method should only call controller
        method_start = src.find("def competition_runtime_sampling_start")
        method_end = src.find("\n    def ", method_start + 10)
        if method_end < 0:
            method_end = len(src)
        method_body = src[method_start:method_end]
        assert "LinkManager" not in method_body
        assert "dispatcher" not in method_body
        assert "set_servo" not in method_body


# ── real ASGI endpoint coverage ─────────────────────────────────────────────


def _make_http_app(tmp_path):
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    config = load_app_config(args)
    config.ui.audit_log_path = str(tmp_path / "audit.jsonl")
    config.ui.allowed_hosts = (*config.ui.allowed_hosts, "testserver")
    runner = SystemRunner(config)
    return create_app(runner, config.ui), runner


def _asgi_request(app, method, path, *, json_body=None, content=None):
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            kwargs = {"headers": {"authorization": "Bearer test-only-operator-password"}}
            if json_body is not None:
                kwargs["json"] = json_body
            if content is not None:
                kwargs["content"] = content
                kwargs["headers"]["content-type"] = "application/json"
            return await client.request(method, path, **kwargs)

    return asyncio.run(request())


@pytest.mark.parametrize(
    "payload",
    [
        {"forward_marker_lat": 34.25, "forward_marker_lon": 108.25},
        {"forward_marker_lat": 34, "forward_marker_lon": 108},
    ],
)
def test_competition_start_http_accepts_real_numbers(tmp_path, payload):
    app, _runner = _make_http_app(tmp_path)
    response = _asgi_request(
        app, "POST", "/api/field-reference/runtime-sampling/start", json_body=payload
    )
    assert response.status_code == 200
    assert response.json()["state"] == "sampling"


@pytest.mark.parametrize(
    "payload",
    [
        {"forward_marker_lat": True, "forward_marker_lon": 108.0},
        {"forward_marker_lat": "34.0", "forward_marker_lon": 108.0},
        {"forward_marker_lat": None, "forward_marker_lon": 108.0},
        {"forward_marker_lon": 108.0},
        {"forward_marker_lat": 34.0, "forward_marker_lon": 108.0, "extra": 1},
    ],
)
def test_competition_start_http_rejects_invalid_structure(tmp_path, payload):
    app, _runner = _make_http_app(tmp_path)
    response = _asgi_request(
        app, "POST", "/api/field-reference/runtime-sampling/start", json_body=payload
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "content",
    [
        '{"forward_marker_lat": NaN, "forward_marker_lon": 108.0}',
        '{"forward_marker_lat": 34.0, "forward_marker_lon": Infinity}',
    ],
)
def test_competition_start_http_rejects_non_finite(tmp_path, content):
    app, _runner = _make_http_app(tmp_path)
    response = _asgi_request(
        app, "POST", "/api/field-reference/runtime-sampling/start", content=content
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"forward_marker_lat": 90.1, "forward_marker_lon": 108.0},
        {"forward_marker_lat": 34.0, "forward_marker_lon": 180.1},
        {"forward_marker_lat": 90.0, "forward_marker_lon": 108.0},
    ],
)
def test_competition_start_http_rejects_coordinate_bounds(tmp_path, payload):
    app, _runner = _make_http_app(tmp_path)
    response = _asgi_request(
        app, "POST", "/api/field-reference/runtime-sampling/start", json_body=payload
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "state",
    ["sampling", "sampling_failed", "candidate_ready", "apply_failed", "applied", "unexpected"],
)
def test_competition_start_http_returns_409_for_non_idle_state(tmp_path, state):
    app, runner = _make_http_app(tmp_path)
    binding = runner.field_service._runtime_binding
    binding._state = state
    binding._forward_marker_lat = 35.0
    binding._forward_marker_lon = 109.0
    candidate = object()
    if state == "apply_failed":
        binding._candidate = candidate

    response = _asgi_request(
        app,
        "POST",
        "/api/field-reference/runtime-sampling/start",
        json_body={"forward_marker_lat": 34.0, "forward_marker_lon": 108.0},
    )

    assert response.status_code == 409
    assert response.json()["detail"]
    assert binding._forward_marker_lat == 35.0
    assert binding._forward_marker_lon == 109.0
    if state == "apply_failed":
        assert binding._candidate is candidate


def test_competition_start_http_returns_409_when_frozen(tmp_path):
    app, runner = _make_http_app(tmp_path)
    runner.field_service.reference.is_frozen = True
    response = _asgi_request(
        app,
        "POST",
        "/api/field-reference/runtime-sampling/start",
        json_body={"forward_marker_lat": 34.0, "forward_marker_lon": 108.0},
    )
    assert response.status_code == 409


def test_sampling_failed_http_preserves_real_session_B(tmp_path):
    app, runner = _make_http_app(tmp_path)
    first = _asgi_request(
        app,
        "POST",
        "/api/field-reference/runtime-sampling/start",
        json_body={"forward_marker_lat": 34.25, "forward_marker_lon": 108.25},
    )
    assert first.status_code == 200
    binding = runner.field_service._runtime_binding
    binding._state = "sampling_failed"

    second = _asgi_request(
        app,
        "POST",
        "/api/field-reference/runtime-sampling/start",
        json_body={"forward_marker_lat": 35.0, "forward_marker_lon": 109.0},
    )

    assert second.status_code == 409
    assert binding._forward_marker_lat == pytest.approx(34.25)
    assert binding._forward_marker_lon == pytest.approx(108.25)


def test_cancel_then_competition_start_http_succeeds(tmp_path):
    app, runner = _make_http_app(tmp_path)
    binding = runner.field_service._runtime_binding
    binding._state = "sampling_failed"
    assert binding.cancel()["state"] == "idle"
    response = _asgi_request(
        app,
        "POST",
        "/api/field-reference/runtime-sampling/start",
        json_body={"forward_marker_lat": 34.0, "forward_marker_lon": 108.0},
    )
    assert response.status_code == 200


def test_reset_then_competition_start_http_succeeds(tmp_path):
    app, runner = _make_http_app(tmp_path)
    binding = runner.field_service._runtime_binding
    binding._state = "applied"
    assert runner.field_service.reset()["ok"] is True
    response = _asgi_request(
        app,
        "POST",
        "/api/field-reference/runtime-sampling/start",
        json_body={"forward_marker_lat": 34.0, "forward_marker_lon": 108.0},
    )
    assert response.status_code == 200


def test_regular_v3_profile_starts_through_real_http_endpoint(tmp_path):
    raw = json.loads(Path("config/field_profiles/competition_runtime_v3.json").read_text())
    raw["profile_id"] = "ordinary_v3"
    raw["name"] = "Ordinary v3"
    raw["template_only"] = False
    profile_path = tmp_path / "ordinary_v3.json"
    profile_path.write_text(json.dumps(raw), encoding="utf-8")
    app, runner = _make_http_app(tmp_path)
    runner.field_service._PROFILE_DIRS = [str(tmp_path)]

    response = _asgi_request(
        app, "POST", "/api/field-profiles/ordinary_v3/runtime-sampling/start"
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["state"] == "sampling"
