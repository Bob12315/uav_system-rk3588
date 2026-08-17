from __future__ import annotations

from contracts.core.action import CodecResult
from contracts.core.common import FrozenJson, FrozenObject, freeze_json


class FrozenJsonCodec:
    """Bounded compatibility codec used until an Action supplies a narrower codec."""

    def __init__(self, *, require_object: bool = False) -> None:
        self._require_object = require_object

    def validate_encoded(self, value: FrozenJson) -> CodecResult[None]:
        if self._require_object and not isinstance(value, FrozenObject):
            return CodecResult(None, "expected_object")
        return CodecResult(None)

    def decode(self, value: FrozenJson) -> CodecResult[object]:
        validated = self.validate_encoded(value)
        return CodecResult(value, validated.reason_code)

    def encode(self, value: object) -> CodecResult[FrozenJson]:
        try:
            return CodecResult(freeze_json(value))
        except (TypeError, ValueError):
            return CodecResult(None, "not_frozen_json")
