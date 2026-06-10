# Telemetry Link Public API Reference

> **Status:** T2 document — maps the current code, no behavioural change.

## Principle

`telemetry_link` is the **flight-controller egress layer**.  
App-layer code (actions, missions, web UI) must **not** call pymavlink directly.  
All vehicle commands flow through `LinkManager`.

`telemetry_link` carries **no mission policy** — no waypoint strategy, no
search pattern, no payload-drop sequencing.  Those live in the app layer.

---

## Public API tiers

### 1. Core mission interfaces — preferred for Action/Mission

These are the supported, documented entry-points for the Action-first main path.

| Method | Semantics | Notes |
|---|---|---|
| `set_mode(mode, priority=5)` | Change flight mode | |
| `arm(priority=1)` | Arm motors | |
| `disarm(priority=1)` | Disarm motors | |
| `takeoff(altitude_m, priority=2)` | Take off to altitude | |
| `land(priority=2)` | Land | |
| **Semantic wrappers (preferred)** | | |
| `goto_local_ned(x_north_m, y_east_m, z_down_m, yaw_rad=None, priority=4)` | Position target, `LOCAL_NED` frame | Use over `local_position` |
| `send_body_velocity(vx_forward_mps, vy_right_mps, vz_down_mps)` | Velocity, `BODY_NED` frame | Use over raw `send_velocity_command` |
| `set_servo_output_pwm(servo_output, pwm, priority=3)` | SERVO output PWM | Maps to `MAV_CMD_DO_SET_SERVO` |
| **Legacy (kept for compat / tests)** | | |
| `local_position(x, y, z, frame, yaw=None, priority=4)` | Raw position | Prefer `goto_local_ned` |
| `send_velocity_command(vx, vy, vz, frame=1)` | Raw velocity | Prefer `send_body_velocity` |
| `set_servo(channel, pwm, priority=3)` | Raw servo | Prefer `set_servo_output_pwm` |
| **Gimbal** | | |
| `send_gimbal_angle(pitch, yaw, roll=0.0, mount_mode=None, priority=5)` | Absolute angle | pitch/yaw in **degrees** |
| `send_gimbal_rate(yaw_rate, pitch_rate, yaw_lock=False)` | Rate control | |
| **Stop** | | |
| `stop_control(frame=1)` | All-zero velocity stop | `ControlType.STOP` |

### 2. Advanced / debug interfaces

Use these for debugging, manual control, or special-mission needs. Not part of
the Action-first main flow.

| Method | Semantics |
|---|---|
| `global_goto(lat, lon, alt, priority=4)` | Global-position waypoint |
| `reposition(lat, lon, alt, ground_speed_mps, yaw_deg, priority=4)` | `MAV_CMD_DO_REPOSITION` |
| `condition_yaw(yaw_deg, direction, relative, priority=4)` | Yaw condition (`MAV_CMD_CONDITION_YAW`) |
| `change_speed(speed_mps, speed_type, priority=4)` | Speed override |
| `set_home_current(priority=4)` | Set home to current position |
| `set_home_location(lat, lon, alt, priority=4)` | Set home to location |
| `set_roi_location(lat, lon, alt, priority=4)` | Point camera at location |
| `roi_none(gimbal_device_id, priority=4)` | Clear ROI |
| `gimbal_manager_configure(gimbal_device_id, …, priority=4)` | Mount configure |
| `request_message_interval(message_name, rate_hz, priority=6)` | Telemetry rate |
| `set_relay(relay_id, state, priority=3)` | Relay control |
| `send_yaw_rate_command(yaw_rate, frame=1)` | Yaw-only rate |

### 3. Deprecated / restricted interfaces

**Do not call these from Action or Mission code.**  
They exist for internal plumbing (`CommandSender`) or console-based debugging.

| Method | Restriction reason |
|---|---|
| `release_payload(payload_id, priority=3)` | **Not the payload-drop path.** Raises `NotImplementedError` — use `set_servo_output_pwm`. |
| `submit_action_command(command)` | Raw queue injection — bypasses all wrappers. |
| `submit_control_command(command)` | Raw queue injection — bypasses all wrappers. |

---

## Payload release canonical path

### Correct (main path)

```
PayloadReleaseAction
  -> set_servo action  (action_type="set_servo")
  -> ActionDispatcher._dispatch_set_servo()
  -> LinkManager.set_servo_output_pwm() / set_servo()
  -> ActionCommand(action_type=ActionType.SET_SERVO)
  -> CommandSender._send_set_servo()
  -> MAV_CMD_DO_SET_SERVO
```

### Forbidden

| Path | Why |
|---|---|
| `release_payload()` | Not the designated path; emits `ActionType.RELEASE_PAYLOAD` with zero retries. |
| RC override | Not supported in this architecture. |
| Direct `pymavlink` call | Bypasses `LinkManager` queue, safety gate, and audit. |

---

## Naming conventions

| Term | Meaning |
|---|---|
| `servo_output` | Flight-controller **SERVO output** number (1‒16), **not** an RC input channel. |
| `channel` (in `set_servo`) | Same as `servo_output` — legacy parameter name. |
| `pwm` | PWM pulse width in **microseconds** (µs), typically 500‒2500. |
| `yaw_rad` | Yaw angle in **radians**. |
| `pitch` / `yaw` in gimbal APIs | **Degrees** — per the current interface contract. |
| `altitude_m` | Altitude in metres, positive **up**. |
| `z_down_m` | Z in LOCAL_NED/BODY_NED, positive **down**. |

---

## Frame constants

Always import from `telemetry_link.frames` — never hardcode integers.

```python
from telemetry_link.frames import LOCAL_NED, BODY_NED
```

See [`coordinate_frames.md`](coordinate_frames.md) for the full specification.
