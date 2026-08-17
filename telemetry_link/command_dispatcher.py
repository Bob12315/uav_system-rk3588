from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from pymavlink import mavutil

try:
    from .link_manager import LinkManager
except ImportError:  # pragma: no cover - supports direct script execution
    from link_manager import LinkManager


@dataclass(slots=True)
class CommandResult:
    ok: bool
    message: str


def _parse_float(value: str, command: str) -> float | CommandResult:
    try:
        return float(value)
    except ValueError:
        return CommandResult(False, f"parse failed: {command}")


def _global_frame(name: str) -> int | None:
    normalized = name.strip().lower()
    if normalized in {"relative", "rel", "relative_alt", "global_relative_alt"}:
        return mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
    if normalized in {"global", "abs", "absolute", "amsl"}:
        return mavutil.mavlink.MAV_FRAME_GLOBAL_INT
    if normalized in {"terrain", "agl"}:
        return mavutil.mavlink.MAV_FRAME_GLOBAL_TERRAIN_ALT_INT
    return None


def _local_frame(name: str) -> int | None:
    normalized = name.strip().lower()
    if normalized in {"local", "local_ned"}:
        return mavutil.mavlink.MAV_FRAME_LOCAL_NED
    if normalized in {"offset", "local_offset"}:
        return mavutil.mavlink.MAV_FRAME_LOCAL_OFFSET_NED
    if normalized in {"body"}:
        return mavutil.mavlink.MAV_FRAME_BODY_NED
    if normalized in {"body_offset", "bodyoffset"}:
        return mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED
    return None


def _speed_type(name: str) -> int | None:
    normalized = name.strip().lower()
    if normalized in {"air", "airspeed", "0"}:
        return 0
    if normalized in {"ground", "groundspeed", "1"}:
        return 1
    if normalized in {"climb", "2"}:
        return 2
    if normalized in {"descent", "descend", "3"}:
        return 3
    return None


