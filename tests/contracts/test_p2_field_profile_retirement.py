from pathlib import Path

import pytest

from field.profile import FieldProfileValidationError, load_field_profile_json, parse_field_profile
from field.profile_service import FieldProfileService
from app.config import build_arg_parser, load_app_config
from application.runner import SystemRunner


ROOT = Path(__file__).resolve().parents[2]


def test_only_schema_v3_profile_is_shipped_and_listed() -> None:
    directory = ROOT / "config" / "field_profiles"
    assert [path.name for path in directory.glob("*.json")] == ["competition_runtime_v3.json"]
    profile = load_field_profile_json(directory / "competition_runtime_v3.json")
    assert profile.schema_version == 3
    assert FieldProfileService.validate_profile(profile).ok


def test_schema_v2_and_local_origin_fields_are_rejected() -> None:
    with pytest.raises(FieldProfileValidationError, match="schema v3"):
        parse_field_profile({"schema_version": 2})
    with pytest.raises(FieldProfileValidationError, match="must not contain"):
        parse_field_profile({"schema_version": 3, "anchor": {}})


def test_runtime_field_reference_truthfully_has_no_local_ned_transform() -> None:
    config = load_app_config(build_arg_parser().parse_args(["--no-yolo-udp", "--no-ui"]))
    status = SystemRunner(config).field_reference_status()["field_reference"]
    assert "is_ready_for_field_to_local" not in status
    assert status["is_ready_for_field_to_gps"] is False


def test_p2_removed_v2_api_and_legacy_runtime_files() -> None:
    server = (ROOT / "web_ui" / "server.py").read_text(encoding="utf-8")
    assert "bind-current" not in server
    assert not (ROOT / "app" / "mission_runner.py").exists()
    assert not (ROOT / "app" / "stage_registry.py").exists()
