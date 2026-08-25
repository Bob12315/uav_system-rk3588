from __future__ import annotations

import hashlib
import json

from contracts.core.action import ExitBarrier
from contracts.core.common import MissionDefinitionId, StepId, freeze_json
from contracts.core.mission import (
    BlackboardRefExpr,
    FailureMode,
    FailurePolicy,
    LiteralExpr,
    MissionDefinition,
    StepDefinition,
)
from contracts.platform.common import SchemaVersion

from .action_catalog import ActionDefinitionCatalog


class MissionCompiler:
    def __init__(self, catalog: ActionDefinitionCatalog) -> None:
        self._catalog = catalog

    def compile(self, document: dict[str, object]) -> MissionDefinition:
        if document.get("version") != 2:
            raise ValueError("only Mission template v2 is supported")
        name = str(document.get("name") or "")
        raw_steps = document.get("steps")
        if not name or not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("Mission name and non-empty steps are required")
        label_ids: dict[str, StepId] = {}
        for index, item in enumerate(raw_steps):
            if not isinstance(item, dict):
                raise ValueError("Mission step must be an object")
            label = str(item.get("label") or f"step_{index}")
            if label in label_ids:
                raise ValueError(f"duplicate Mission label: {label}")
            label_ids[label] = StepId(f"{index}:{label}")
        steps: list[StepDefinition] = []
        for index, item in enumerate(raw_steps):
            assert isinstance(item, dict)
            action_name = str(item.get("name") or "")
            definition = self._catalog.get(action_name)
            if definition is None:
                raise ValueError(f"unknown Action: {action_name}")
            label = str(item.get("label") or f"step_{index}")
            params = item.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError(f"step {label} params must be an object")
            encoded = freeze_json(self._compile_value(self._normalize_v2_params(action_name, params)))
            if not hasattr(encoded, "items_tuple"):
                raise ValueError("compiled Action params must be an object")
            failure = self._failure_policy(item.get("on_failed"), label_ids)
            barrier = definition.minimum_exit_barrier
            declared = item.get("exit_barrier")
            if declared == ExitBarrier.MOTION_STOPPED.value:
                barrier = ExitBarrier.MOTION_STOPPED
            steps.append(StepDefinition(
                label_ids[label], label, definition.contract_ref, encoded,
                str(item["save_as"]) if item.get("save_as") else None,
                failure, barrier,
            ))
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        revision = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return MissionDefinition(
            SchemaVersion(3, 0), MissionDefinitionId(name), revision, name,
            tuple(steps), max(64, len(steps) * 8), max(128, len(steps) * 16), 16,
        )

    def _compile_value(self, value: object) -> object:
        if isinstance(value, str) and value.startswith("$"):
            parts = value[1:].split(".")
            path: list[str | int] = []
            for part in parts[1:]:
                path.append(int(part) if part.isdigit() else part)
            expression = BlackboardRefExpr(parts[0], tuple(path))
            return {"$blackboard": expression.root_key, "path": list(expression.path)}
        if isinstance(value, dict):
            return {key: self._compile_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._compile_value(item) for item in value]
        return value

    @staticmethod
    def _normalize_v2_params(action_name: str, params: dict[str, object]) -> dict[str, object]:
        """Remove legacy dispatch knobs now owned by trusted core contracts."""
        if action_name == "takeoff":
            return {
                "mode": params.get("mode", "GUIDED"),
                "altitude_m": params.get("altitude_m", 5.0),
                "require_armed": params.get("require_armed", True),
            }
        if action_name == "land":
            return {}
        if action_name == "change_speed":
            return {"speed_mps": params.get("speed_mps", 1.0)}
        return params

    @staticmethod
    def _failure_policy(value: object, labels: dict[str, StepId]) -> FailurePolicy:
        if value is None:
            return FailurePolicy(FailureMode.FAIL)
        if not isinstance(value, dict):
            raise ValueError("on_failed must be an object")
        action = str(value.get("action") or "fail")
        if action == "continue":
            return FailurePolicy(FailureMode.CONTINUE)
        if action == "retry":
            attempts = int(value.get("max_attempts", 1))
            return FailurePolicy(FailureMode.RETRY, max_retries=attempts,
                                 retry_delay_ms=int(value.get("delay_ms", 0)))
        if action == "retry_current_then_jump_to":
            target = str(value.get("target") or "")
            if target not in labels:
                raise ValueError(f"unknown jump label: {target}")
            return FailurePolicy(
                FailureMode.RETRY,
                max_retries=int(value.get("max_attempts", 1)),
                jump_target=labels[target],
                retry_delay_ms=int(value.get("delay_ms", 0)),
            )
        if action == "jump_to":
            target = str(value.get("target") or "")
            if target not in labels:
                raise ValueError(f"unknown jump label: {target}")
            return FailurePolicy(FailureMode.JUMP, max_retries=int(value.get("max_attempts", 0)),
                                 jump_target=labels[target])
        if action != "fail":
            raise ValueError(f"unsupported failure policy: {action}")
        return FailurePolicy(FailureMode.FAIL)
