"""Safe discovery and loading for supported schema-v3 Field Profiles."""
from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Iterable

from contracts.platform.common import SchemaVersion
from contracts.platform.field import FieldProfileRecord
from .profile import (FieldProfile, FieldProfileDiagnostics, load_field_profile_json,
                      parse_field_profile, profile_to_dict, validate_field_profile)


def _freeze_json(value):
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


class ReadOnlyFieldProfileRepository:
    """Injected, deterministic schema-v3 profile repository.

    Sources are ordered highest priority first.  Duplicate profile IDs are
    resolved once here; callers never traverse directories independently.
    """

    def __init__(self, sources: Iterable[tuple[str, str | Path]]) -> None:
        self._sources = tuple((str(name), Path(path).resolve()) for name, path in sources)
        self._lock = RLock()
        self._records: dict[str, FieldProfileRecord] | None = None
        self._profiles: dict[str, FieldProfile] | None = None

    def _load(self) -> None:
        records: dict[str, FieldProfileRecord] = {}
        profiles: dict[str, FieldProfile] = {}
        for priority, (source, root) in enumerate(self._sources):
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.json"), key=lambda item: item.name):
                if path.name.startswith(".") or path.parent.resolve() != root:
                    continue
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                profile_id = path.stem
                try:
                    decoded = json.loads(raw.decode("utf-8"))
                    profile = parse_field_profile(decoded)
                    profile_id = profile.profile_id
                    diagnostics = validate_field_profile(profile)
                    record = FieldProfileRecord(
                        SchemaVersion(3, 0), profile.profile_id, profile.name, source, priority,
                        digest, bool(profile.extra.get("template_only") is True), diagnostics.ok,
                        tuple(diagnostics.errors), tuple(diagnostics.warnings), _freeze_json(profile_to_dict(profile)),
                    )
                except Exception as exc:
                    record = FieldProfileRecord(
                        SchemaVersion(3, 0), profile_id, profile_id, source, priority, digest,
                        False, False, (str(exc),), (), None,
                    )
                    profile = None
                if profile_id in records:
                    continue
                records[profile_id] = record
                if profile is not None:
                    profiles[profile_id] = profile
        self._records, self._profiles = records, profiles

    def refresh(self) -> None:
        with self._lock:
            self._records = self._profiles = None

    def list(self) -> tuple[FieldProfileRecord, ...]:
        with self._lock:
            if self._records is None: self._load()
            assert self._records is not None
            return tuple(self._records[key] for key in sorted(self._records))

    def get(self, profile_id: str) -> FieldProfileRecord:
        self._validate_id(profile_id)
        with self._lock:
            if self._records is None: self._load()
            assert self._records is not None
            try: return self._records[profile_id.removesuffix(".json")]
            except KeyError as exc: raise FileNotFoundError(f"profile not found: {profile_id}") from exc

    def load_profile(self, profile_id: str) -> FieldProfile:
        record = self.get(profile_id)
        if not record.valid:
            raise ValueError(record.errors[0] if record.errors else "invalid field profile")
        with self._lock:
            assert self._profiles is not None
            return self._profiles[record.profile_id]

    @staticmethod
    def _validate_id(profile_id: str) -> None:
        if (not isinstance(profile_id, str) or not profile_id.strip() or os.path.isabs(profile_id)
                or ".." in profile_id or "/" in profile_id or "\\" in profile_id):
            raise ValueError("field profile id must be a simple relative name")


class FieldProfileService:
    """Filesystem boundary only; v2 centerline binding was retired in P2."""

    @staticmethod
    def list_profiles(profile_dir: str) -> list[str]:
        if not os.path.isdir(profile_dir):
            return []
        return [
            os.path.abspath(os.path.join(profile_dir, entry))
            for entry in sorted(os.listdir(profile_dir))
            if entry.endswith(".json") and not entry.startswith(".") and os.path.isfile(os.path.join(profile_dir, entry))
        ]

    @staticmethod
    def load_profile(profile_id: str, profile_dir: str | None = None) -> FieldProfile:
        if profile_dir is None or not isinstance(profile_id, str) or not profile_id.strip():
            raise FileNotFoundError("field profile id and directory are required")
        if os.path.isabs(profile_id) or ".." in profile_id or "/" in profile_id or "\\" in profile_id:
            raise ValueError("field profile id must be a simple relative name")
        filename = profile_id if profile_id.endswith(".json") else f"{profile_id}.json"
        root = os.path.realpath(profile_dir)
        path = os.path.realpath(os.path.join(root, filename))
        if os.path.commonpath([root, path]) != root:
            raise ValueError("field profile path escapes profile directory")
        return load_field_profile_json(path)

    @staticmethod
    def validate_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
        return validate_field_profile(profile)
