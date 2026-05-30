from __future__ import annotations

import difflib
import shutil
from pathlib import Path

import yaml


class ConfigStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def files(self) -> list[str]:
        candidates = [
            self.root / "config" / "app.yaml",
            self.root / "config" / "telemetry.yaml",
            self.root / "yolo_app" / "config.yaml",
        ]
        candidates.extend(sorted((self.root / "missions").glob("*/config.yaml")))
        return [str(path.relative_to(self.root)) for path in candidates if path.exists()]

    def resolve(self, relative_path: str) -> Path:
        normalized = relative_path.strip().replace("\\", "/")
        if normalized not in self.files():
            raise ValueError("configuration path is not approved")
        return (self.root / normalized).resolve()

    def read(self, relative_path: str) -> dict[str, object]:
        path = self.resolve(relative_path)
        content = path.read_text(encoding="utf-8")
        return {
            "path": relative_path,
            "content": content,
            "has_backup": path.with_suffix(path.suffix + ".bak").exists(),
        }

    def preview(self, relative_path: str, content: str) -> str:
        current = self.resolve(relative_path).read_text(encoding="utf-8")
        return "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=relative_path,
                tofile=f"{relative_path} (edited)",
            )
        )

    def save(self, relative_path: str, content: str) -> str:
        path = self.resolve(relative_path)
        self._validate(content, relative_path)
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        path.write_text(content, encoding="utf-8")
        return self.preview_backup(path, relative_path)

    def restore(self, relative_path: str) -> str:
        path = self.resolve(relative_path)
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            raise ValueError("no previous saved version is available")
        replacement = backup.read_text(encoding="utf-8")
        self._validate(replacement, relative_path)
        current = path.read_text(encoding="utf-8")
        path.write_text(replacement, encoding="utf-8")
        backup.write_text(current, encoding="utf-8")
        return self.preview_backup(path, relative_path)

    @staticmethod
    def _validate(content: str, relative_path: str) -> None:
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"YAML root must be a mapping: {relative_path}")

    @staticmethod
    def preview_backup(path: Path, relative_path: str) -> str:
        backup = path.with_suffix(path.suffix + ".bak")
        before = backup.read_text(encoding="utf-8") if backup.exists() else ""
        after = path.read_text(encoding="utf-8")
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"{relative_path}.bak",
                tofile=relative_path,
            )
        )
