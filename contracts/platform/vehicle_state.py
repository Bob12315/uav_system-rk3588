from __future__ import annotations

from dataclasses import dataclass

from .common import ClockStamp, SchemaVersion, SourceId


@dataclass(frozen=True, slots=True)
class VehicleStateSnapshot:
    schema: SchemaVersion
    source: SourceId
    link_session_id: str
    sequence: int
    captured_at: ClockStamp
    connected: bool
    stale: bool
    control_allowed: bool
    target_system_id: int | None
    target_component_id: int | None
    last_rx_age_s: float | None
    armed: bool
    mode: str | None
    landed: bool | None
    in_air: bool | None
    failsafe: bool | None
    roll_rad: float | None
    pitch_rad: float | None
    yaw_rad: float | None
    yaw_rate_rad_s: float | None
    attitude_age_s: float | None
    local_north_m: float | None
    local_east_m: float | None
    local_down_m: float | None
    velocity_north_mps: float | None
    velocity_east_mps: float | None
    velocity_down_mps: float | None
    local_valid: bool
    local_age_s: float | None
    latitude_deg: float | None
    longitude_deg: float | None
    altitude_msl_m: float | None
    relative_altitude_m: float | None
    global_valid: bool
    global_age_s: float | None
    # Exact local receive timestamp of the latest GLOBAL_POSITION_INT frame.
    # Unlike ``captured_at - global_age_s``, this value is stable while a
    # snapshot is republished and is safe as a GPS-sample identity.
    global_position_received_at_utc_s: float | None
    gps_fix_type: int | None
    satellites_visible: int | None
    gps_eph_m: float | None
    gps_epv_m: float | None
    gps_valid: bool
    battery_voltage_v: float | None
    battery_current_a: float | None
    battery_remaining_pct: float | None
    battery_valid: bool
    gimbal_yaw_rad: float | None
    gimbal_pitch_rad: float | None
    gimbal_roll_rad: float | None
    gimbal_valid: bool
    gimbal_age_s: float | None

    def __post_init__(self) -> None:
        if not self.link_session_id or self.sequence < 0:
            raise ValueError("invalid vehicle publication identity")


@dataclass(frozen=True, slots=True)
class LinkControlSnapshot:
    source: SourceId
    revision: int
    connected: bool
    link_session_id: str


@dataclass(frozen=True, slots=True)
class SourceSwitchReceipt:
    accepted: bool
    previous_source: SourceId
    active_source: SourceId
    revision: int
    reason_code: str
    barrier_disposition: str | None = None
    barrier_id: str | None = None
