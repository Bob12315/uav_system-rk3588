import json
from pathlib import Path

from missions.core.mission_compiler import MissionCompiler
from missions.core.production_catalog import create_production_catalog


ROOT = Path(__file__).resolve().parents[3]


def test_all_formal_v2_missions_compile_deterministically_to_v3() -> None:
    catalog = create_production_catalog()
    compiler = MissionCompiler(catalog.definitions)
    for path in sorted((ROOT / "config" / "action_missions").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        first = compiler.compile(document)
        second = compiler.compile(document)
        assert first == second
        assert first.schema_version.major == 3
        assert len(first.steps) == len(document["steps"])
