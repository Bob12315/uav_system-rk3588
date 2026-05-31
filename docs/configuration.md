# 配置说明

配置分成两层：`config/` 只放系统配置；每个 mission 的任务参数和阶段参数放在自己的 `missions/<mission_name>/config.yaml`。

## config/app.yaml

进程运行、服务开关、mission 选择和 executor 安全出口。

```yaml
runtime:
  yolo_udp_ip: "0.0.0.0"
  yolo_udp_port: 5005
  loop_hz: 20.0
  perception_timeout_sec: 1.0
  print_rate_hz: 2.0
  require_gimbal_feedback: true
  run_seconds: null
  log_level: INFO

services:
  connect_telemetry: false
  start_yolo_udp: true

ui:
  web_enabled: true
  terminal_enabled: false
  web_host: "0.0.0.0"
  web_port: 8080
  audit_log_path: "runtime/logs/web_ui/audit.jsonl"

mission:
  name: visual_tracking

executor:
  send_commands: false
```

- `connect_telemetry`：默认 false；命令行 `--connect-telemetry` 可打开。
- `ui.web_enabled`：是否随 app 启动网页控制台。
- `ui.terminal_enabled`：是否启动 curses UI；命令行 `--ui` 仍可临时打开。
- `start_yolo_udp`：是否监听 YOLO UDP。
- `send_commands`：默认必须为 false；实发时必须显式打开。
- `run_seconds`：自动退出秒数，适合 smoke test。
- `mission.name`：当前运行的 mission 名称，默认 `visual_tracking`。

网页上的外部进程重启按钮由 service manager 命令驱动，建议使用用户级 `systemd`：

```yaml
services_control:
  restart_app_command: ["systemctl", "--user", "restart", "uav-app.service"]
  restart_yolo_command: ["systemctl", "--user", "restart", "uav-yolo.service"]
```

## missions/visual_tracking/config.yaml

视觉跟踪 mission 的模式切换条件、正常恢复策略，以及该 mission 使用的阶段控制参数。

```yaml
initial_mode: "APPROACH_TRACK"
auto_switch_enabled: true

freshness:
  max_vision_age_s: 0.3
  max_drone_age_s: 0.3
  max_gimbal_age_s: 0.3

transitions:
  approach_track_to_overhead_hold:
    target_size_thresh: 10.0
    gimbal_pitch_rad: -1.5707963267948966
    gimbal_pitch_tol_rad: 0.20
    gimbal_yaw_tol_rad: 0.15
    hold_s: 0.5
  overhead_hold_to_approach_track:
    target_size_drop: 0.06

recovery:
  lost_target:
    recenter_gimbal_enabled: true
    recenter_after_s: 10.0
    recenter_pitch_deg: 0.0
    recenter_yaw_deg: 0.0
```

- `initial_mode`：任务状态机启动后的默认模式。
- `auto_switch_enabled`：是否允许自动切换模式。
- `freshness`：各数据源最大允许年龄。
- `transitions`：模式间切换阈值。
- `recovery.lost_target`：丢目标后的正常恢复动作。

## missions/rescue_competition/config.yaml

比赛任务骨架配置。当前只提供框架，不代表已完成比赛自动化。

常用项：

```yaml
name: rescue_competition
initial_stage: PREPARE
auto_start: false
takeoff_altitude_m: 5.0
local_position_frame: 1
align_mode: OVERHEAD_HOLD
scan_duration_s: 3.0
land_complete_altitude_m: 0.3
route: []
drop_zones: []
recce_zones: []
payloads: []
```

- `auto_start`：默认 false，避免加载 rescue mission 后自动起飞。
- `route`：任务相对本地坐标航点，mission 会在开始时记录 EKF local origin。
- `payloads`：投放载荷列表，mission 只请求 `release_payload`，具体舵机/继电器映射仍属于 telemetry/action 层。
- `scan_duration_s`：侦察扫描占位阶段持续时间。
- `land_complete_altitude_m`：降落完成的相对高度阈值。

## missions/<mission_name>/config.yaml

