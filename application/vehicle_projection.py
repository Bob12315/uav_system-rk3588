from __future__ import annotations

from contracts.platform.vehicle_state import VehicleStateSnapshot
from telemetry_link.models import DroneState, GimbalState, LinkStatus


def project_legacy_vehicle_frame(
    snapshot: VehicleStateSnapshot,
) -> tuple[DroneState, GimbalState, LinkStatus]:
    """Compatibility projection from one immutable platform publication cut."""
    captured = snapshot.captured_at.utc.timestamp()
    sample_time = lambda age: 0.0 if age is None else max(0.0, captured - age)
    drone = DroneState(
        timestamp=captured,
        connected=snapshot.connected,
        stale=snapshot.stale,
        last_rx_time=sample_time(snapshot.last_rx_age_s),
        hb_age_sec=float("inf") if snapshot.last_rx_age_s is None else snapshot.last_rx_age_s,
        rx_age_sec=float("inf") if snapshot.last_rx_age_s is None else snapshot.last_rx_age_s,
        armed=snapshot.armed,
        landed=snapshot.landed,
        in_air=snapshot.in_air,
        failsafe=snapshot.failsafe,
        mode=snapshot.mode or "UNKNOWN",
        control_allowed=snapshot.control_allowed,
        attitude_valid=snapshot.roll_rad is not None,
        velocity_valid=snapshot.velocity_north_mps is not None,
        altitude_valid=snapshot.altitude_msl_m is not None,
        battery_valid=snapshot.battery_valid,
        global_position_valid=snapshot.global_valid,
        relative_alt_valid=snapshot.relative_altitude_m is not None,
        local_position_valid=snapshot.local_valid,
        last_attitude_time=sample_time(snapshot.attitude_age_s),
        last_velocity_time=sample_time(snapshot.local_age_s),
        last_altitude_time=sample_time(snapshot.global_age_s),
        last_battery_time=captured if snapshot.battery_valid else 0.0,
        last_global_position_time=sample_time(snapshot.global_age_s),
        last_relative_alt_time=sample_time(snapshot.global_age_s),
        last_local_position_time=sample_time(snapshot.local_age_s),
        roll=snapshot.roll_rad or 0.0,
        pitch=snapshot.pitch_rad or 0.0,
        yaw=snapshot.yaw_rad or 0.0,
        yaw_rate=snapshot.yaw_rate_rad_s,
        vx=snapshot.velocity_north_mps or 0.0,
        vy=snapshot.velocity_east_mps or 0.0,
        vz=snapshot.velocity_down_mps or 0.0,
        local_x=snapshot.local_north_m or 0.0,
        local_y=snapshot.local_east_m or 0.0,
        local_z=snapshot.local_down_m or 0.0,
        altitude=snapshot.altitude_msl_m or 0.0,
        relative_altitude=snapshot.relative_altitude_m or 0.0,
        lat=snapshot.latitude_deg or 0.0,
        lon=snapshot.longitude_deg or 0.0,
        battery_voltage=snapshot.battery_voltage_v or 0.0,
        battery_remaining=-1 if snapshot.battery_remaining_pct is None else round(snapshot.battery_remaining_pct),
        gps_fix_type=snapshot.gps_fix_type or 0,
        satellites_visible=snapshot.satellites_visible or 0,
        gps_eph=-1.0 if snapshot.gps_eph_m is None else snapshot.gps_eph_m,
        gps_epv=-1.0 if snapshot.gps_epv_m is None else snapshot.gps_epv_m,
    )
    gimbal = GimbalState(
        timestamp=captured,
        gimbal_valid=snapshot.gimbal_valid,
        yaw=snapshot.gimbal_yaw_rad or 0.0,
        pitch=snapshot.gimbal_pitch_rad or 0.0,
        roll=snapshot.gimbal_roll_rad or 0.0,
        last_update_time=sample_time(snapshot.gimbal_age_s),
    )
    link = LinkStatus(
        connected=snapshot.connected,
        reconnecting=False,
        last_rx_time=sample_time(snapshot.last_rx_age_s),
        target_system=snapshot.target_system_id or 0,
        target_component=snapshot.target_component_id or 0,
        status_text="connected" if snapshot.connected and not snapshot.stale else "disconnected",
    )
    return drone, gimbal, link
