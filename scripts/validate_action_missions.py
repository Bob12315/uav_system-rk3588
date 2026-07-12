from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.mission_orchestrator import MissionBlackboard
from missions.common.actions.action_lab import create_action_lab_registry


DEFAULT_TEMPLATE_PATHS = [
    ROOT / "config/action_missions/drop_two_targets_v1.json",
    ROOT / "config/action_missions/drop_two_targets_v2.json",
    ROOT / "config/action_missions/recon_gps_v2.json",
    ROOT / "config/action_missions/recon_inspect_5_targets_stepwise_v1.json",
    ROOT / "config/action_missions/rescue_2026_full_auto.json",
    ROOT / "config/action_missions/rescue_2026_full_auto_v2.json",
]
ALLOWED_FAILURE_ACTIONS = {"fail", "retry_current", "retry_current_then_jump_to", "jump_to", "continue"}


def validate_templates(paths: list[Path]) -> list[str]:
    registered_actions = set(create_action_lab_registry().list())
    messages: list[str] = []
    for path in paths:
        data = _load_template(path)
        steps = _validate_shape(path, data)
        labels = _validate_steps(path, steps, registered_actions)
        _validate_blackboard_refs(path, steps)
        display_path = _display_path(path)
        label_text = ",".join(sorted(labels)) if labels else "-"
        messages.append(f"OK {display_path} steps={len(steps)} labels={label_text}")
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Action Mission JSON templates offline.")
    parser.add_argument("paths", nargs="*", type=Path, help="Template path(s) to validate.")
    args = parser.parse_args(argv)

    paths = args.paths or DEFAULT_TEMPLATE_PATHS
    try:
        messages = validate_templates(paths)
    except ValueError as exc:
        print(str(exc))
        return 1

    for message in messages:
        print(message)
    print("All action mission templates validated.")
    return 0


def _load_template(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"ERROR {_display_path(path)}: cannot read JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"ERROR {_display_path(path)}: top-level JSON must be an object")
    return data


def _validate_shape(path: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ValueError(f"ERROR {_display_path(path)}: top-level name must be a non-empty string")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"ERROR {_display_path(path)}: steps must be a non-empty list")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"ERROR {_display_path(path)}: step {index} must be an object")
    return steps


def _validate_steps(
    path: Path,
    steps: list[dict[str, Any]],
    registered_actions: set[str],
) -> set[str]:
    labels: dict[str, int] = {}
    for index, step in enumerate(steps):
        prefix = f"ERROR {_display_path(path)}: step {index}"
        name = step.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{prefix} name must be a non-empty string")
        if name.strip() not in registered_actions:
            raise ValueError(f"{prefix} unknown action: {name}")

        params = step.get("params")
        if not isinstance(params, dict):
            raise ValueError(f"{prefix} params must be an object")

        save_as = step.get("save_as")
        if save_as is not None and (not isinstance(save_as, str) or not save_as.strip()):
            raise ValueError(f"{prefix} save_as must be a non-empty string")

        label = step.get("label")
        if label is not None:
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"{prefix} label must be a non-empty string")
            normalized = label.strip()
            if normalized in labels:
                raise ValueError(f"{prefix} duplicate label: {normalized}")
            labels[normalized] = index

        _validate_on_failed(path, index, step.get("on_failed"))

    label_set = set(labels)
    for index, step in enumerate(steps):
        policy = step.get("on_failed")
        if not isinstance(policy, dict) or policy.get("action") not in {"jump_to", "retry_current_then_jump_to"}:
            continue
        target = policy.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"ERROR {_display_path(path)}: step {index} {policy.get('action')} target must be a non-empty string")
        if target.strip() not in label_set:
            raise ValueError(f"ERROR {_display_path(path)}: step {index} {policy.get('action')} target not found: {target}")
    return label_set


