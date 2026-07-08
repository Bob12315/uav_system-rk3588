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
    assert 'data-action-mission-template="recon_inspect_5_targets_stepwise_v2"' in html
    assert 'data-action-mission-template="rescue_2026_full_auto_v2"' in html
    assert 'data-action-mission-template="drop_two_targets_v1"' not in html
    assert 'data-action-mission-template="recon_inspect_5_targets_stepwise_v1"' not in html
    assert 'data-action-mission-template="recon_sequence_v1"' not in html
    assert 'data-action-mission-template="rescue_2026_full_auto"' not in html


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
