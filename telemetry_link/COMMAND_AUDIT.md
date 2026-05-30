# Telemetry Command Audit

对照对象：

- ArduPilot Copter Guided mode command notes
- ArduPilot gimbal/mount command notes
- MAVLink command parameter definitions

## 已修正

### `body_vel` / `yaw_rate` / `stop`

底层都使用 `SET_POSITION_TARGET_LOCAL_NED`。

ArduPilot Copter 对 Guided 运动命令要求：

- 速度目标必须提供完整 `vx/vy/vz`
- `yaw_rate` 不能单独作为唯一目标
- 要做偏航角速度控制时，应同时给速度三轴，速度可为 `0`

原实现的问题：

- `VELOCITY` 类型 mask 屏蔽了 `yaw_rate`，所以上层统一控制里的 `yaw_rate` 会被飞控忽略
- `YAW_RATE` 类型只发送 yaw_rate，不发送有效的速度三轴目标，ArduPilot Copter 下可能不生效

当前实现：

- `VELOCITY`、`YAW_RATE`、`STOP` 都发送速度三轴 + `yaw_rate`
- type mask 等效为 ArduPilot 示例里的 `1479`
- `yaw_rate` 单独命令会用 `vx=vy=vz=0` 搭配目标偏航角速度
- `stop` 会发送 `vx=vy=vz=yaw_rate=0`

## 已核对，暂不改

### `arm` / `disarm`

使用 `MAV_CMD_COMPONENT_ARM_DISARM`：

- param1 `1` = arm
- param1 `0` = disarm

### `takeoff`

使用 `MAV_CMD_NAV_TAKEOFF`，当前只填 param7 `altitude_m`。

这个用法适合 Copter Guided 起飞。更完整的版本可以补 yaw/lat/lon，但对当前终端命令不是必须。

### `land`

使用 `MAV_CMD_NAV_LAND`，所有参数填 `0`。

这会触发当前位置降落。若以后需要指定降落点，可补 lat/lon/alt。

### `mode`

使用 pymavlink 的 `mode_mapping()` + `set_mode()`。

这条依赖飞控固件返回的模式映射，适合 ArduPilot。输入拼错会被拒绝，例如日志里的 `guild` 不会被误发。

### `gimbal`

当前走 `MAV_CMD_DO_MOUNT_CONTROL`：

- param1 pitch
- param2 roll
- param3 yaw
- param7 mount mode

这符合 ArduPilot mount v1 路径。若你的云台只支持 gimbal v2，建议改成或新增 `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW` 角度模式。

### `gimbal_rate`

当前走 `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW`：

- param1/2 为 `NaN`，表示不使用角度目标
- param3 pitch rate，单位 `deg/s`
- param4 yaw rate，单位 `deg/s`
- param5 yaw follow/lock flags
- param7 gimbal device id

这符合 ArduPilot gimbal v2 速率路径。

### `request_message_interval`

使用 `MAV_CMD_SET_MESSAGE_INTERVAL`：

- param1 message id
- param2 interval us
- `rate_hz <= 0` 时发送 `-1`，表示恢复默认/停止自定义间隔

## 已补充

### `arm throttle`

兼容 MAVProxy 常用写法，等同于 `arm`。

### `condition_yaw`

格式：

```text
condition_yaw <yaw_deg> [speed_deg_s] [cw|ccw|shortest] [absolute|relative]
```

使用 `MAV_CMD_CONDITION_YAW`。

### `change_speed`

格式：

```text
change_speed <speed_mps> [ground|air|climb|descent]
```

使用 `MAV_CMD_DO_CHANGE_SPEED`。

### `set_home`

格式：

```text
set_home current
set_home <lat> <lon> <alt_m>
```

使用 `MAV_CMD_DO_SET_HOME`。

### `global_goto`

格式：

```text
global_goto <lat> <lon> <alt_m> [relative|global|terrain]
```

使用 `SET_POSITION_TARGET_GLOBAL_INT` 的位置目标。默认 `relative`。

### `local_pos`

格式：

```text
local_pos <x_m> <y_m> <z_m> [local|offset|body|body_offset]
```

使用 `SET_POSITION_TARGET_LOCAL_NED` 的位置目标。默认 `body_offset`。

### `reposition`

格式：

```text
reposition <lat> <lon> <rel_alt_m> [groundspeed_mps] [yaw_deg]
```

使用 `MAV_CMD_DO_REPOSITION` + `COMMAND_INT`。

### `set_roi_location`

格式：

```text
set_roi_location <lat> <lon> <alt_m>
```

使用 `MAV_CMD_DO_SET_ROI_LOCATION` + `COMMAND_INT`。

### `roi_none`

格式：

```text
roi_none [gimbal_device_id]
```

使用 `MAV_CMD_DO_SET_ROI_NONE` + `COMMAND_INT`。

### `gimbal_manager_configure`

格式：

```text
gimbal_manager_configure [gimbal_device_id] [primary_sysid primary_compid]
```

使用 `MAV_CMD_DO_GIMBAL_MANAGER_CONFIGURE`。

不传 `primary_sysid/primary_compid` 时，发送层会使用当前 MAVLink 连接的源 system/component id。

### `set_message_interval`

格式：

```text
set_message_interval <MESSAGE_NAME> <rate_hz|default>
message_interval <MESSAGE_NAME> <rate_hz|default>
```

使用 `MAV_CMD_SET_MESSAGE_INTERVAL`。`default` 会发送 `rate_hz=-1`。

### `set_servo`

格式：

```text
set_servo <channel> <pwm>
```

使用 `MAV_CMD_DO_SET_SERVO`：

- param1 servo channel
- param2 pwm

### `set_relay`

格式：

```text
set_relay <relay_id> <on|off>
```

使用 `MAV_CMD_DO_SET_RELAY`：

- param1 relay number
- param2 `0` / `1`

### `release_payload`

格式：

```text
release_payload <payload_id>
```

本阶段先安全拒绝未配置载荷映射，不把比赛专用映射写进底层。后续需要通过配置声明 `payload_id -> servo/relay action` 后再启用。
