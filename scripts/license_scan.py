#!/usr/bin/env python3
"""Report licenses for installed direct/transitive packages; no network needed."""
from __future__ import annotations

from importlib.metadata import distributions


def main() -> None:
    unknown: list[str] = []
    for dist in sorted(
        distributions(),
        key=lambda item: (item.metadata.get("Name") or item.name or "").lower(),
    ):
        name = dist.metadata.get("Name") or dist.name or "<unnamed distribution>"
        license_name = dist.metadata.get("License") or "UNKNOWN"
        print(f"{name}=={dist.version}: {license_name}")
        if license_name == "UNKNOWN":
            unknown.append(name)
    if unknown:
        print("WARNING: metadata license missing for: " + ", ".join(unknown))


if __name__ == "__main__":
    main()
