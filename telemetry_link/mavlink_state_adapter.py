from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, cast

from contracts.platform.common import ClockStamp, SchemaVersion, SourceId
from contracts.platform.vehicle_state import VehicleStateSnapshot


class MavlinkVehicleStateAdapter:
    """Projects one StateCache publication cut into the platform DTO."""

    def __init__(self, provider: Callable[[str | None], object], source_provider: Callable[[], str]) -> None:
        self._provider = provider
        self._source_provider = source_provider

    def snapshot(self, source: SourceId | None = None) -> VehicleStateSnapshot:
        selected = source or cast(SourceId, self._source_provider())
        cache = self._provider(selected)
        publication = cache.atomic_publication(time.time())
        return self._project(selected, publication)

    def wait_next(self, *, after_session_id: str, after_sequence: int, timeout_s: float,
                  source: SourceId | None = None) -> VehicleStateSnapshot | None:
        selected = source or cast(SourceId, self._source_provider())
        cache = self._provider(selected)
        publication = cache.wait_publication(after_session_id, after_sequence, timeout_s)
        return None if publication is None else self._project(selected, publication)

    @staticmethod
    def _project(source: SourceId, publication: dict[str, object]) -> VehicleStateSnapshot:
        state = publication["drone"]
        gimbal = publication["gimbal"]
        link = publication["link"]
        now_wall = float(publication["captured_at_wall"])
        age = lambda sample: None if float(sample or 0.0) <= 0 else max(0.0, now_wall - float(sample))
        valid = lambda name: bool(getattr(state, name, False))
        return VehicleStateSnapshot(
            schema=SchemaVersion(1, 0), source=source,
            link_session_id=str(publication["session_id"]), sequence=int(publication["sequence"]),
            captured_at=ClockStamp(datetime.fromtimestamp(now_wall, timezone.utc), int(publication["captured_at_monotonic_ns"]), str(publication["clock_domain_id"])),
            connected=bool(getattr(state, "connected", False)), stale=bool(getattr(state, "stale", True)),
            control_allowed=bool(getattr(state, "control_allowed", False)),
            target_system_id=int(getattr(link, "target_system", 0)) or None,
            target_component_id=int(getattr(link, "target_component", 0)) or None,
            last_rx_age_s=age(getattr(link, "last_rx_time", 0.0)), armed=bool(getattr(state, "armed", False)),
            mode=str(getattr(state, "mode", "")) or None,
            landed=getattr(state, "landed", None), in_air=getattr(state, "in_air", None),
            failsafe=getattr(state, "failsafe", None),
            roll_rad=float(getattr(state, "roll", 0.0)) if valid("attitude_valid") else None,
            pitch_rad=float(getattr(state, "pitch", 0.0)) if valid("attitude_valid") else None,
            yaw_rad=float(getattr(state, "yaw", 0.0)) if valid("attitude_valid") else None,
            yaw_rate_rad_s=getattr(state, "yaw_rate", None) if valid("attitude_valid") else None,
            attitude_age_s=age(getattr(state, "last_attitude_time", 0.0)),
            local_north_m=float(getattr(state, "local_x", 0.0)) if valid("local_position_valid") else None,
            local_east_m=float(getattr(state, "local_y", 0.0)) if valid("local_position_valid") else None,
            local_down_m=float(getattr(state, "local_z", 0.0)) if valid("local_position_valid") else None,
            velocity_north_mps=float(getattr(state, "vx", 0.0)) if valid("velocity_valid") else None,
            velocity_east_mps=float(getattr(state, "vy", 0.0)) if valid("velocity_valid") else None,
            velocity_down_mps=float(getattr(state, "vz", 0.0)) if valid("velocity_valid") else None,
            local_valid=valid("local_position_valid"), local_age_s=age(getattr(state, "last_local_position_time", 0.0)),
            latitude_deg=float(getattr(state, "lat", 0.0)) if valid("global_position_valid") else None,
            longitude_deg=float(getattr(state, "lon", 0.0)) if valid("global_position_valid") else None,
            altitude_msl_m=float(getattr(state, "altitude", 0.0)) if valid("altitude_valid") else None,
            relative_altitude_m=float(getattr(state, "relative_altitude", 0.0)) if valid("relative_alt_valid") else None,
            global_valid=valid("global_position_valid"), global_age_s=age(getattr(state, "last_global_position_time", 0.0)),
            global_position_received_at_utc_s=(
                float(getattr(state, "last_global_position_time", 0.0))
                if float(getattr(state, "last_global_position_time", 0.0)) > 0.0
                else None
            ),
            gps_fix_type=int(getattr(state, "gps_fix_type", 0)) or None,
            satellites_visible=int(getattr(state, "satellites_visible", 0)) or None,
            gps_eph_m=float(getattr(state, "gps_eph", -1.0)) if float(getattr(state, "gps_eph", -1.0)) >= 0 else None,
            gps_epv_m=float(getattr(state, "gps_epv", -1.0)) if float(getattr(state, "gps_epv", -1.0)) >= 0 else None,
            gps_valid=int(getattr(state, "gps_fix_type", 0)) >= 3,
            battery_voltage_v=float(getattr(state, "battery_voltage", 0.0)) if valid("battery_valid") else None,
            battery_current_a=None,
            battery_remaining_pct=float(getattr(state, "battery_remaining", -1)) if valid("battery_valid") and int(getattr(state, "battery_remaining", -1)) >= 0 else None,
            battery_valid=valid("battery_valid"),
            gimbal_yaw_rad=float(getattr(gimbal, "yaw", 0.0)) if bool(getattr(gimbal, "gimbal_valid", False)) else None,
            gimbal_pitch_rad=float(getattr(gimbal, "pitch", 0.0)) if bool(getattr(gimbal, "gimbal_valid", False)) else None,
            gimbal_roll_rad=float(getattr(gimbal, "roll", 0.0)) if bool(getattr(gimbal, "gimbal_valid", False)) else None,
            gimbal_valid=bool(getattr(gimbal, "gimbal_valid", False)), gimbal_age_s=age(getattr(gimbal, "last_update_time", 0.0)),
        )