mission 阶段控制器和通用控制参数。

主要分区：

- `input_adapter`：dt、age、低通滤波、target stable。
- `approach_track.gates`：斜视接近各控制通道放行条件。
- `approach_track.gimbal`：斜视接近云台控制参数。
- `approach_track.body`：斜视接近横移和机体偏航参数，`yaw_rate_damping` 用当前飞机 yaw 速率给偏航速率指令加阻尼，减小延迟导致的冲过。
- `approach_track.forward`：斜视接近前向速度参数。
- `overhead_hold.gates`：正上方悬停各控制通道放行条件。
- `overhead_hold.gimbal`：正上方悬停云台角度目标。
- `overhead_hold.lateral`：正上方悬停横向平移参数。
- `overhead_hold.longitudinal`：正上方悬停前后平移参数。
- `shaper`：最终命令限幅和 slew rate。

app 带 UI 运行时，修改本文件后可以在 UI 输入 `pid reload` 或 `stage reload`，将上述 mission stage 参数重载进当前进程。重载会更新正在运行的 controller，并重置积分/微分历史和 command shaper 状态；不会修改 YAML 文件。

## config/telemetry.yaml

MAVLink 连接、消息频率、超时和 UI 配置。

常用项：

```yaml
data_source: sitl
active_source: sitl

sitl:
  connection_type: tcp
  tcp_host: 127.0.0.1
  tcp_port: 5762

real:
  connection_type: eth
  serial_port: /dev/ttyUSB0
  baudrate: 57600
  eth_mode: udpin
  eth_host: 0.0.0.0
  eth_port: 15001
```

- SITL 端口需要和实际 `sim_vehicle.py` 输出一致。
- 实机可使用 `serial` 或 `eth`；ETH 直连 RK3588 网口时，通常让 RK3588 侧监听 `udpin:0.0.0.0:15001`，也可按飞控配置切到 `udpout` 或 `tcp`。
- `control_send_rate_hz` 控制连续命令最高发送频率。
- `request_message_intervals` 为 true 时会请求常用 MAVLink 消息频率。

## config/yolo.yaml

YOLO 感知配置，包含模型路径、视频源、UDP 输出目标、目标选择策略、显示和保存选项。

本地窗口和浏览器标注画面可独立启用：

```yaml
display:
  local_window_enabled: false
  fullscreen: false

web_stream:
  enabled: true
  host: "0.0.0.0"
  port: 8081
  jpeg_quality: 75
  max_fps: 20
```

注意保持 UDP 端口与 `config/app.yaml` 一致。

## Web 配置编辑

配置页只开放 `config/app.yaml`、`config/telemetry.yaml`、
`config/yolo.yaml` 和 `missions/*/config.yaml`。每次保存会写入同路径
`.bak` 作为上一次版本。

- 当前 mission 的“保存并应用”先关闭 `SEND`、清空连续命令，再热重载任务配置。
- telemetry 的“保存并重连”先关闭 `SEND`，再按新配置重建通信连接。
- YOLO 与 app 的“保存并重启”调用 `services_control` 中配置的命令。
- 应用、重连或重启之后 `SEND` 均保持关闭，必须人工重新开启。

## bool 配置规则

必须使用 YAML 原生 bool：

```yaml
true
false
```

不要写：

```yaml
"true"
"false"
ture
```

新 loader 对错误 bool 应明确报错，避免实机时误解配置。

## RK3588 真机与 SITL 切换

`config/*.yaml` 是程序直接读取并提交到 Git 的当前生效配置。切换运行环境时，
使用显式脚本覆盖 `config/telemetry.yaml` 和 `config/yolo.yaml`：

```bash
bash scripts/config/apply_rk3588_real.sh
bash scripts/config/apply_rk3588_sitl.sh
```

模板位于：

```text
config/profiles/rk3588-real/
config/profiles/rk3588-sitl/
```

两个脚本都会先检查 `config/app.yaml` 中 `executor.send_commands` 是否严格为
`false`。如果自动发送已开启，脚本拒绝切换配置。
