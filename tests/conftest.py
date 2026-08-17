from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _web_operator_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production startup fails closed; tests use a disposable credential."""
    monkeypatch.setenv("UAV_WEB_OPERATOR_PASSWORD", "test-only-operator-password")
