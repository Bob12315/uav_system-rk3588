from __future__ import annotations

import logging
import threading
import time

from pymavlink import mavutil

try:
    from .config import TelemetryConfig
    from .mavlink_client import MavlinkClient
    from .state_cache import StateCache
    from .telemetry_parser import (
        control_allowed_for_mode,
        decode_copter_mode,
        global_position_is_valid,
        heartbeat_is_armed,
        parse_gimbal_device_attitude_status,
        parse_mount_status,
        parse_sys_status_values,
    )
except ImportError:  # pragma: no cover - supports direct script execution
    from config import TelemetryConfig
    from mavlink_client import MavlinkClient
    from state_cache import StateCache
    from telemetry_parser import (
        control_allowed_for_mode,
        decode_copter_mode,
        global_position_is_valid,
        heartbeat_is_armed,
        parse_gimbal_device_attitude_status,
        parse_mount_status,
        parse_sys_status_values,
    )


class TelemetryReceiver(threading.Thread):
    def __init__(self, client: MavlinkClient, state_cache: StateCache, cfg: TelemetryConfig, stop_event: threading.Event) -> None:
        super().__init__(name="TelemetryReceiver", daemon=True)
        self.client = client
        self.state_cache = state_cache
        self.cfg = cfg
        self.stop_event = stop_event
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self) -> None:
        while not self.stop_event.is_set():
            now = time.time()
            self._check_timeouts(now)
            try:
                message = self.client.recv_message(timeout=0.2)
            except Exception as exc:
                self.logger.warning("recv_message failed: %s", exc)
                time.sleep(self.cfg.receiver_idle_sleep_sec)
                continue

            if message is None:
                self._check_timeouts(time.time())
                time.sleep(self.cfg.receiver_idle_sleep_sec)
                continue

            now = time.time()
            msg_type = message.get_type()
            self.state_cache.update_link(last_rx_time=now)
            self.state_cache.update_state(last_message_type=msg_type)
            self._handle_message(msg_type, message, now)

    def _check_timeouts(self, now: float) -> None:
        link = self.state_cache.get_link_status()
        if link.reconnecting or not link.connected:
            return

        if link.last_heartbeat_time > 0 and (now - link.last_heartbeat_time) > self.cfg.heartbeat_timeout_sec:
            self.logger.warning("Heartbeat timeout, mark link disconnected")
            self.state_cache.mark_disconnected("heartbeat_timeout")
            return

        if link.last_rx_time > 0 and (now - link.last_rx_time) > self.cfg.rx_timeout_sec:
            self.logger.warning("RX timeout, mark link disconnected")
            self.state_cache.mark_disconnected("rx_timeout")
            return

    def _handle_message(self, msg_type: str, message, now: float) -> None:
        if msg_type == "HEARTBEAT":
            if not self._is_autopilot_heartbeat(message):
                return
            armed = heartbeat_is_armed(message.base_mode)
            mode = decode_copter_mode(message.custom_mode)
            self.state_cache.update_drone_state(
                connected=True,
                stale=False,
                armed=armed,
                mode=mode,
                control_allowed=control_allowed_for_mode(mode),
                last_heartbeat_time=now,
            )
            self.state_cache.update_link(
                connected=True,
                reconnecting=False,
                last_rx_time=now,
                last_heartbeat_time=now,
                status_text="connected",
            )
            return

        if msg_type == "ATTITUDE":
            self.state_cache.update_drone_state(
                attitude_valid=True,
                roll=float(message.roll),
                pitch=float(message.pitch),
                yaw=float(message.yaw),
                roll_rate=float(message.rollspeed),
                pitch_rate=float(message.pitchspeed),
                yaw_rate=float(message.yawspeed),
                last_attitude_time=now,
            )
            return

        if msg_type == "GLOBAL_POSITION_INT":
            lat = float(message.lat) / 1e7
            lon = float(message.lon) / 1e7
            self.state_cache.update_drone_state(
                altitude_valid=True,
                lat=lat,
                lon=lon,
                altitude=float(message.alt) / 1000.0,
                relative_altitude=float(message.relative_alt) / 1000.0,
                relative_alt_valid=True,
                last_altitude_time=now,
                last_global_position_time=now,
                last_relative_alt_time=now,
                global_position_valid=global_position_is_valid(
                    lat,
                    lon,
                    self.state_cache.get_latest_drone_state_raw().gps_fix_type,
                ),
            )
            return

        if msg_type == "LOCAL_POSITION_NED":
            raw_state = self.state_cache.get_latest_drone_state_raw()
            self.state_cache.update_drone_state(
                velocity_valid=True,
                local_x=float(message.x),
                local_y=float(message.y),
                local_z=float(message.z),
                vx=float(message.vx),
                vy=float(message.vy),
                vz=float(message.vz),
                last_velocity_time=now,
                velocity_source="ekf",
                velocity_quality="good" if int(raw_state.gps_fix_type) >= 3 else "poor",
                relative_altitude=float(-message.z),
                local_position_valid=True,
                relative_alt_valid=True,
                last_local_position_time=now,
                last_relative_alt_time=now,
            )
            return

        if msg_type == "VFR_HUD":
            self.state_cache.update_drone_state(
                altitude_valid=True,
                altitude=float(message.alt),
                last_altitude_time=now,
            )
            return

        if msg_type == "SYS_STATUS":
            voltage_v, _current_a, percentage = parse_sys_status_values(
                message.voltage_battery,
                message.current_battery,
                message.battery_remaining,
            )
            self.state_cache.update_drone_state(
                battery_valid=True,
                battery_voltage=voltage_v,
                battery_remaining=int(round(percentage * 100.0)) if percentage == percentage else -1,
                last_battery_time=now,
            )
            return

        if msg_type == "GPS_RAW_INT":
            gps_fix_type = int(message.fix_type)
            satellites_visible = int(message.satellites_visible)
            raw_state = self.state_cache.get_latest_drone_state_raw()
            self.state_cache.update_drone_state(
                gps_fix_type=gps_fix_type,
                satellites_visible=satellites_visible,
                gps_eph=float(getattr(message, "eph", -1)) / 100.0 if int(getattr(message, "eph", -1)) >= 0 else -1.0,
                gps_epv=float(getattr(message, "epv", -1)) / 100.0 if int(getattr(message, "epv", -1)) >= 0 else -1.0,
                global_position_valid=global_position_is_valid(raw_state.lat, raw_state.lon, gps_fix_type),
            )
            return

        if msg_type == "MOUNT_STATUS":
            if self._should_ignore_mount_status(now):
                return
            pitch_deg, roll_deg, yaw_deg = parse_mount_status(
                int(message.pointing_a),
                int(message.pointing_b),
                int(message.pointing_c),
            )
            self.state_cache.update_gimbal_state(
                gimbal_valid=True,
                pitch=pitch_deg,
                roll=roll_deg,
                yaw=yaw_deg,
                source_msg_type="MOUNT_STATUS",
                last_update_time=now,
                raw_quaternion=None,
            )
            return

        if msg_type == "GIMBAL_DEVICE_ATTITUDE_STATUS":
            pitch_deg, roll_deg, yaw_deg, valid = self._parse_gimbal_device_attitude(message)
            self.state_cache.update_gimbal_state(
                gimbal_valid=valid,
                yaw=yaw_deg,
                pitch=pitch_deg,
                roll=roll_deg,
                source_msg_type="GIMBAL_DEVICE_ATTITUDE_STATUS",
                last_update_time=now,
                raw_quaternion=tuple(float(v) for v in getattr(message, "q", [])) or None,
            )
            return

        if msg_type == "RC_CHANNELS":
            return

    def _is_autopilot_heartbeat(self, message) -> bool:
        autopilot = int(getattr(message, "autopilot", mavutil.mavlink.MAV_AUTOPILOT_INVALID))
        mav_type = int(getattr(message, "type", mavutil.mavlink.MAV_TYPE_GCS))
        return autopilot != mavutil.mavlink.MAV_AUTOPILOT_INVALID and mav_type != mavutil.mavlink.MAV_TYPE_GCS

    def _parse_gimbal_device_attitude(self, message) -> tuple[float, float, float, bool]:
        q = [float(v) for v in getattr(message, "q", [])]
        if len(q) != 4:
            return 0.0, 0.0, 0.0, False
        try:
            pitch_deg, roll_deg, yaw_deg = parse_gimbal_device_attitude_status(q)
        except Exception as exc:
            self.logger.debug("failed to decode gimbal quaternion: %s", exc)
            return 0.0, 0.0, 0.0, False
        return float(pitch_deg), float(roll_deg), float(yaw_deg), True

    def _should_ignore_mount_status(self, now: float) -> bool:
        current = self.state_cache.get_latest_gimbal_state_raw()
        if current.source_msg_type != "GIMBAL_DEVICE_ATTITUDE_STATUS":
            return False
        if current.last_update_time <= 0:
            return False
        return (now - current.last_update_time) <= self.cfg.rx_timeout_sec
