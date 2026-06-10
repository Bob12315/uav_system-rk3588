"""Canonical MAVLink frame constants used across telemetry_link.

Re-exporting from pymavlink so that callers never need to import
mavutil.mavlink directly for frame selection.
"""

from __future__ import annotations

from pymavlink import mavutil

LOCAL_NED = mavutil.mavlink.MAV_FRAME_LOCAL_NED
BODY_NED = mavutil.mavlink.MAV_FRAME_BODY_NED
GLOBAL_RELATIVE_ALT_INT = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
GLOBAL = mavutil.mavlink.MAV_FRAME_GLOBAL
