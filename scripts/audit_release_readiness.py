#!/usr/bin/env python3
"""Read-only P3 release-readiness audit for the repository and all Git refs.

The command never rewrites history or deletes files.  It reports issues that
must be resolved before a public release; ``--strict`` exits non-zero while
release blockers remain.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_RELEASE_FILES = (
    "LICENSE",
    "NOTICE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "THIRD_PARTY_NOTICES.md",
    "ASSETS_LICENSES.md",
    "MODEL_CARD.md",
)
ASSET_SUFFIXES = {".rknn", ".dat", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mov", ".avi"}
HISTORY_SENSITIVE_SUFFIXES = {".rknn", ".tlog", ".ulg", ".bag", ".bin", ".dat", ".mp4", ".mov", ".avi"}
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _tracked_files() -> list[str]:
    return [line for line in _git("ls-files").splitlines() if line]


def _history_paths() -> list[str]:
    return sorted({line for line in _git("log", "--all", "--format=", "--name-only").splitlines() if line})


def _secret_hits_in_worktree(paths: list[str]) -> list[str]:
    hits: list[str] = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() in ASSET_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            hits.append(relative)
    return hits


def _history_secret_hits() -> bool:
    # Scan textual patches in every reachable ref with Python's regex engine.
    # Git's ``-G`` dialect differs across builds and cannot safely express all
    # of the token patterns above.
    result = subprocess.run(
        ["git", "log", "--all", "-p", "--no-ext-diff", "--format=%H", "--"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip() or "git history secret scan failed")
    history_text = result.stdout.decode(errors="replace")
    return any(pattern.search(history_text) for pattern in SECRET_PATTERNS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="return non-zero when release blockers exist")
    args = parser.parse_args()

    tracked = _tracked_files()
    history = _history_paths()
    blockers: list[str] = []
    missing = [name for name in REQUIRED_RELEASE_FILES if not (ROOT / name).is_file()]
    if missing:
        blockers.append("missing required public-release documents: " + ", ".join(missing))

    assets = [path for path in tracked if Path(path).suffix.lower() in ASSET_SUFFIXES]
    if assets:
        blockers.append("tracked binary/media assets require explicit provenance and redistribution approval")

    historical = [path for path in history if Path(path).suffix.lower() in HISTORY_SENSITIVE_SUFFIXES]
    if historical:
        blockers.append("Git history contains model, telemetry, EEPROM, terrain, or media paths requiring review")

    worktree_hits = _secret_hits_in_worktree(tracked)
    if worktree_hits:
        blockers.append("known secret pattern found in tracked worktree files: " + ", ".join(worktree_hits))
    if _history_secret_hits():
        blockers.append("known secret pattern found in Git history")

    print("P3 release-readiness audit")
    print(f"tracked files: {len(tracked)}")
    print(f"tracked binary/media assets: {len(assets)}")
    print(f"historical sensitive paths: {len(historical)}")
    if assets:
        print("current assets:")
        for path in assets:
            print(f"  - {path}")
    if historical:
        print("history paths requiring review:")
        for path in historical:
            print(f"  - {path}")
    if blockers:
        print("RELEASE BLOCKED:")
        for blocker in blockers:
            print(f"  - {blocker}")
    else:
        print("no blockers found by this baseline audit")
    return 1 if args.strict and blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
