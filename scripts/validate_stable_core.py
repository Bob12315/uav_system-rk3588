from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CORE_ROOTS = (
    ROOT / "contracts" / "core",
    ROOT / "application" / "core",
    ROOT / "missions" / "core",
)
FORBIDDEN_IMPORT_PREFIXES = ("pymavlink", "fastapi", "socket")
STRICT_LEGACY_FILES = (
    "application/action_runtime.py",
    "application/send_state.py",
    "execution/dispatcher.py",
    "missions/engine.py",
    "missions/common/actions/runner.py",
)


def _python_files(root: Path):
    yield from sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def validate(strict: bool) -> list[str]:
    errors: list[str] = []
    app_config = (ROOT / "config" / "app.yaml").read_text(encoding="utf-8")
    if not re.search(r"(?m)^\s*send_commands:\s*false\s*$", app_config):
        errors.append("config/app.yaml must keep executor.send_commands: false")

    for root in CORE_ROOTS:
        for path in _python_files(root):
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = (node.module,)
                for name in names:
                    if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        errors.append(f"{relative}:{node.lineno}: forbidden concrete I/O import {name}")

    route = (ROOT / "web_ui" / "routers" / "missions.py").read_text(encoding="utf-8")
    tick_match = re.search(r'@router\.post\("/tick"\)(.*?)(?=\n\s*@router\.|\Z)', route, re.S)
    if tick_match is None or "action_mission_tick" in tick_match.group(1):
        errors.append("Web /tick must be compatibility read-only and must not advance Mission")

    if strict:
        for relative in STRICT_LEGACY_FILES:
            if (ROOT / relative).exists():
                errors.append(f"strict freeze blocker remains: {relative}")
        production_catalog = (ROOT / "missions" / "core" / "production_catalog.py").read_text(encoding="utf-8")
        if "LegacyActionModuleAdapter" in production_catalog:
            errors.append("strict freeze blocker remains: compatibility-backed Action registrations")
        runner = (ROOT / "application" / "runner.py").read_text(encoding="utf-8")
        if "_tick_action_mission_in_background" in runner:
            errors.append("strict freeze blocker remains: legacy background Mission tick owner")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate stable-core boundaries and freeze readiness")
    parser.add_argument("--strict", action="store_true", help="also require production cutover and legacy deletion")
    args = parser.parse_args()
    errors = validate(args.strict)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("stable core boundaries validated" + (" (strict)" if args.strict else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
