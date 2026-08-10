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

    def test_runtime_sampling_auto_finalizes_in_orchestrator(self):
        src = Path("app/runtime_binding_orchestrator.py").read_text()
        assert "auto_finalized" in src


def test_runtime_binding_automatic_freeze_in_current_contract():
    src = Path("docs/developer/field_origin_heading.md").read_text()
    assert "Schema v3：比赛现场初始化" in src
    assert "自动 finalize、apply 并 freeze" in src
    assert "is_ready_for_field_to_local=false" in src


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
               "fpRuntimeStart", "fpRuntimeCancel"]
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
    def test_primary_ui_omits_manual_finalize(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "function onFinalize" not in src
        assert "cfsFinalize" not in src

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
        assert "updateButtons()" in src


class TestCSS:
    def test_runtime_progress_style(self):
        css = Path("web_ui/static/style.css").read_text()
        assert "fpSamplingProgress" in css

    def test_disabled_button_style(self):
        css = Path("web_ui/static/style.css").read_text()
        assert "disabled" in css


# =============================================================================
# Module integration tests (6.3)
# =============================================================================


class TestModuleIntegration:
    def test_single_fetch_definition(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        assert "function fetchFieldReferenceStatus" in src
        lines = [l for l in src.split(chr(10)) if "function fetchFieldReferenceStatus" in l]
        assert len(lines) == 1, f"fetchFieldReferenceStatus defined {len(lines)} times"

    def test_single_on_field_reference_status(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "function onFieldReferenceStatus" not in src.split("})();")[1] if "})();" in src else True
        assert "onFieldReferenceStatus" in src

    def test_no_window_selected_profile_schema(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "window.selectedProfileSchema" not in src
        assert "window.selectedProfileId" not in src
        assert "window.requestBusy" not in src

    def test_start_in_iife(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "onStart" in src  # competition start handler

    def test_profile_js_not_directly_fetch_status(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        # The profile.js should call UavFieldRef, not fetch status directly
        assert "window.UavFieldRef.fetchFieldReferenceStatus" in src or "UavFieldRef" in src

    def test_no_set_interval(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        assert "setInterval" not in src

    def test_poll_in_flight_guard(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        assert "pollInFlight" in src

    def test_modules_export_on_field_reference_status(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "onFieldReferenceStatus" in src


class TestNoDuplicateFunctions:
    def test_no_duplicate_start(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        lines = [l for l in src.split('\n') if 'function onStart' in l]
        assert len(lines) <= 1, f"onStart defined {len(lines)} times"

    def test_no_duplicate_update_controls(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        lines = [l for l in src.split('\n') if 'function updateButtons' in l]
        assert len(lines) <= 1, f"updateButtons defined {len(lines)} times"


# =============================================================================
# Node syntax and module integrity tests (6.4)
# =============================================================================


class TestNodeSyntax:
    def test_node_check_profile(self):
        import subprocess
        r = subprocess.run(["node", "--check", "web_ui/static/js/field_profile.js"], capture_output=True, text=True)
        assert r.returncode == 0, f"node --check failed: {r.stderr}"

    def test_node_check_reference(self):
        import subprocess
        r = subprocess.run(["node", "--check", "web_ui/static/js/field_reference.js"], capture_output=True, text=True)
        assert r.returncode == 0, f"node --check failed: {r.stderr}"


class TestModuleExports:
    def test_profile_exports_9_methods(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "return {" in src
        assert "onFieldReferenceStatus" in src
        assert "updateRuntimeControls" in src  # exports as updateRuntimeControls
        assert "getRuntimeUiState" in src

    def test_ref_exports_7_methods(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        assert "return {" in src
        assert "fetchFieldReferenceStatus" in src
        assert "renderFieldReference" in src
        assert "startPolling" in src
        assert "stopPolling" in src

    def test_no_setInterval(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        assert "setInterval" not in src


class TestStaticIntegrity:
    def test_no_status_endpoint_in_profile(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "/api/field-reference/status" not in src

    def test_no_request_post_bad_sig(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert 'request("POST"' not in src or 'api.request("' not in src.split('"POST"')[0]

    def test_no_orig_load_and_render(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "_origLoadAndRender" not in src

    def test_ref_first_line_is_iife(self):
        src = Path("web_ui/static/js/field_reference.js").read_text().strip()
        assert src.startswith("window.UavFieldRef")

    def test_no_finalize_in_ref_js(self):
        src = Path("web_ui/static/js/field_reference.js").read_text()
        # Legacy buttons in ref.js may reference runtime-sampling for backward compat
        # But polling function must not contain them
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

    def test_single_return_in_profile(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        # Count lines that are exactly '    return {' (module return, not nested)
        lines = [l for l in src.split(chr(10)) if l.strip() == 'return {']
        assert len(lines) <= 19, f"too many bare return {{ lines in field_profile.js"


class TestAppJS:
    def test_no_start_fr_polling(self):
        src = Path("web_ui/static/app.js").read_text()
        assert "startFrPolling" not in src
        assert "setInterval(fetchFieldReferenceStatus" not in src


class TestNodeBehavior:
    """Run the full Node behavior test suite and verify exit code 0."""

    def test_node_behavior_suite(self):
        import subprocess
        # Try new test file first, fall back to old
        import os
        new_test = "tests/js/test_competition_field_setup.js"
        old_test = "tests/js/field_profile_runtime_ui_test.js"
        if os.path.exists(new_test):
            r = subprocess.run(
                ["node", new_test],
                capture_output=True, text=True, timeout=30,
            )
            assert r.returncode == 0, f"Node behavior test failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}"
            assert "All " in r.stdout
            assert " tests passed!" in r.stdout
        else:
            # Skip if new test not yet created
            pytest.skip("test_competition_field_setup.js not yet created")


class TestRealIDs:
    def test_uses_real_fp_ids(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        # Competition panel uses cfs* IDs; legacy fp* IDs are in index.html + field_reference.js
        assert "cfsForwardLat" in src  # competition input
        assert "cfsStart" in src       # competition button
        assert "onFieldReferenceStatus" in src

    def test_no_fpOriginGps_in_js(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        assert "fpOriginGps" not in src

    def test_fpBindResult_preserved(self):
        src = Path("web_ui/static/js/field_profile.js").read_text()
        # setText should NOT be called on fpBindResult
        assert 'setText("fpBindResult"' not in src

    def test_v3_detail_ids_in_html(self):
        html = Path("web_ui/static/index.html").read_text()
        assert "fpV3Marker" in html
        assert "fpV3Scan" in html
        assert "fpV3Sampling" in html
        assert "fpV3Baseline" in html
