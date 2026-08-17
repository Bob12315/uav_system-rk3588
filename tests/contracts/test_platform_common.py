from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.platform import ClockStamp, OperationReceipt, RequestContext, SchemaVersion, to_json_value


def _stamp() -> ClockStamp:
    return ClockStamp(datetime(2026, 8, 16, tzinfo=timezone.utc), 123, "app-process-1")


def test_schema_version_is_explicit_and_major_compatible() -> None:
    assert SchemaVersion.parse("1.2") == SchemaVersion(1, 2)
    assert SchemaVersion(1, 3).supports(SchemaVersion(1, 2))
    assert not SchemaVersion(2, 0).supports(SchemaVersion(1, 9))
    with pytest.raises(ValueError):
        SchemaVersion.parse("1")


def test_request_context_is_immutable_and_keeps_two_time_domains() -> None:
    context = RequestContext("req-1", "corr-1", "operator", "sitl", _stamp())
    with pytest.raises(FrozenInstanceError):
        context.request_id = "changed"  # type: ignore[misc]
    payload = to_json_value(context)
    assert payload["created_at"]["monotonic_ns"] == 123  # type: ignore[index]
    assert payload["created_at"]["utc"].endswith("+00:00")  # type: ignore[index,union-attr]


def test_operation_receipt_serializes_without_runtime_objects() -> None:
    receipt = OperationReceipt("op-1", True, "accepted", _stamp(), detail={"attempt": 1})
    assert to_json_value(receipt)["schema_version"] == "1.0"  # type: ignore[index]


def test_platform_contracts_only_import_python_standard_library() -> None:
    root = Path(__file__).parents[2] / "contracts" / "platform"
    allowed = {"__future__", "dataclasses", "datetime", "enum", "typing"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        }
        assert imports <= allowed, (path, imports - allowed)
