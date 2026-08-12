#!/usr/bin/env python3
"""Fast static guardrails for the P1 package and safety boundaries."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module.split(".")[0])
    return result


def py_files(directory: str) -> list[Path]:
    return sorted((ROOT / directory).rglob("*.py"))


def main() -> None:
    errors: list[str] = []
    core = py_files("fusion") + py_files("missions/common/actions")
    forbidden_core = {"fastapi", "uvicorn", "pymavlink", "cv2", "rknnlite"}
    for path in core:
        leaked = imports(path) & forbidden_core
        if leaked:
            errors.append(f"core import leak {path.relative_to(ROOT)}: {sorted(leaked)}")

    for path in py_files("missions/common/actions"):
        content = path.read_text(encoding="utf-8")
        if {"pymavlink", "telemetry_link"} & imports(path) or "LinkManager" in content:
            errors.append(f"Action boundary violation {path.relative_to(ROOT)}")

    for path in py_files("yolo_app"):
        content = path.read_text(encoding="utf-8")
        if {"pymavlink", "telemetry_link"} & imports(path) or "LinkManager" in content:
            errors.append(f"YOLO telemetry/control violation {path.relative_to(ROOT)}")

    app_config = (ROOT / "config/app.yaml").read_text(encoding="utf-8")
    if "send_commands: false" not in app_config:
        errors.append("config/app.yaml must default executor.send_commands to false")
    if errors:
        raise SystemExit("\n".join(errors))
    print("architecture boundaries validated")


if __name__ == "__main__":
    main()
