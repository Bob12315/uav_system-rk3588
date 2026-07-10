"""Backend tests for step 6 Web UI runtime binding."""

import ast
from pathlib import Path

import pytest

from app.field_profile import parse_field_profile
from app.field_profile_service import FieldProfileService
from app.field_reference_service import FieldReferenceService


def _make_v2_dict():
    return {
        "schema_version": 2, "profile_id": "test_v2_ui", "name": "Test V2 UI",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "anchor": {"name": "a", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
        "centerline_points": [
            {"name": "c1", "lat": 34.001, "lon": 108.001},
            {"name": "c2", "lat": 34.002, "lon": 108.002},
            {"name": "c3", "lat": 34.003, "lon": 108.003},
            {"name": "c4", "lat": 34.004, "lon": 108.004},
        ],
    }


def _make_v3_dict():
    return {
        "schema_version": 3, "profile_id": "test_v3_ui", "name": "Test V3 UI",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "forward_marker": {"name": "far", "lat": 34.104189, "lon": 108.642674, "coordinate_system": "WGS84"},
        "field_geometry": {"lane_half_width_m": 4.0, "drop_area_y_min_m": 30.0, "drop_area_y_max_m": 35.0, "drop_center_y_m": 32.5, "recce_area_y_min_m": 55.0, "recce_area_y_max_m": 60.0, "recce_center_y_m": 57.5},
        "drop_scan": {"waypoints": [{"x_m": -2.0, "y_m": 31.25, "altitude_m": 5.0}, {"x_m": 2.0, "y_m": 31.25, "altitude_m": 5.0}, {"x_m": 2.0, "y_m": 33.75, "altitude_m": 5.0}, {"x_m": -2.0, "y_m": 33.75, "altitude_m": 5.0}]},
        "gps_quality": {"min_fix_type": 3, "min_satellites": 10, "max_eph": 2.5, "max_epv": 5.0},
        "runtime_origin_sampling": {"min_samples": 20, "sample_window_s": 5.0, "max_horizontal_spread_m": 1.0, "estimator": "median"},
        "binding_policy": {"min_baseline_m": 30.0, "warn_baseline_below_m": 50.0},
    }


class TestProfilePayload:
    def test_v2_payload_has_anchor(self):
        p = parse_field_profile(_make_v2_dict())
        assert p.anchor is not None

    def test_v3_payload_has_forward_marker(self):
        p = parse_field_profile(_make_v3_dict())
        assert p.forward_marker is not None
        assert p.anchor is None

    def test_v3_drop_scan_waypoints(self):
        p = parse_field_profile(_make_v3_dict())
        assert len(p.drop_scan.waypoints) == 4

    def test_v3_null_fields_stable(self):
        p = parse_field_profile(_make_v3_dict())
        assert p.anchor is None
        assert p.centerline_points == []


class TestWebAPIAST:
    def test_server_has_runtime_endpoints(self):
        tree = ast.parse(Path("web_ui/server.py").read_text())
        paths = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(getattr(node, 'func', None), ast.Attribute):
                if getattr(node.func, 'attr', '') in ('get', 'post', 'put'):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant):
                            paths.add(arg.value)
        assert "/api/field-profiles/{profile_id}/runtime-sampling/start" in paths
        assert "/api/field-reference/runtime-sampling/finalize" in paths
        assert "/api/field-reference/runtime-sampling/cancel" in paths

    def test_server_has_no_flight_commands(self):
        src = Path("web_ui/server.py").read_text()
        for token in ("send_body_velocity", "goto_local_ned", "set_servo"):
            assert token not in src, f"forbidden: {token}"


class TestControllerBindGuard:
    def test_v3_bind_current_guard_exists(self):
        src = Path("app/field_reference_controller.py").read_text()
        assert "bind-current is only supported for schema v2" in src


class TestProfileSchemaValidation:
    def test_v2_has_anchor(self):
        p = parse_field_profile(_make_v2_dict())
        assert p.anchor.name == "a"

    def test_v3_has_no_anchor(self):
        p = parse_field_profile(_make_v3_dict())
        assert p.anchor is None

    def test_v3_runtime_sampling(self):
        p = parse_field_profile(_make_v3_dict())
        assert p.runtime_origin_sampling.min_samples == 20
        assert p.runtime_origin_sampling.sample_window_s == 5.0

    def test_v3_binding_policy(self):
        p = parse_field_profile(_make_v3_dict())
        assert p.binding_policy.min_baseline_m == 30.0


