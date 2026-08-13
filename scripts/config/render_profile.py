#!/usr/bin/env python3
"""Render a small RK3588 profile delta over canonical strict configs."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import yaml


def _merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def render(repo_root: Path, profile_path: Path, *, write: bool) -> dict[str, dict]:
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    if set(profile) != {"profile", "overrides", "executor"}:
        raise ValueError("profile must contain only profile, overrides and executor")
    executor = profile.get("executor")
    if executor != {"send_commands": False}:
        raise ValueError("profile executor.send_commands must be false")
    overrides = profile.get("overrides")
    if not isinstance(overrides, dict) or set(overrides) - {"telemetry", "yolo"}:
        raise ValueError("profile overrides may contain only telemetry and yolo")
    rendered: dict[str, dict] = {}
    for name in ("telemetry", "yolo"):
        path = repo_root / "config" / f"{name}.yaml"
        base = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        delta = overrides.get(name, {})
        if not isinstance(base, dict) or not isinstance(delta, dict):
            raise ValueError(f"{name} base and override must be mappings")
        rendered[name] = _merge(base, delta)
        if write:
            path.write_text(yaml.safe_dump(rendered[name], sort_keys=False), encoding="utf-8")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    render(args.repo_root.resolve(), args.profile.resolve(), write=args.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
