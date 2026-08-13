from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldPoint:
    x_m: float
    y_m: float
    altitude_m: float
