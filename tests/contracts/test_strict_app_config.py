from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config import build_arg_parser, load_app_config
from scripts.config.render_profile import render


def test_app_config_rejects_unknown_fields(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/app.yaml").read_text())
    data["runtime"]["typo_field"] = 1
    path = tmp_path / "app.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    args = build_arg_parser().parse_args(["--app-config", str(path), "--no-yolo-udp"])
    with pytest.raises(ValueError, match="unknown runtime field"):
        load_app_config(args)


def test_app_config_rejects_string_bool(tmp_path: Path) -> None:
    data = yaml.safe_load(Path("config/app.yaml").read_text())
    data["executor"]["send_commands"] = "false"
    path = tmp_path / "app.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    args = build_arg_parser().parse_args(["--app-config", str(path), "--no-yolo-udp"])
    with pytest.raises(ValueError, match="must be a bool"):
        load_app_config(args)


@pytest.mark.parametrize("name", ["rk3588-real", "rk3588-sitl"])
def test_profile_is_small_delta_and_cannot_enable_send(name: str) -> None:
    path = Path("config/profiles") / name / "profile.yaml"
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert profile["executor"] == {"send_commands": False}
    rendered = render(Path.cwd(), path, write=False)
    assert set(rendered) == {"telemetry", "yolo"}
    assert len(path.read_text(encoding="utf-8").splitlines()) < 20