def _validate_on_failed(path: Path, index: int, policy: Any) -> None:
    if policy is None:
        return
    prefix = f"ERROR {_display_path(path)}: step {index}"
    if not isinstance(policy, dict):
        raise ValueError(f"{prefix} on_failed must be an object")
    action = policy.get("action", "fail")
    if not isinstance(action, str) or action not in ALLOWED_FAILURE_ACTIONS:
        raise ValueError(f"{prefix} invalid on_failed action: {action}")
    if action in {"retry_current", "retry_current_then_jump_to", "jump_to"}:
        attempts = policy.get("max_attempts", 1)
        if not isinstance(attempts, int) or attempts < 1:
            raise ValueError(f"{prefix} {action}.max_attempts must be >= 1")


def _validate_blackboard_refs(path: Path, steps: list[dict[str, Any]]) -> None:
    blackboard = _smoke_blackboard()
    for index, step in enumerate(steps):
        params = step["params"]
        for ref in _blackboard_refs(params):
            if ref == "$":
                raise ValueError(f"ERROR {_display_path(path)}: step {index} blackboard path must be non-empty")
        try:
            blackboard.resolve(params)
        except Exception as exc:
            raise ValueError(
                f"ERROR {_display_path(path)}: step {index} blackboard resolve failed: {exc}"
            ) from exc


def _blackboard_refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("$") else []
    if isinstance(value, dict):
        refs: list[str] = []
        for item in value.values():
            refs.extend(_blackboard_refs(item))
        return refs
    if isinstance(value, list):
        refs = []
        for item in value:
            refs.extend(_blackboard_refs(item))
        return refs
    return []


