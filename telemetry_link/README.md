# telemetry_link

`telemetry_link/` 是 MAVLink 数传通讯适配层。它负责连接飞控、接收状态、缓存最新 telemetry、管理命令队列，并把上层提交的控制命令或动作命令发送到当前 active source。

它可以被 `app/` 嵌入使用，也可以通过 `python -m telemetry_link.main` 独立运行，用于单独调试 SITL、真机链路、云台反馈和 MAVLink 命令。

## 职责

- 建立 MAVLink2 连接。
- 接收并解析飞控状态。
- 接收并解析云台反馈。
- 维护 `DroneState`、`GimbalState`、`LinkStatus`。
- 管理连续控制命令、云台速率命令和一次性 action 命令。
- 对连续控制命令限频。
- 在断线、超时或重连时停止发送连续命令。
- 支持 `real`、`sitl`、`dual` 数据源。

## 不负责

- 不读取 YOLO UDP。
- 不做感知融合。
- 不计算目标跟踪控制律。
- 不决定 `APPROACH_TRACK`、`OVERHEAD_HOLD` 等任务阶段。
- 不直接依赖 mission stage controller 或 `app/`。
- 不是 ROS2 节点，不使用 `rclpy`，不发布或订阅 ROS2 topic。

## 数据流

```text
Serial / UDP / TCP / ETH
  -> MavlinkClient
  -> TelemetryReceiver
  -> StateCache
  -> LinkManager.get_latest_*()
```

```text
FlightCommandExecutor / UI / stdin
  -> LinkManager
  -> CommandQueue
  -> CommandSender
  -> MAVLink
```

在 `dual` 模式下，`real` 和 `sitl` 各自维护独立连接、接收线程、发送线程、状态缓存和命令队列。对外状态和控制发送只应面向当前 `active_source`。

## 主要文件

- `main.py`：独立运行入口。
- `../config/telemetry.yaml`：app 和独立 telemetry 服务共用的默认配置。
- `config.py`：加载根目录 telemetry 配置并处理命令行覆盖。
- `models.py`：公开 dataclass 和枚举。
- `link_manager.py`：对外统一入口和 source 生命周期管理。
- `mavlink_client.py`：底层 `pymavlink` 连接封装。
- `telemetry_receiver.py`：接收线程，解析 MAVLink 状态消息。
- `telemetry_parser.py`：MAVLink 字段解析和单位转换工具。
- `state_cache.py`：线程安全状态缓存和新鲜度校验。
- `command_queue.py`：连续命令和 action 命令队列。
- `command_sender.py`：发送线程，统一发 MAVLink 控制和动作命令。
- `command_dispatcher.py`：文本命令到 `LinkManager` 方法的分发。
- `rate_controller.py`：发送限频器。
- `state_publisher.py`：本地 UDP 状态发布。
- `COMMAND_AUDIT.md`：MAVLink 命令审计和命令参数说明。

## 公开接口

上层模块只应通过 `LinkManager` 使用 telemetry：

```python
from telemetry_link.link_manager import LinkManager

manager = LinkManager(cfg)
manager.start_background()

drone = manager.get_latest_drone_state()
gimbal = manager.get_latest_gimbal_state()
link = manager.get_link_status()
```

连续机体控制走：

```python
manager.submit_control_command(command)
```

云台速率控制走：

```python
manager.send_gimbal_rate(yaw_rate=0.0, pitch_rate=0.0)
```

一次性动作命令走：

```python
manager.arm()
manager.disarm()
manager.set_mode("GUIDED")
manager.takeoff(altitude_m=5.0)
manager.land()
```

完整接口契约见 [../docs/interfaces.md](../docs/interfaces.md)。

## 状态模型

- `DroneState`：飞控连接、模式、解锁、姿态、速度、高度、电池、GPS 和数据新鲜度。
- `GimbalState`：云台 yaw、pitch、roll、反馈来源和有效性。
- `LinkStatus`：连接状态、重连状态、最近收发时间和目标 system/component。

状态字段单位和语义以 [../docs/interfaces.md](../docs/interfaces.md) 为准。

