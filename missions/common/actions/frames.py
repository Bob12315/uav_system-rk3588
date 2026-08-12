"""MAVLink frame IDs used by Actions without importing telemetry transport.

The numeric values are stable protocol constants: LOCAL_NED=1 and
GLOBAL_RELATIVE_ALT_INT=6. Transport code remains the sole pymavlink owner.
"""

LOCAL_NED = 1
GLOBAL_RELATIVE_ALT_INT = 6
