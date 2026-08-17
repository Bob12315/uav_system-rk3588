from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_web_receives_explicit_services_not_system_runner() -> None:
    source = "\n".join(path.read_text() for path in (ROOT / "web_ui").rglob("*.py"))
    assert "SystemRunner" not in source
    assert "runner." not in source
    assert "getattr(runner" not in source


def test_server_and_app_are_thin_assembly_entries() -> None:
    assert len((ROOT / "web_ui/server.py").read_text().splitlines()) < 100
    app_js = (ROOT / "web_ui/static/app.js").read_text()
    assert "UavControl.init" in app_js
    assert "function " not in app_js


def test_router_groups_and_field_modules_exist() -> None:
    for name in ("auth", "status", "actions", "missions", "field", "vision", "config", "services"):
        assert (ROOT / f"web_ui/routers/{name}.py").is_file()
    for name in ("model", "render", "interaction"):
        assert (ROOT / f"web_ui/static/js/field/{name}.js").is_file()


def test_fetch_is_owned_only_by_api_client() -> None:
    offenders = []
    for path in (ROOT / "web_ui/static").rglob("*.js"):
        if path.name != "api_client.js" and "fetch(" in path.read_text():
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