## 命令模型

- `ControlCommand`：连续机体控制命令。
- `GimbalRateCommand`：连续云台角速度命令，输入单位为 `rad/s`。
- `ActionCommand`：一次性动作命令，例如 arm、mode、takeoff、land、goto、ROI、message interval。

当前 MAVLink 发送细节：

- body velocity / yaw rate / stop 使用 `SET_POSITION_TARGET_LOCAL_NED`。
- gimbal rate 使用 `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW`。
- action 命令使用 `COMMAND_LONG`、`COMMAND_INT` 或对应 setpoint message。

命令参数审计见 [COMMAND_AUDIT.md](COMMAND_AUDIT.md)。

## 独立运行

查看参数：

```bash
cd ~/uav_project/uav_system-rk3588
python -m telemetry_link.main --help
```

使用根目录 `config/telemetry.yaml` 启动：

```bash
python -m telemetry_link.main
```

覆盖为 SITL TCP：

```bash
python -m telemetry_link.main \
  --data-source sitl \
  --active-source sitl \
  --sitl-connection-type tcp \
  --sitl-tcp-host 127.0.0.1 \
  --sitl-tcp-port 5762
```

覆盖为真机串口：

```bash
python -m telemetry_link.main \
  --data-source real \
  --active-source real \
  --real-connection-type serial \
  --real-serial-port /dev/ttyUSB0 \
  --real-baudrate 57600
```

如果 `ui_enabled: true` 或传入 `--ui`，会打开 curses 终端 UI；否则从 stdin 接收文本命令。

## 配置

telemetry 独立运行和完整 app 运行共用配置入口：

```text
config/telemetry.yaml
```

独立入口仍然可以脱离 `app/` 调链路、调云台和验证 MAVLink 命令。需要临时覆盖时，使用 `--config` 指定其他文件，或使用命令行参数覆盖单项配置。

常用配置项：

- `data_source`：`real`、`sitl` 或 `dual`。
- `active_source`：当前对外暴露状态和接收控制命令的 source。
- `control_send_rate_hz`：连续控制命令最大发送频率。
- `heartbeat_timeout_sec`：heartbeat 超时时间。
- `rx_timeout_sec`：任意消息接收超时时间。
- `request_message_intervals`：启动后是否请求默认消息频率。
- `message_interval_hz`：默认 MAVLink 消息频率请求。
- `state_udp_enabled`：是否通过 UDP 发布最新状态。
- `ui_enabled`：是否默认打开终端 UI。

## 文本命令

独立运行且未打开 UI 时，可以从 stdin 输入命令：

```text
arm
disarm
mode GUIDED
takeoff 5
land
stop
body_vel 1 0 0
yaw_rate 0.2
gimbal -20 0
gimbal_rate 0 20
switch_source real
switch_source sitl
```

命令格式由 `command_dispatcher.py` 解析，所有命令最终都通过 `LinkManager` 进入发送链路。

## 安全规则

- 连续控制命令只保留最新一条，不排长队。
- 断线或重连时必须清空连续 body/gimbal rate 命令。
- `TelemetryReceiver` 只接收和解析状态，不发送命令。
- `CommandSender` 只发送队列中的命令，不计算控制律。
- 云台角度状态必须来自 MAVLink 实际反馈，不能用发送过的命令值代替。
- `HEARTBEAT` 只接受 autopilot 来源，避免把 GCS heartbeat 当成飞控状态。
- `relative_altitude` 不由 `VFR_HUD.alt` 覆盖，避免相对高度语义跳变。

## 禁止事项

- 不在 `telemetry_link/` 中实现 YOLO、fusion 或 mission stage 控制公式。
- 不让外部模块直接访问 `pymavlink` master 对象。
- 不让 stage controller 直接调用 `LinkManager`。
- 不绕过 `CommandShaper` 和 `FlightCommandExecutor` 发送自动控制命令。
- 不默认打开真实控制发送；`send_commands` 的安全开关属于 app executor 层。
- 不把 `__pycache__`、日志或本地调试产物作为功能变更提交。
