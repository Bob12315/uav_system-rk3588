from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_action_missions import DEFAULT_TEMPLATE_PATHS, validate_templates


def _write_template(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "mission.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_validate_templates_accepts_default_templates() -> None:
    messages = validate_templates(DEFAULT_TEMPLATE_PATHS)

    assert messages
    assert all(message.startswith("OK ") for message in messages)


def test_validate_templates_rejects_invalid_action_name(tmp_path: Path) -> None:
    path = _write_template(
        tmp_path,
        {
            "name": "bad",
            "steps": [
                {"name": "not_registered", "params": {}},
            ],
        },
    )

    with pytest.raises(ValueError, match="unknown action"):
        validate_templates([path])


def test_validate_templates_rejects_duplicate_label(tmp_path: Path) -> None:
    path = _write_template(
        tmp_path,
        {
            "name": "bad",
            "steps": [
                {"name": "takeoff", "label": "same", "params": {}},
                {"name": "land", "label": "same", "params": {}},
            ],
        },
    )

    with pytest.raises(ValueError, match="duplicate label"):
        validate_templates([path])


def test_validate_templates_rejects_missing_jump_target(tmp_path: Path) -> None:
    path = _write_template(
        tmp_path,
        {
            "name": "bad",
            "steps": [
                {
                    "name": "takeoff",
                    "on_failed": {
                        "action": "jump_to",
                        "target": "missing",
                    },
                    "params": {},
                },
            ],
        },
    )

    with pytest.raises(ValueError, match="jump_to target not found"):
        validate_templates([path])


def test_validate_templates_rejects_invalid_on_failed_action(tmp_path: Path) -> None:
    path = _write_template(
        tmp_path,
        {
            "name": "bad",
            "steps": [
                {
                    "name": "takeoff",
                    "on_failed": {
                        "action": "unknown",
                    },
                    "params": {},
                },
            ],
        },
    )

    with pytest.raises(ValueError, match="invalid on_failed action"):
        validate_templates([path])


def test_validate_templates_rejects_missing_blackboard_reference(tmp_path: Path) -> None:
    path = _write_template(
        tmp_path,
        {
            "name": "bad",
            "steps": [
                {
                    "name": "goto_waypoint",
                    "params": {
                        "x": "$missing.value",
                    },
                },
            ],
        },
    )

    with pytest.raises(ValueError, match="blackboard resolve failed"):
        validate_templates([path])


def test_validate_action_missions_cli_success() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_action_missions.py",
            "config/action_missions/drop_two_targets_v1.json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "All action mission templates validated." in result.stdout
