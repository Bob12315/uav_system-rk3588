# UI Commands

本文档列出终端 UI 输入框中可以输入的命令。命令来自：

- `uav_ui/terminal_ui.py`：UI 退出和输入行为
- `uav_ui/ui_commands.py`：app/control UI 扩展命令
- `telemetry_link/command_dispatcher.py`：MAVLink 手动命令

部分命令只在 app/control 启动 UI 时可用；只启动 `telemetry_link` UI 时，通常只支持 MAVLink 手动命令。

## UI 通用命令

输入框支持 `Tab` 自动补全。单个候选会直接补全，多个候选可以连续按 `Tab` 循环切换。

```text
quit
exit
```

`quit` 和 `exit` 会退出终端 UI。

## 目标切换命令

仅 app/control UI 支持。命令会通过 UDP 发给 `yolo_app`。

```text
target next
target prev
target previous
target lock <track_id>
target unlock
```

示例：

```text
target lock 7
target unlock
```

## Controller 运行时开关

仅 app/control UI 支持。`controller` 也可以写成 `controllers`。

格式：

```text
controller <gimbal|body|approach|all> <on|off|toggle>
controllers <gimbal|body|approach|all> <on|off|toggle>
```

支持的动作别名：

```text
on      enable enabled 1 true
off     disable disabled 0 false
toggle  tog
```

常用命令：

```text
controller gimbal on
controller gimbal off
controller gimbal toggle
controller body on
controller body off
controller body toggle
controller approach on
controller approach off
controller approach toggle
controller all on
controller all off
controller all toggle
```

## Control 发送开关

仅 app/control UI 支持。控制是否真的下发连续控制命令。

格式：

```text
control send <on|off|toggle>
control send_commands <on|off|toggle>
control commands <on|off|toggle>
```

支持的动作别名：

```text
on      enable enabled 1 true
off     disable disabled 0 false
toggle  tog
```

常用命令：

```text
control send on
control send off
control send toggle
```

## Stage Override

仅 app/control UI 支持。用于临时强制当前 mission 的 stage controller，主要用于调试控制模块，不是切换 mission。

`task` 仍可作为兼容别名，但建议新命令统一用 `stage`。

格式：

```text
stage <STAGE_CONTROLLER>
stage mode <STAGE_CONTROLLER>
stage auto
stage clear
```

当前 app stage controller 支持：

```text
APPROACH_TRACK
OVERHEAD_HOLD
CORRIDOR_FOLLOW
IDLE
auto
clear
```

示例：

```text
stage mode APPROACH_TRACK
stage mode OVERHEAD_HOLD
stage mode CORRIDOR_FOLLOW
stage mode IDLE
stage auto
```

`auto` 和 `clear` 会取消强制 stage override，恢复 mission 自动选择 stage controller。

## Mission 切换

仅 app/control UI 支持。用于运行中切换当前 mission。

```text
mission list
mission current
mission status
mission switch <MISSION_NAME>
mission select <MISSION_NAME>
mission use <MISSION_NAME>
mission start
mission reset
```

当前支持：

```text
visual_tracking
rescue_competition
```

示例：

```text
mission list
mission switch visual_tracking
mission switch rescue_competition
mission start
mission reset
```

切换或重置 mission 时会清掉当前连续控制队列、重置 stage controller/shaper 状态，并把 `SEND` 置为 `OFF`。确认状态安全后再输入：

`mission start` 会请求当前 mission 开始执行。对 `rescue_competition` 来说，它会从 `PREPARE` 等待本地位置有效后进入 `TAKEOFF`。

```text
control send on
```

## Stage 参数重载

仅 app/control UI 支持。用于运行中重载 [missions/<mission_name>/config.yaml](missions/<mission_name>/config.yaml)。

```text
pid reload
stage reload
stage config reload
stage controllers reload
```

## MAVLink 手动命令

这些命令会走 `telemetry_link.command_dispatcher`，最终进入 `LinkManager` 的 MAVLink 发送链路。

### 链路和飞控模式

```text
switch_source <source_name>
mode <MODE_NAME>
```

示例：

```text
switch_source real
switch_source sitl
mode GUIDED
mode LOITER
mode RTL
```

### 解锁、起飞、降落

```text
arm
arm throttle
disarm
takeoff <altitude_m>
land
```

示例：

```text
arm
takeoff 5
land
disarm
```

### 偏航和速度

```text
condition_yaw <yaw_deg> [speed_deg_s] [cw|ccw|shortest] [absolute|relative]
change_speed <speed_mps> [ground|air|climb|descent]
```

示例：

```text
condition_yaw 90
condition_yaw 45 20 shortest relative
change_speed 3 ground
change_speed 1.5 air
```

### Home 和位置命令

```text
set_home current
set_home <lat> <lon> <alt_m>
global_goto <lat> <lon> <alt_m> [relative|global|terrain]
local_pos <x_m> <y_m> <z_m> [local|offset|body|body_offset]
reposition <lat> <lon> <rel_alt_m> [groundspeed_mps] [yaw_deg]
```

示例：

```text
set_home current
set_home -35.363262 149.165237 584
global_goto -35.363262 149.165237 20 relative
local_pos 5 0 -2 body
reposition -35.363262 149.165237 20 3 90
```

### ROI 和云台管理

```text
set_roi_location <lat> <lon> <alt_m>
roi_none [gimbal_device_id]
gimbal_manager_configure
gimbal_manager_configure [gimbal_device_id]
gimbal_manager_configure [gimbal_device_id] [primary_sysid] [primary_compid]
```

示例：

```text
set_roi_location -35.363262 149.165237 584
roi_none
roi_none 1
gimbal_manager_configure
gimbal_manager_configure 1
gimbal_manager_configure 1 1 1
```

### MAVLink 消息频率

`message_interval` 是 `set_message_interval` 的别名。

```text
set_message_interval <MESSAGE_NAME> <rate_hz|default>
message_interval <MESSAGE_NAME> <rate_hz|default>
```

示例：

```text
set_message_interval ATTITUDE 10
message_interval GLOBAL_POSITION_INT 5
set_message_interval ATTITUDE default
```

### 连续机体控制

```text
body_vel <forward_mps> <right_mps> <down_mps>
yaw_rate <rad_per_sec>
stop
```

示例：

```text
body_vel 1 0 0
body_vel 0 1 0
yaw_rate 0.2
stop
```

### 云台角度和角速度

```text
gimbal <pitch_deg> <yaw_deg> [roll_deg]
gimbal_rate <pitch_rate_deg_s> <yaw_rate_deg_s> [follow|lock]
```

示例：

```text
gimbal -20 0
gimbal -20 30 0
gimbal_rate 0 20
gimbal_rate 0 20 lock
```

## 注意

在 app/control UI 中，输入手动 MAVLink 命令后，系统会自动关闭 control 连续命令发送，避免自动控制和人工输入同时争用飞控命令。
