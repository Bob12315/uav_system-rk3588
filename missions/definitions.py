from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from contracts.core.action import ExitBarrier
from contracts.effects import _EFFECT_TYPES

from missions.common.actions.base import ActionModule


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """Single public definition consumed by registry, Web and validators."""

    name: str
    factory: type[ActionModule]
    label: str
    description: str
    revision: str = "v1"
    default_params: dict[str, Any] = field(default_factory=dict)
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    required_inputs: tuple[str, ...] = ()
    output_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "additionalProperties": False})
    # canonical parameter -> accepted legacy spellings (a dotted spelling is
    # resolved from a nested object, e.g. ``config.kp_vx``).
    parameter_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    allowed_effect_types: tuple[str, ...] = ()
    exit_barrier: ExitBarrier = ExitBarrier.NONE

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("action definition name must be non-empty")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("action definition revision must be non-empty")
        if not isinstance(self.factory, type) or not issubclass(self.factory, ActionModule):
            raise TypeError("action definition factory must be an ActionModule subclass")
        for name, schema in (("parameter_schema", self.parameter_schema), ("output_schema", self.output_schema)):
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ValueError(f"{name} must be an object schema")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise ValueError(f"invalid {name}: {exc.message}") from exc
        if self.parameter_schema.get("additionalProperties") is not False:
            raise ValueError("parameter_schema.additionalProperties must be false")
        unknown = set(self.allowed_effect_types) - set(_EFFECT_TYPES)
        if unknown:
            raise ValueError(f"unknown action effect types: {sorted(unknown)}")
        if not isinstance(self.exit_barrier, ExitBarrier):
            raise ValueError("exit_barrier must be an ExitBarrier")
        unknown_default = set(self.default_params) - set(self.parameter_schema.get("properties", {}))
        if unknown_default:
            raise ValueError(f"default params reference unknown fields: {sorted(unknown_default)}")
        unknown_canonical = set(self.parameter_aliases) - set(self.parameter_schema.get("properties", {}))
        if unknown_canonical:
            raise ValueError(f"parameter aliases reference unknown canonical fields: {sorted(unknown_canonical)}")

    def merge_and_validate_params(self, raw_params: dict[str, Any] | None) -> dict[str, Any]:
        if raw_params is not None and not isinstance(raw_params, dict):
            raise ValueError("params must be an object")
        raw = dict(raw_params or {})
        params = self.normalize_params(raw)
        # Defaults are deliberately applied only after aliases.  A legacy
        # value must therefore never be hidden by a canonical default.
        for key, value in self.default_params.items():
            params.setdefault(key, value)
        self.validate_params(params)
        return params

    def normalize_params(self, raw_params: dict[str, Any]) -> dict[str, Any]:
        """Return effective canonical parameters without mutating caller data.

        An explicitly supplied canonical value wins, including ``None``.  If
        it is absent, the first present legacy spelling is copied verbatim.
        This preserves the Actions' historic distinction between a missing
        value and an explicit null while making the precedence testable here.
        """
        params = dict(raw_params)
        for canonical, aliases in self.parameter_aliases.items():
            if canonical in raw_params:
                continue
            for alias in aliases:
                found, value = self._lookup(raw_params, alias)
                if found:
                    params[canonical] = value
                    break
        return params

    @staticmethod
    def _lookup(params: dict[str, Any], path: str) -> tuple[bool, Any]:
        value: Any = params
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return False, None
            value = value[part]
        return True, value

    def validate_params(self, params: dict[str, Any]) -> None:
        self._validate(self.parameter_schema, params)

    def validate_output(self, output: dict[str, Any]) -> None:
        self._validate(self.output_schema, output)

    @staticmethod
    def _validate(schema: dict[str, Any], value: dict[str, Any]) -> None:
        try:
            Draft202012Validator(schema).validate(value)
        except ValidationError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "$"
            raise ValueError(f"{path}: {exc.message}") from exc

    def web_spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "revision": self.revision,
            "label": self.label,
            "description": self.description,
            "default_params": self.default_params,
            "parameter_schema": self.parameter_schema,
            "required_inputs": list(self.required_inputs),
            "output_schema": self.output_schema,
            "parameter_aliases": {key: list(value) for key, value in self.parameter_aliases.items()},
            "allowed_effect_types": list(self.allowed_effect_types),
            "exit_barrier": self.exit_barrier.value,
        }
