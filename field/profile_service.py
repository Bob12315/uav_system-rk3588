"""Safe discovery and loading for supported schema-v3 Field Profiles."""
from __future__ import annotations

import os

from .profile import FieldProfile, FieldProfileDiagnostics, load_field_profile_json, validate_field_profile


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
