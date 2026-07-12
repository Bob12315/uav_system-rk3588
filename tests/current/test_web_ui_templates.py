from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read_html():
    return (ROOT / "web_ui/static/index.html").read_text(encoding="utf-8")


def _read_js(path: str):
    return (ROOT / path).read_text(encoding="utf-8")


def test_index_contains_only_v2_template_buttons():
    html = _read_html()
    assert 'data-action-mission-template="drop_two_targets_v2"' in html
    assert 'data-action-mission-template="recon_gps_v2"' in html
    assert 'data-action-mission-template="rescue_2026_full_auto_v2"' in html
    assert 'data-action-mission-template="drop_two_targets_v1"' not in html
    assert 'data-action-mission-template="recon_inspect_5_targets_stepwise_v1"' not in html
    assert 'data-action-mission-template="recon_sequence_v1"' not in html
    assert 'data-action-mission-template="rescue_2026_full_auto"' not in html
    assert 'id="actionMissionTemplateList"' not in html
    assert 'id="actionMissionLoadCustom"' not in html
    assert 'id="actionMissionValidate"' not in html


def test_index_no_legacy_templates():
    html = _read_html()
    assert 'class="legacy-templates"' not in html
    assert '旧版 / 调试模板' not in html
    assert 'data-action-mission-preset="dry_goto"' not in html
    assert 'data-action-mission-preset="payload_release_test"' not in html


def test_action_lab_has_whitelist():
    js = _read_js("web_ui/static/js/action_lab.js")
    assert "ACTION_UI_ALLOWED_NAMES" in js
    assert '"takeoff"' in js
    assert '"yaw_align"' in js
    assert '"fixed_view_localize"' in js
    assert '"select_drop_targets"' in js
    assert '"recon_sequence"' in js
    assert '"build_recon_report"' in js


def test_action_lab_filter_uses_whitelist():
    js = _read_js("web_ui/static/js/action_lab.js")
    assert "allowed.has(spec.name)" in js


def test_app_js_presets_cleared():
    js = _read_js("web_ui/static/app.js")
    assert "const actionMissionPresets = {};" in js
    assert "dry_goto:" not in js


def test_app_js_v2_safety_hints():
    js = _read_js("web_ui/static/app.js")
    assert "fixed_view_localize:" in js
    assert "select_drop_targets:" in js
    assert "drop_sequence:" in js
    assert "select_recon_targets:" in js
    assert "recon_sequence:" in js
    assert "build_recon_report:" in js


def test_server_template_names_v2_only():
    js = _read_js("web_ui/server.py")
    assert '"drop_two_targets_v2"' in js
    assert '"recon_inspect_5_targets_stepwise_v2"' in js
    assert '"rescue_2026_full_auto_v2"' in js
    assert '"drop_two_targets_v1"' not in js
    assert '"recon_sequence_v1"' not in js
    assert '"recon_inspect_5_targets_stepwise_v1"' not in js
    assert '"rescue_2026_full_auto"' not in js


def test_app_js_init_no_load_action_mission_templates():
    """app.js init 不再调用 loadActionMissionTemplates，避免动态生成重复按钮。"""
    js = _read_js("web_ui/static/app.js")
    assert "loadActionLab(), loadActionMissionTemplates()" not in js
    assert "loadActionLab()]);" in js
    # 函数定义仍可以保留
    assert "function loadActionMissionTemplates" in js


def test_app_js_summary_html_cache_variable():
    """app.js 有 lastActionMissionSummaryHtml 变量用于防闪烁。"""
    js = _read_js("web_ui/static/app.js")
    assert "lastActionMissionSummaryHtml" in js


def test_app_js_summary_html_comparison():
    """renderActionMissionSummary 使用 html === lastActionMissionSummaryHtml 比对。"""
    js = _read_js("web_ui/static/app.js")
    assert "html === lastActionMissionSummaryHtml" in js


def test_app_js_recon_report_path_v2_first():
    """summarizeReconReport 优先读取 recon_report.recon_report。"""
    js = _read_js("web_ui/static/app.js")
    assert '["recon_report", "recon_report"]' in js


def test_app_js_recon_report_path_fallback():
    """summarizeReconReport 保留 recon_scan.recon_report 兼容路径。"""
    js = _read_js("web_ui/static/app.js")
    assert '["recon_scan", "recon_report"]' in js


def test_field_map_x_original_world_to_canvas():
    """field_map.js worldToCanvas 恢复原始 originX + x 正向映射。"""
    js = _read_js("web_ui/static/js/field_map.js")
    assert "originX + Number(x) * view.scale" in js


def test_field_map_x_original_canvas_to_world():
    """field_map.js canvasToWorld 恢复原始 (screenX - originX) 逆映射。"""
    js = _read_js("web_ui/static/js/field_map.js")
    assert "x: (screenX - originX) / view.scale" in js


def test_field_map_x_mirrored_mapping_removed():
    """field_map.js 不再使用 originX - x 镜像映射。"""
    js = _read_js("web_ui/static/js/field_map.js")
    assert "originX - Number(x) * view.scale" not in js


def test_field_map_x_mirrored_inverse_removed():
    """field_map.js 不再使用 (originX - screenX) 逆映射。"""
    js = _read_js("web_ui/static/js/field_map.js")
    assert "x: (originX - screenX) / view.scale" not in js


def test_field_map_drone_uses_field_x_directly():
    """field_map.js fieldMapModel uses x: fieldX directly (no sign flip)."""
    js = _read_js("web_ui/static/js/field_map.js")
    assert "x: -fieldX" not in js
    assert "display_x_mirrored" not in js
    assert "x: fieldX" in js


def test_index_field_map_asset_gps_fused_targets_version():
    """index.html 使用 gps-fused-targets 新缓存版本。"""
    html = _read_html()
    assert "uav-x-mirror-20260710-1" not in html
    assert "uav-x-unmirror-20260711-1" not in html
    assert "uav-gps-field-position-20260711-1" not in html
    assert "gps-fused-targets-20260711-1" in html


def test_field_map_gps_ready_blocks_local_fallback():
    """GPS field reference ready 时禁止原始 LOCAL_NED 兜底。"""
    js = _read_js("web_ui/static/js/field_map.js")
    assert "gpsFieldReady" in js
    assert "is_ready_for_field_to_gps" in js
    assert "!gpsFieldReady" in js


def test_field_map_fusion_uses_sample_count():
    """融合目标计数优先使用 sample_count。"""
    js = _read_js("web_ui/static/js/field_map.js")
    assert "sample_count" in js
    assert "raw_count" in js
    # pointX/pointY chain does NOT use east_m/north_m
    assert "east_m" not in js
    assert "north_m" not in js