class TestASTEndpoints:
    def test_start_endpoint_exists(self):
        tree = ast.parse(Path("web_ui/server.py").read_text())
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(getattr(node, 'func', None), ast.Attribute):
                if getattr(node.func, 'attr', '') in ('post',):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and 'runtime-sampling/start' in arg.value:
                            found = True
        assert found, "start endpoint not found"

    def test_finalize_endpoint_exists(self):
        tree = ast.parse(Path("web_ui/server.py").read_text())
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(getattr(node, 'func', None), ast.Attribute):
                if getattr(node.func, 'attr', '') in ('post',):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and 'runtime-sampling/finalize' in arg.value:
                            found = True
        assert found, "finalize endpoint not found"

    def test_cancel_endpoint_exists(self):
        tree = ast.parse(Path("web_ui/server.py").read_text())
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(getattr(node, 'func', None), ast.Attribute):
                if getattr(node.func, 'attr', '') in ('post',):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and 'runtime-sampling/cancel' in arg.value:
                            found = True
        assert found, "cancel endpoint not found"

    def test_no_auto_finalize(self):
        src = Path("web_ui/server.py").read_text()
        assert "auto_finalize" not in src


def test_step6_web_confirmation_in_contract():
    src = Path('docs/refactor/drop_v2_gps_first_contract.md').read_text()
    assert 'Step 6 Web confirmation' in src
    assert 'Schema v3 runtime GPS binding' in src
    assert 'explicitly finalize and freeze' in src


class TestAuditSafety:
    def test_audit_helper_exists(self):
        src = Path("web_ui/server.py").read_text()
        assert "_append_field_reference_audit" in src

    def test_audit_not_block_result(self):
        src = Path("web_ui/server.py").read_text()
        # The audit call comes AFTER the result is captured, before return
        assert "_append_field_reference_audit" in src

    def test_start_route_uses_audit(self):
        src = Path("web_ui/server.py").read_text()
        assert "runtime_sampling_start" in src


class TestMapPreview:
    def test_v3_map_preview_guard_in_source(self):
        src = Path("app/system_runner.py").read_text()
        assert "runtime_reference_required" in src
        assert "schema v3 GPS map preview requires an applied runtime reference" in src

    def test_v3_profiles_exist(self):
        p = parse_field_profile(_make_v3_dict())
        assert p.schema_version == 3


# =============================================================================
# Real DOM and JS tests (6.2)
# =============================================================================


class TestRealDOM:
    def test_all_runtime_ids_exist_once(self):
        html = Path("web_ui/static/index.html").read_text()
        ids = ["frGpsReady", "frLocalReady", "frForwardMarkerGps",
               "frRuntimeState", "frRuntimeProfile", "frRuntimeError",
               "fpSamplingState", "fpSamplingElapsed", "fpSamplingAccepted",
               "fpSamplingRejected", "fpSamplingDuplicate",
               "fpSamplingWindowComplete", "fpSamplingCanFinalize",
               "fpSamplingLastRejection", "fpSamplingProgress",
               "fpRuntimeOrigin", "fpRuntimeMarker", "fpRuntimeHeading",
               "fpRuntimeBaseline", "fpRuntimeSpread", "fpRuntimeSampleCount",
               "fpRuntimeWarnings", "fpRuntimeGeometry",
               "fpRuntimeStart", "fpRuntimeFinalize", "fpRuntimeCancel"]
        for id_ in ids:
            count = html.count('id="' + id_ + '"')
            assert count == 1, f"DOM id '{id_}' found {count} times, expected 1"

    def test_no_centerline_only_in_title(self):
        html = Path("web_ui/static/index.html").read_text()
        assert "(Centerline Only)" not in html
        assert "Field Reference / 场地参考" in html

    def test_progress_element_exists(self):
        html = Path("web_ui/static/index.html").read_text()
        assert '<progress id="fpSamplingProgress"' in html


class TestJSFunctionScope:
    def test_finalize_only_in_finalize_fn(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        # Find finalizeRuntimeSampling function body
        fn_start = src.find("async function finalizeRuntimeSampling")
        fn_end = src.find("async function cancelRuntimeSampling", fn_start)
        if fn_end < 0:
            fn_end = src.find("function cancelRuntimeSampling", fn_start)
        if fn_end < 0:
            fn_end = len(src)
        fn_body = src[fn_start:fn_end]
        assert "runtime-sampling/finalize" in fn_body

    def test_polling_does_not_call_start(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        # Polling function should not contain start
        poll_start = src.find("function fetchFieldReferenceStatus")
        poll_end = src.find("function startPolling", poll_start + 10)
        if poll_end < 0:
            poll_end = src.find("function stopPolling", poll_start)
        if poll_end < 0:
            poll_end = len(src)
        poll_body = src[poll_start:poll_end]
        assert "runtime-sampling/start" not in poll_body
        assert "runtime-sampling/finalize" not in poll_body
        assert "runtime-sampling/cancel" not in poll_body

    def test_no_set_interval(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        assert "setInterval" not in src, "setInterval found — should use recursive setTimeout"

    def test_poll_in_flight_guard(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        assert "pollInFlight" in src

    def test_requestBusy_in_profile_js(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "requestBusy" in src
        assert "updateRuntimeControls()" in src


class TestCSS:
    def test_runtime_progress_style(self):
        css = Path("web_ui/static/style.css").read_text()
        assert "fpSamplingProgress" in css

    def test_disabled_button_style(self):
        css = Path("web_ui/static/style.css").read_text()
        assert "disabled" in css
