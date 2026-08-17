from dataclasses import FrozenInstanceError

import pytest

from contracts.core.common import FrozenObject, freeze_json, thaw_json
from contracts.platform.common import ResourceVersion


def test_frozen_json_is_deep_immutable_and_canonical() -> None:
    source = {"b": [1, {"x": True}], "a": 2.5}
    frozen = freeze_json(source)
    source["b"].append(9)
    assert isinstance(frozen, FrozenObject)
    assert tuple(frozen) == ("a", "b")
    assert thaw_json(frozen) == {"a": 2.5, "b": [1, {"x": True}]}
    assert hash(frozen)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "bad"}, b"bad"])
def test_frozen_json_rejects_undefined_values(value) -> None:
    with pytest.raises((TypeError, ValueError)):
        freeze_json(value)


def test_resource_version_is_monotonic_and_frozen() -> None:
    version = ResourceVersion("session", 1)
    assert version.next() == ResourceVersion("session", 2)
    with pytest.raises(FrozenInstanceError):
        version.revision = 4  # type: ignore[misc]