def dispatch_text_command(manager: LinkManager, command: str, logger: logging.Logger | None = None) -> CommandResult:
    command = command.strip()
    if not command:
        return CommandResult(False, "empty command")

    def _log_info(message: str, *args) -> None:
        if logger is not None:
            logger.info(message, *args)

    def _log_warning(message: str, *args) -> None:
        if logger is not None:
            logger.warning(message, *args)

    if command.startswith("switch_source "):
        source_name = command.split(maxsplit=1)[1].strip()
        ok = manager.switch_active_source(source_name)
        if ok:
            _log_info("switch_source command applied active_source=%s", source_name)
            return CommandResult(True, f"switch_source queued active_source={source_name}")
        _log_warning("switch_source command rejected source=%s", source_name)
        return CommandResult(False, f"switch_source rejected source={source_name}")

    if command.startswith("mode "):
        mode_name = command.split(maxsplit=1)[1].strip()
        if not mode_name:
            return CommandResult(False, "format: mode <MODE_NAME>")
        manager.set_mode(mode_name)
        _log_info("mode command queued mode=%s", mode_name)
        return CommandResult(True, f"mode queued mode={mode_name}")

    if command in {"arm", "arm throttle"}:
        manager.arm()
        _log_info("arm command queued")
        return CommandResult(True, "arm queued")

    if command == "disarm":
        manager.disarm()
        _log_info("disarm command queued")
        return CommandResult(True, "disarm queued")

    if command.startswith("takeoff "):
        parts = command.split()
        if len(parts) != 2:
            return CommandResult(False, "format: takeoff <altitude_m>")
        try:
            altitude_m = float(parts[1])
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        manager.takeoff(altitude_m)
        _log_info("takeoff command queued altitude_m=%.2f", altitude_m)
        return CommandResult(True, f"takeoff queued altitude_m={altitude_m:.2f}")

    if command == "land":
        manager.land()
        _log_info("land command queued")
        return CommandResult(True, "land queued")

    if command.startswith("condition_yaw "):
        parts = command.split()
        if len(parts) not in {2, 3, 4, 5}:
            return CommandResult(False, "format: condition_yaw <yaw_deg> [speed_deg_s] [cw|ccw|shortest] [absolute|relative]")
        yaw_deg = _parse_float(parts[1], command)
        if isinstance(yaw_deg, CommandResult):
            return yaw_deg
        speed_deg_s = 20.0
        if len(parts) >= 3:
            parsed_speed = _parse_float(parts[2], command)
            if isinstance(parsed_speed, CommandResult):
                return parsed_speed
            speed_deg_s = parsed_speed
        direction = 0
        if len(parts) >= 4:
            direction_name = parts[3].strip().lower()
            if direction_name not in {"cw", "ccw", "shortest"}:
                return CommandResult(False, "condition_yaw direction must be cw, ccw, or shortest")
            direction = 1 if direction_name == "cw" else -1 if direction_name == "ccw" else 0
        relative = False
        if len(parts) == 5:
            relative_name = parts[4].strip().lower()
            if relative_name not in {"absolute", "relative", "abs", "rel"}:
                return CommandResult(False, "condition_yaw frame must be absolute or relative")
            relative = relative_name in {"relative", "rel"}
        manager.condition_yaw(yaw_deg, speed_deg_s, direction, relative)
        _log_info(
            "condition_yaw command queued yaw_deg=%.2f speed_deg_s=%.2f direction=%s relative=%s",
            yaw_deg,
            speed_deg_s,
            direction,
            relative,
        )
        return CommandResult(True, f"condition_yaw queued yaw={yaw_deg:.2f} speed={speed_deg_s:.2f}")

    if command.startswith("change_speed "):
        parts = command.split()
        if len(parts) not in {2, 3}:
            return CommandResult(False, "format: change_speed <speed_mps> [ground|air|climb|descent]")
        speed_mps = _parse_float(parts[1], command)
        if isinstance(speed_mps, CommandResult):
            return speed_mps
        speed_type = 1
        if len(parts) == 3:
            parsed_type = _speed_type(parts[2])
            if parsed_type is None:
                return CommandResult(False, "change_speed type must be ground, air, climb, or descent")
            speed_type = parsed_type
        manager.change_speed(speed_mps, speed_type)
        _log_info("change_speed command queued speed_mps=%.2f speed_type=%s", speed_mps, speed_type)
        return CommandResult(True, f"change_speed queued speed={speed_mps:.2f} type={speed_type}")

    if command.startswith("set_home"):
        parts = command.split()
        if len(parts) == 2 and parts[1].strip().lower() == "current":
            manager.set_home_current()
            _log_info("set_home current command queued")
            return CommandResult(True, "set_home queued current")
        if len(parts) != 4:
            return CommandResult(False, "format: set_home current | set_home <lat> <lon> <alt_m>")
        lat = _parse_float(parts[1], command)
        lon = _parse_float(parts[2], command)
        alt = _parse_float(parts[3], command)
        if isinstance(lat, CommandResult):
            return lat
        if isinstance(lon, CommandResult):
            return lon
        if isinstance(alt, CommandResult):
            return alt
        manager.set_home_location(lat, lon, alt)
        _log_info("set_home command queued lat=%.7f lon=%.7f alt=%.2f", lat, lon, alt)
        return CommandResult(True, f"set_home queued lat={lat:.7f} lon={lon:.7f} alt={alt:.2f}")

    if command.startswith("global_goto "):
        parts = command.split()
        if len(parts) not in {4, 5}:
            return CommandResult(False, "format: global_goto <lat> <lon> <alt_m> [relative|global|terrain]")
        lat = _parse_float(parts[1], command)
        lon = _parse_float(parts[2], command)
        alt = _parse_float(parts[3], command)
        if isinstance(lat, CommandResult):
            return lat
        if isinstance(lon, CommandResult):
            return lon
        if isinstance(alt, CommandResult):
            return alt
        frame = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
        if len(parts) == 5:
            parsed_frame = _global_frame(parts[4])
            if parsed_frame is None:
                return CommandResult(False, "global_goto frame must be relative, global, or terrain")
            frame = parsed_frame
        manager.global_goto(lat, lon, alt, frame)
        _log_info("global_goto command queued lat=%.7f lon=%.7f alt=%.2f frame=%s", lat, lon, alt, frame)
        return CommandResult(True, f"global_goto queued lat={lat:.7f} lon={lon:.7f} alt={alt:.2f}")

    if command.startswith("local_pos "):
        parts = command.split()
        if len(parts) not in {4, 5, 6}:
            return CommandResult(False, "format: local_pos <x_m> <y_m> <z_m> [local|offset|body|body_offset] [yaw_rad]")
        x = _parse_float(parts[1], command)
        y = _parse_float(parts[2], command)
        z = _parse_float(parts[3], command)
        if isinstance(x, CommandResult):
            return x
        if isinstance(y, CommandResult):
            return y
        if isinstance(z, CommandResult):
            return z
        frame = mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED
        yaw = None
        if len(parts) >= 5:
            parsed_frame = _local_frame(parts[4])
            if parsed_frame is not None:
                frame = parsed_frame
            else:
                return CommandResult(False, "local_pos frame must be local, offset, body, or body_offset")
        if len(parts) == 6:
            yaw = _parse_float(parts[5], command)
            if isinstance(yaw, CommandResult):
                return yaw
        manager.local_position(x, y, z, frame, yaw=yaw)
        yaw_text = f" yaw={yaw:.2f}" if yaw is not None else ""
        _log_info("local_pos command queued x=%.2f y=%.2f z=%.2f frame=%s%s", x, y, z, frame, yaw_text)
        return CommandResult(True, f"local_pos queued x={x:.2f} y={y:.2f} z={z:.2f}{yaw_text}")

    if command.startswith("reposition "):
        parts = command.split()
        if len(parts) not in {4, 5, 6}:
            return CommandResult(False, "format: reposition <lat> <lon> <rel_alt_m> [groundspeed_mps] [yaw_deg]")
        lat = _parse_float(parts[1], command)
        lon = _parse_float(parts[2], command)
        alt = _parse_float(parts[3], command)
        if isinstance(lat, CommandResult):
            return lat
        if isinstance(lon, CommandResult):
            return lon
        if isinstance(alt, CommandResult):
            return alt
        speed = -1.0
        if len(parts) >= 5:
            parsed_speed = _parse_float(parts[4], command)
            if isinstance(parsed_speed, CommandResult):
                return parsed_speed
            speed = parsed_speed
        yaw = None
        if len(parts) == 6:
            parsed_yaw = _parse_float(parts[5], command)
            if isinstance(parsed_yaw, CommandResult):
                return parsed_yaw
            yaw = parsed_yaw
        manager.reposition(lat, lon, alt, speed, yaw)
        _log_info("reposition command queued lat=%.7f lon=%.7f alt=%.2f speed=%.2f yaw=%s", lat, lon, alt, speed, yaw)
        return CommandResult(True, f"reposition queued lat={lat:.7f} lon={lon:.7f} alt={alt:.2f}")

    if command.startswith("set_roi_location "):
        parts = command.split()
        if len(parts) != 4:
            return CommandResult(False, "format: set_roi_location <lat> <lon> <alt_m>")
        lat = _parse_float(parts[1], command)
        lon = _parse_float(parts[2], command)
        alt = _parse_float(parts[3], command)
        if isinstance(lat, CommandResult):
            return lat
        if isinstance(lon, CommandResult):
            return lon
        if isinstance(alt, CommandResult):
            return alt
        manager.set_roi_location(lat, lon, alt)
        _log_info("set_roi_location command queued lat=%.7f lon=%.7f alt=%.2f", lat, lon, alt)
        return CommandResult(True, f"set_roi_location queued lat={lat:.7f} lon={lon:.7f} alt={alt:.2f}")

    if command.startswith("roi_none"):
        parts = command.split()
        if len(parts) not in {1, 2}:
            return CommandResult(False, "format: roi_none [gimbal_device_id]")
        gimbal_device_id = 0
        if len(parts) == 2:
            try:
                gimbal_device_id = int(parts[1])
            except ValueError:
                return CommandResult(False, f"parse failed: {command}")
        manager.roi_none(gimbal_device_id)
        _log_info("roi_none command queued gimbal_device_id=%s", gimbal_device_id)
        return CommandResult(True, f"roi_none queued gimbal_device_id={gimbal_device_id}")

    if command.startswith("gimbal_manager_configure"):
        parts = command.split()
        if len(parts) not in {1, 2, 4}:
            return CommandResult(False, "format: gimbal_manager_configure [gimbal_device_id] [primary_sysid primary_compid]")
        try:
            gimbal_device_id = int(parts[1]) if len(parts) >= 2 else 0
            primary_sysid = int(parts[2]) if len(parts) == 4 else None
            primary_compid = int(parts[3]) if len(parts) == 4 else None
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        manager.gimbal_manager_configure(gimbal_device_id, primary_sysid, primary_compid)
        _log_info(
            "gimbal_manager_configure command queued gimbal_device_id=%s primary_sysid=%s primary_compid=%s",
            gimbal_device_id,
            primary_sysid,
            primary_compid,
        )
        return CommandResult(True, f"gimbal_manager_configure queued gimbal_device_id={gimbal_device_id}")

    if command.startswith("set_servo "):
        parts = command.split()
        if len(parts) != 3:
            return CommandResult(False, "format: set_servo <channel> <pwm>")
        try:
            channel = int(parts[1])
            pwm = int(parts[2])
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        manager.set_servo(channel, pwm)
        _log_info("set_servo command queued channel=%s pwm=%s", channel, pwm)
        return CommandResult(True, f"set_servo queued channel={channel} pwm={pwm}")

    if command.startswith("set_relay "):
        parts = command.split()
        if len(parts) != 3:
            return CommandResult(False, "format: set_relay <relay_id> <on|off>")
        try:
            relay_id = int(parts[1])
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        state_text = parts[2].strip().lower()
        if state_text not in {"on", "off"}:
            return CommandResult(False, "set_relay state must be on or off")
        state = state_text == "on"
        manager.set_relay(relay_id, state)
        _log_info("set_relay command queued relay_id=%s state=%s", relay_id, state)
        return CommandResult(True, f"set_relay queued relay_id={relay_id} state={state_text}")

    if command.startswith("release_payload "):
        parts = command.split()
        if len(parts) != 2:
            return CommandResult(False, "format: release_payload <payload_id>")
        try:
            payload_id = int(parts[1])
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        _log_warning("release_payload rejected payload_id=%s: payload mapping is not configured", payload_id)
        return CommandResult(False, f"release_payload rejected payload_id={payload_id}: payload mapping is not configured")

    if command.startswith("set_message_interval ") or command.startswith("message_interval "):
        parts = command.split()
        if len(parts) != 3:
            return CommandResult(False, "format: set_message_interval <MESSAGE_NAME> <rate_hz|default>")
        message_name = parts[1].strip().upper()
        rate_text = parts[2].strip().lower()
        if rate_text == "default":
            rate_hz = -1.0
        else:
            parsed_rate = _parse_float(parts[2], command)
            if isinstance(parsed_rate, CommandResult):
                return parsed_rate
            rate_hz = parsed_rate
        manager.request_message_interval(message_name, rate_hz)
        _log_info("set_message_interval command queued message=%s rate_hz=%s", message_name, rate_hz)
        return CommandResult(True, f"set_message_interval queued message={message_name} rate={'default' if rate_hz <= 0 else f'{rate_hz:.2f}'}")

    if command.startswith("body_vel "):
        parts = command.split()
        if len(parts) != 4:
            return CommandResult(False, "format: body_vel <forward_mps> <right_mps> <down_mps>")
        try:
            forward = float(parts[1])
            right = float(parts[2])
            down = float(parts[3])
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        manager.send_velocity_command(
            vx=forward,
            vy=right,
            vz=down,
            frame=mavutil.mavlink.MAV_FRAME_BODY_NED,
        )
        _log_info(
            "body_vel command queued forward=%.2f right=%.2f down=%.2f frame=BODY_NED",
            forward,
            right,
            down,
        )
        return CommandResult(True, f"body_vel queued forward={forward:.2f} right={right:.2f} down={down:.2f}")

    if command.startswith("yaw_rate "):
        parts = command.split()
        if len(parts) != 2:
            return CommandResult(False, "format: yaw_rate <rad_per_sec>")
        try:
            yaw_rate = float(parts[1])
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        manager.send_yaw_rate_command(
            yaw_rate=yaw_rate,
            frame=mavutil.mavlink.MAV_FRAME_BODY_NED,
        )
        _log_info("yaw_rate command queued yaw_rate=%.2f frame=BODY_NED", yaw_rate)
        return CommandResult(True, f"yaw_rate queued yaw_rate={yaw_rate:.2f}")

    if command == "stop":
        manager.stop_control(frame=mavutil.mavlink.MAV_FRAME_BODY_NED)
        _log_info("stop command queued frame=BODY_NED")
        return CommandResult(True, "stop queued frame=BODY_NED")

    if command.startswith("gimbal "):
        parts = command.split()
        if len(parts) not in {3, 4}:
            return CommandResult(False, "format: gimbal <pitch_deg> <yaw_deg> [roll_deg]")
        try:
            pitch = float(parts[1])
            yaw = float(parts[2])
            roll = float(parts[3]) if len(parts) == 4 else 0.0
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        manager.send_gimbal_angle(pitch=pitch, yaw=yaw, roll=roll)
        _log_info("gimbal command queued pitch=%.2f yaw=%.2f roll=%.2f", pitch, yaw, roll)
        return CommandResult(True, f"gimbal queued pitch={pitch:.2f} yaw={yaw:.2f} roll={roll:.2f}")

    if command.startswith("gimbal_rate "):
        parts = command.split()
        if len(parts) not in {3, 4}:
            return CommandResult(False, "format: gimbal_rate <pitch_rate_deg_s> <yaw_rate_deg_s> [follow|lock]")
        try:
            pitch_rate_deg_s = float(parts[1])
            yaw_rate_deg_s = float(parts[2])
        except ValueError:
            return CommandResult(False, f"parse failed: {command}")
        yaw_mode = parts[3].strip().lower() if len(parts) == 4 else "follow"
        if yaw_mode not in {"follow", "lock"}:
            return CommandResult(False, "gimbal_rate yaw mode must be follow or lock")
        manager.send_gimbal_rate(
            yaw_rate=math.radians(yaw_rate_deg_s),
            pitch_rate=math.radians(pitch_rate_deg_s),
            yaw_lock=(yaw_mode == "lock"),
        )
        _log_info(
            "gimbal_rate command queued pitch_rate=%.2f deg/s yaw_rate=%.2f deg/s yaw_mode=%s",
            pitch_rate_deg_s,
            yaw_rate_deg_s,
            yaw_mode,
        )
        return CommandResult(
            True,
            f"gimbal_rate queued pitch_rate={pitch_rate_deg_s:.2f}deg/s yaw_rate={yaw_rate_deg_s:.2f}deg/s {yaw_mode}",
        )

    _log_warning("unknown command: %s", command)
    return CommandResult(False, f"unknown command: {command}")