def _smoke_blackboard() -> MissionBlackboard:
    blackboard = MissionBlackboard()
    blackboard.set(
        "drop_scan",
        {
            "localized_objects": [
                {"id": "b1", "local_x": 1.0, "local_y": 30.0},
                {"id": "b2", "local_x": -1.0, "local_y": 31.0},
            ],
            "raw_estimates": [
                {"track_id": 1, "class_name": "bucket_1", "local_x": 1.0, "local_y": 30.0, "source": {"ex": 0.1, "ey": 0.05}, "confidence": 0.85},
                {"track_id": 2, "class_name": "bucket_2", "local_x": -1.0, "local_y": 31.0, "source": {"ex": -0.1, "ey": 0.08}, "confidence": 0.78},
            ],
        },
    )
    blackboard.set(
        "drop_center",
        {
            "resolved_targets": [
                {"valid": True, "source": "field", "local_x": 100.0, "local_y": 232.5, "z_down_m": -5.0, "lat": 30.0, "lon": 120.0, "altitude_m": 5.0},
            ],
        },
    )
    blackboard.set(
        "first_scan_point",
        {
            "resolved_targets": [
                {"valid": True, "source": "field", "local_x": 98.0, "local_y": 231.25, "z_down_m": -5.0, "lat": 30.0, "lon": 120.0, "altitude_m": 5.0},
            ],
        },
    )
    blackboard.set(
        "drop_buckets",
        {
            "resolved_targets": [
                {"valid": True, "source": "vision", "class_name": "bucket_1", "local_x": 101.0, "local_y": 230.0, "z_down_m": -5.0, "lat": 30.0, "lon": 120.0, "altitude_m": 5.0, "confidence": 0.85},
                {"valid": True, "source": "vision", "class_name": "bucket_2", "local_x": 99.0, "local_y": 231.0, "z_down_m": -5.0, "lat": 30.0, "lon": 120.0, "altitude_m": 5.0, "confidence": 0.78},
            ],
        },
    )
    blackboard.set(
        "home_waypoint",
        {
            "resolved_targets": [
                {"valid": True, "source": "home", "local_x": 100.0, "local_y": 200.0, "z_down_m": -5.0, "lat": 30.0, "lon": 120.0, "altitude_m": 5.0},
            ],
        },
    )
    blackboard.set(
        "drop_targets",
        {
            "selected_targets": [
                {"id": "b1", "local_x": 1.0, "local_y": 30.0},
                {"id": "b2", "local_x": -1.0, "local_y": 31.0},
            ],
            "first_release_servo_outputs": [
                {"channel": 8, "release_pwm": 1750, "hold_pwm": 1250},
            ],
            "target_slots": [
                {
                    "valid": True,
                    "id": "b1",
                    "target_id": "b1",
                    "class_name": "bucket_1",
                    "local_x": 1.0,
                    "local_y": 30.0,
                    "x": 1.0,
                    "y": 30.0,
                    "lat": 34.10364,
                    "lon": 108.64267,
                    "score": 500,
                    "seen_count": 3,
                    "count": 3,
                    "raw_count": 3,
                    "weight": 2.0,
                    "track_ids": [1],
                    "rank": 1,
                },
                {
                    "valid": True,
                    "id": "b2",
                    "target_id": "b2",
                    "class_name": "bucket_2",
                    "local_x": -1.0,
                    "local_y": 31.0,
                    "x": -1.0,
                    "y": 31.0,
                    "lat": 34.10363,
                    "lon": 108.64318,
                    "score": 300,
                    "seen_count": 2,
                    "count": 2,
                    "raw_count": 2,
                    "weight": 1.5,
                    "track_ids": [2],
                    "rank": 2,
                },
                {
                    "valid": False,
                    "id": "missing_drop_target_2",
                    "target_id": None,
                    "class_name": "",
                    "local_x": None,
                    "local_y": None,
                    "x": None,
                    "y": None,
                    "score": 0.0,
                    "seen_count": 0,
                    "count": 0,
                    "raw_count": 0,
                    "weight": 0.0,
                    "track_ids": [],
                    "rank": 3,
                    "status": "missing",
                },
            ],
        },
    )
    blackboard.set(
        "recon_scan",
        {
            "localized_objects": [
                {"id": "r1", "class_name": "bucket", "local_x": 1.0, "local_y": 5.0},
                {"id": "r2", "class_name": "recon_bucket", "local_x": -1.0, "local_y": 51.0},
                {"id": "r3", "class_name": "white_bucket", "local_x": 0.5, "local_y": 49.0},
            ],
        },
    )
    blackboard.set(
        "recon_targets",
        {
            "selected_targets": [
                {"id": "r1", "class_name": "bucket", "local_x": 1.0, "local_y": 5.0},
                {"id": "r2", "class_name": "recon_bucket", "local_x": -1.0, "local_y": 51.0},
                {"id": "r3", "class_name": "white_bucket", "local_x": 0.5, "local_y": 49.0},
            ],
            "target_slots": [
                {"valid": True, "id": "r1", "class_name": "bucket", "local_x": 1.0, "local_y": 5.0, "x": 1.0, "y": 5.0, "seen_count": 3, "raw_count": 3, "weight": 3.0, "rank": 1},
                {"valid": True, "id": "r2", "class_name": "recon_bucket", "local_x": -1.0, "local_y": 51.0, "x": -1.0, "y": 51.0, "seen_count": 2, "raw_count": 2, "weight": 2.0, "rank": 2},
                {"valid": True, "id": "r3", "class_name": "white_bucket", "local_x": 0.5, "local_y": 49.0, "x": 0.5, "y": 49.0, "seen_count": 1, "raw_count": 1, "weight": 1.0, "rank": 3},
                {"valid": False, "id": "missing_recon_target_3", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "seen_count": 0, "raw_count": 0, "weight": 0.0, "rank": 4, "status": "missing"},
                {"valid": False, "id": "missing_recon_target_4", "class_name": "", "local_x": None, "local_y": None, "x": None, "y": None, "seen_count": 0, "raw_count": 0, "weight": 0.0, "rank": 5, "status": "missing"},
            ],
        },
    )
    for i in range(5):
        blackboard.set(
            f"recon_result_{i}",
            {"target_id": f"recon_{i}", "target_index": i, "content": "blank", "confidence": 0.0, "status": "blank_or_uncertain"},
        )
    blackboard.set(
        "recon_report",
        {"recon_report": {"barrels": []}, "barrel_count": 5, "detected_count": 0, "blank_count": 5, "skipped_count": 0},
    )
    blackboard.set(
        "recon_sequence",
        {
            "observations": [
                {"target_index": 0, "target_id": "r1", "hazard_label": "", "status": "blank"},
            ],
            "recon_result_items": [
                {"target_index": 0, "target_id": "r1", "content": "baozha", "confidence": 0.72, "status": "detected"},
            ],
        },
    )
    return blackboard


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
