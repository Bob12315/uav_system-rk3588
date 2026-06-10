# Coordinate Frames

> **Status:** T2 document — norm, not implementation change.

All MAVLink coordinate frames used by this project are re-exported from
`telemetry_link/frames.py`.  Never hardcode integer frame values in app or
mission code.

```python
from telemetry_link.frames import LOCAL_NED, BODY_NED, GLOBAL_RELATIVE_ALT_INT, GLOBAL
```

---

## 1. LOCAL_NED (`MAV_FRAME_LOCAL_NED`)

Local North-East-Down frame, origin at vehicle home position.

| Axis | Label | Direction | Unit |
|---|---|---|---|
| X | `x_north_m` | North | metres |
| Y | `y_east_m`  | East  | metres |
| Z | `z_down_m`   | Down  | metres |

### Altitude conversion

App-layer altitude is typically **positive up** (`altitude_m`). Convert before
passing to `goto_local_ned`:

```
z_down_m = -altitude_m
```

### Example

```python
# Fly to (10 m North, 5 m East) at 3 m altitude, yaw 0.5 rad.
manager.goto_local_ned(
    x_north_m=10.0,
    y_east_m=5.0,
    z_down_m=-3.0,      # 3 m up
    yaw_rad=0.5,
    priority=4,
)
```

### Usage

- `goto_local_ned(x_north_m, y_east_m, z_down_m, ...)` — semantic wrapper
- `local_position(x, y, z, frame=LOCAL_NED, ...)` — legacy raw form

---

## 2. BODY_NED (`MAV_FRAME_BODY_NED`)

Body-fixed North-East-Down frame, origin at the vehicle.

| Axis | Label | Description | Unit |
|---|---|---|---|
| X | `vx_forward_mps` | Forward velocity (nose direction) | m/s |
| Y | `vy_right_mps`   | Right velocity (starboard)       | m/s |
| Z | `vz_down_mps`     | Down velocity                    | m/s |

### Sign convention

| Value | Meaning |
|---|---|
| `vx_forward_mps > 0` | Drone moves **forward** |
| `vx_forward_mps < 0` | Drone moves **backward** |
| `vy_right_mps > 0`   | Drone moves to the **right** |
| `vy_right_mps < 0`   | Drone moves to the **left** |
| `vz_down_mps > 0`    | Drone moves **down** |
| `vz_down_mps < 0`    | Drone moves **up** |

### Example

```python
# Forward 0.2 m/s, slight left, no vertical.
manager.send_body_velocity(
    vx_forward_mps=0.2,
    vy_right_mps=-0.1,
    vz_down_mps=0.0,
)
```

### Usage

- `send_body_velocity(vx_forward_mps, vy_right_mps, vz_down_mps)` — semantic wrapper
- `send_velocity_command(vx, vy, vz, frame=BODY_NED)` — legacy raw form

---

## 3. GLOBAL_RELATIVE_ALT_INT (`MAV_FRAME_GLOBAL_RELATIVE_ALT_INT`)

Global position with altitude relative to home.

Used by `global_goto()` and `reposition()`.  Not part of the Action-first
local-frame path, but available for GPS-based debugging and special missions.

---

## 4. GLOBAL (`MAV_FRAME_GLOBAL`)

Global position with altitude relative to mean sea level (MSL).

Used by `roi_none()`.  Rare in typical Action code.

---

## Yaw

Vehicle yaw uses **radians** in the local/body API.  
Yaw strategy (`yaw_mode = "arm_heading"`, `"fixed"`, `"hold"`) is an
**Action-layer policy** — `telemetry_link` only transparently forwards the
`yaw` parameter to the appropriate MAVLink command.

| Interface | Yaw unit | Notes |
|---|---|---|
| `goto_local_ned(yaw_rad=…)` | radians | |
| `local_position(yaw=…)` | radians | |
| `condition_yaw(yaw_deg=…)` | **degrees** | Legacy interface |
| `set_servo_output_pwm` | N/A | No yaw |

---

## Recommended conventions for future Actions

*Waypoint actions:* Accept `altitude_m` (positive up) as user input.
Convert to `z_down_m = -altitude_m` internally before calling
`goto_local_ned`.

*Vision-based velocity actions:* Accept `vx_body_mps` / `vy_body_mps` /
`vz_body_mps` representing BODY_NED velocity.  Pass directly to
`send_body_velocity`.

*Drop actions:* Always go through `set_servo_output_pwm(servo_output, pwm)`.
Never call `release_payload()` or send raw pymavlink commands.

---

## Anti-patterns

| Don't | Instead use |
|---|---|
| `frame=1` (magic number) | `from telemetry_link.frames import LOCAL_NED` |
| `frame=8` (magic number) | `from telemetry_link.frames import BODY_NED` |
| `z=altitude_m` (sign error) | `z_down_m = -altitude_m` |
| `release_payload()` | `set_servo_output_pwm()` |
| Direct `pymavlink` call | `LinkManager` public method |
