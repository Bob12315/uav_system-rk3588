from __future__ import annotations

import math
from dataclasses import dataclass

from .field_reference import FieldReference, FieldReferenceError


# ---------------------------------------------------------------------------
# coordinate point types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LocalNedPoint:
    """A point in the LOCAL_NED frame.

    ``north_m`` / ``east_m`` / ``z_down_m`` follow the conventions in
    ``docs/reference/coordinate_frames.md``.
    """

    north_m: float
    east_m: float
    z_down_m: float


@dataclass(slots=True)
class FieldPoint:
    """A point in the FIELD frame.

    ``field_x_m`` is +right, ``field_y_m`` is +forward,
    ``altitude_m`` is positive-up.
    """

    field_x_m: float
    field_y_m: float
    altitude_m: float


# ---------------------------------------------------------------------------
# transform functions
# ---------------------------------------------------------------------------

def field_to_local_ned(
    field_x_m: float,
    field_y_m: float,
    altitude_m: float,
    reference: FieldReference,
) -> LocalNedPoint:
    """Convert FIELD coordinates to LOCAL_NED.

    Implements the formula from ``docs/reference/coordinate_frames.md``::

        forward_N = cos(field_heading_yaw_rad)
        forward_E = sin(field_heading_yaw_rad)

        right_N = -sin(field_heading_yaw_rad)
        right_E =  cos(field_heading_yaw_rad)

        local_N = origin_N + field_y_m * forward_N + field_x_m * right_N
        local_E = origin_E + field_y_m * forward_E + field_x_m * right_E
        z_down  = -altitude_m

    Raises :exc:`FieldReferenceError` if *reference* is not ready.
    """
    if not reference.is_ready():
        raise FieldReferenceError(
            "FieldReference is not ready for coordinate transform"
        )

    yaw = reference.field_heading_yaw_rad  # type: float  (guaranteed by is_ready)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    # forward  = (cos_yaw,  sin_yaw)   -- FIELD +Y in LOCAL_NED
    # right    = (-sin_yaw, cos_yaw)   -- FIELD +X in LOCAL_NED
    local_n = (
        reference.origin_local_n_m
        + field_y_m * cos_yaw
        + field_x_m * (-sin_yaw)
    )
    local_e = (
        reference.origin_local_e_m
        + field_y_m * sin_yaw
        + field_x_m * cos_yaw
    )

    return LocalNedPoint(
        north_m=local_n,
        east_m=local_e,
        z_down_m=-altitude_m,
    )


def local_ned_to_field(
    north_m: float,
    east_m: float,
    z_down_m: float,
    reference: FieldReference,
) -> FieldPoint:
    """Convert LOCAL_NED coordinates to FIELD (inverse of
    :func:`field_to_local_ned`).

    Raises :exc:`FieldReferenceError` if *reference* is not ready.
    """
    if not reference.is_ready():
        raise FieldReferenceError(
            "FieldReference is not ready for coordinate transform"
        )

    yaw = reference.field_heading_yaw_rad  # type: float
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    dn = north_m - reference.origin_local_n_m
    de = east_m - reference.origin_local_e_m

    # inverse rotation
    field_y = dn * cos_yaw + de * sin_yaw
    field_x = -dn * sin_yaw + de * cos_yaw

    return FieldPoint(
        field_x_m=field_x,
        field_y_m=field_y,
        altitude_m=-z_down_m,
    )
