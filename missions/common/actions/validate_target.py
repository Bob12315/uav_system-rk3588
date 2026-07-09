from __future__ import annotations

import math
from typing import Any

from .base import ActionModule
from .result import ActionResult


class ValidateTargetAction(ActionModule):
    """Validate a target dict: check valid flag and lat/lon presence.

    Outputs done on success, failed on any check failure.
    Designed to gate subsequent drop steps so missing/invalid
    targets skip the entire payload group.
    """

    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}
        self._target = data.get("target")
        self._require_valid = bool(data.get("require_valid", True))
        self._require_lat_lon = bool(data.get("require_lat_lon", True))
        self._key = str(data.get("key") or "validate_target")
        self._started = True
        self._stopped = False
        self._done = False

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self._started:
            return ActionResult(failed=True, reason="action_not_started")
        if self._stopped:
            return ActionResult(done=True, reason="stopped")
        if self._done:
            return ActionResult(
                done=True, reason="target_valid", detail=self._detail(valid=True),
            )

        target = self._target
        if not isinstance(target, dict):
            self._done = True
            return ActionResult(
                failed=True,
                reason="invalid_target",
                detail=self._detail(valid=False, note="target is not a dict"),
            )

        if self._require_valid and target.get("valid") is False:
            self._done = True
            return ActionResult(
                failed=True,
                reason="target_not_valid",
                detail=self._detail(valid=False, note="target.valid is false"),
            )

        if self._require_lat_lon:
            lat = self._optional_finite_float(target.get("lat"))
            lon = self._optional_finite_float(target.get("lon"))
            if lat is None or lon is None:
                self._done = True
                return ActionResult(
                    failed=True,
                    reason="missing_target_gps",
                    detail=self._detail(
                        valid=target.get("valid"),
                        lat=target.get("lat"),
                        lon=target.get("lon"),
                        note="target missing valid lat/lon",
                    ),
                )

        self._done = True
        return ActionResult(
            done=True,
            reason="target_valid",
            detail=self._detail(valid=True),
        )

    def stop(self) -> None:
        self._stopped = True

    def reset(self) -> None:
        self._target: Any = None
        self._require_valid = True
        self._require_lat_lon = True
        self._key = "validate_target"
        self._started = False
        self._stopped = False
        self._done = False

    def _detail(self, *, valid: bool, **extra: Any) -> dict[str, Any]:
        target = self._target if isinstance(self._target, dict) else {}
        detail: dict[str, Any] = {
            "valid": bool(valid),
            "target_id": target.get("id") or target.get("target_id"),
            "class_name": target.get("class_name"),
            "lat": target.get("lat"),
            "lon": target.get("lon"),
            "key": self._key,
        }
        detail.update(extra)
        return detail

    @staticmethod
    def _optional_finite_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None
