# UAV UI

`uav_ui/` 是无人机项目的共享终端 UI 模块。它不直接管理 MAVLink 连接，也不直接运行控制器，只负责把已有运行时对象显示出来，并把用户输入的命令分发到对应模块。

当前主要入口：

- [terminal_ui.py](terminal_ui.py)：curses 终端界面
- [completion_catalog.py](completion_catalog.py)：终端和 Web UI 共用的命令补全目录
- [ui_commands.py](ui_commands.py)：UI 层命令分发
- [control_switches.py](control_switches.py)：app controller 运行时开关
- [yolo_command_client.py](yolo_command_client.py)：向 `yolo_app` 发送目标切换 UDP 命令

## 启动方式

### 跟随 app 启动

当 [config/app.yaml](../config/app.yaml) 中：

```yaml
ui:
  terminal_enabled: true
```

运行：

```bash
python -m app.main
```

会启动 app 总控循环，同时打开终端 UI。app 循环在后台线程运行，UI 在主线程接管终端。

### 跟随 telemetry_link 启动

也可以只启动 telemetry link UI：

```bash
python -m telemetry_link.main
```

此模式只显示 telemetry 状态和 MAVLink 手动命令，不显示 control 输出命令，也不支持 controller 运行时开关。

## 界面区域

当前 UI 分为三块：

- `Latest telemetry`：显示最新无人机状态、姿态、速度、位置、电池、云台状态和链路状态
- `Manual commands`：显示手动输入命令的执行结果
- `Mission control`：app 启动 UI 时显示当前 mission、stage controller、发送开关和 shaped command

底部输入框可以直接输入命令，按 Enter 发送。

常用按键：

- `Enter`：发送当前命令
- `Tab`：自动补全命令；多个候选时连续按 `Tab` 循环切换
- `Up / Down`：浏览命令历史
- `Esc` 或 `Ctrl-C`：退出 UI
- `quit` 或 `exit`：退出 UI

## 手动飞控命令

这些命令会走 `telemetry_link.command_dispatcher`，最终通过 `LinkManager` 进入 MAVLink 发送链路：

```text
arm
disarm
land
stop
mode GUIDED
takeoff 5
body_vel 5 0 0
yaw_rate 0.2
gimbal -20 0
gimbal_rate 0 20
switch_source real
switch_source sitl
```

更多格式见 [telemetry_link/command_dispatcher.py](../telemetry_link/command_dispatcher.py)。

## 目标切换命令

app 启动 UI 时支持：

```text
target next
target prev
target lock 7
target unlock
```

这些命令会通过 UDP 发给 `yolo_app.command_receiver`。

默认读取 [config/yolo.yaml](../config/yolo.yaml) 中：

```yaml
command_enabled: true
command_ip: "0.0.0.0"
command_port: 5006
```

如果 `command_ip` 是 `0.0.0.0`，UI 会自动改发到 `127.0.0.1`。

也可以启动 app 时指定 yolo 配置：

```bash
python -m app.main --yolo-config /path/to/config/yolo.yaml
```

发送 JSON 格式：

```json
{"action": "switch_next"}
{"action": "switch_prev"}
{"action": "unlock_target"}
{"action": "lock_target", "track_id": 7}
```

## Controller 运行时开关

app 启动 UI 时支持运行时开关：

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

这些命令只影响当前运行中的 app，不会修改 [config/app.yaml](../config/app.yaml)。

初始值来自：

```yaml
runtime:
  enable_gimbal_controller: true
  enable_body_controller: true
  enable_approach_controller: true
```

UI 的 `Mission control` 第一行会显示当前状态：

```text
Controllers G=ON B=ON A=OFF SEND=ON
```

## Control 发送开关

app 启动 UI 时也支持运行时开关是否真的下发 control 命令：

```text
control send on
control send off
control send toggle
```

这些命令只影响当前运行中的 app，不会修改配置文件。

## Stage Override

app 启动 UI 时支持临时强制当前 mission 的 stage controller：

```text
stage mode APPROACH_TRACK
stage mode OVERHEAD_HOLD
stage auto
```

`stage auto` 会取消强制 stage override，恢复 mission 自动选择 stage controller。

注意 `mode GUIDED` 仍然是飞控模式命令；`stage mode ...` 才是 app 内部 stage controller override。

## Mission 切换

app 启动 UI 时支持运行中切换当前 mission：

```text
mission list
mission current
mission switch visual_tracking
mission switch rescue_competition
mission start
mission reset
```

`mission switch ...` 会重建当前 mission，恢复 `stage auto`，并重置 stage controller 和 command shaper。为避免切换瞬间沿用旧任务的连续控制，切换和重置都会把 `SEND` 置为 `OFF`，需要确认安全后再输入：

`mission start` 会请求当前 mission 开始执行。对 `rescue_competition` 来说，它会从
`PREPARE` 等待本地位置有效，进入 `ARM` 请求自动解锁，再进入 `TAKEOFF`。建议顺序：

```text
mode GUIDED
control send on
mission start
```

## Stage 参数重载

app 启动 UI 时支持在运行中重载
`missions/<mission_name>/config.yaml`：

```text
pid reload
stage reload
stage config reload
```

这些命令会重新读取 `input_adapter`、健康监控阈值、`approach_track`、
`overhead_hold` 和 `shaper` 配置，并更新当前运行中的 controller。适合调
`kp_*`、`ki_*`、`kd_*`、死区、限幅和 slew rate 等参数。

重载只影响当前 app 进程，不会写回 YAML。重载成功时会重置 stage controller 内部状态，包括积分、微分历史和 command shaper 状态。

## Mission Control

初始值来自 [config/app.yaml](../config/app.yaml)：

```yaml
executor:
  send_commands: false
```

当 `SEND=OFF` 时，app 仍然会正常计算内部 shaped command，但不会调用 executor 下发，也会清空 `telemetry_link` 中保留的连续 control/gimbal_rate 队列。UI 的 `Mission control` 只显示一条静态 `DRY continuous command sending disabled` 提示，不再刷新命令流水。

app 启动 UI 时，`Mission control` 会显示最近的 shaped command：

```text
12:34:56 vx=0.100 vy=0.000 yaw=0.000 gimbal=(0.120,-0.050) en=G1 B0 A1 active=True valid=True
```

字段含义：

- `vx / vy / yaw`：机体速度与偏航角速度命令
- `gimbal=(yaw_rate,pitch_rate)`：云台角速度命令
- `en=G/B/A`：gimbal/body/approach 三路 controller 是否放行
- `active`：当前 shaped command 是否活跃
- `valid`：当前 shaped command 是否有效

## 设计边界

`uav_ui` 只做显示和命令分发：

- 不创建 MAVLink 连接
- 不直接访问飞控串口或 UDP/TCP 链路
- 不保存 controller 开关到配置文件
- 不解析 YOLO 画面或 track 列表

具体执行仍由对应模块完成：

- MAVLink 命令由 `telemetry_link` 执行
- 目标切换由 `yolo_app` 执行
- controller 开关由 `app` 总控循环读取
