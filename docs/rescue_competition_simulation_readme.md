# Rescue Competition SITL README

本文说明如何用仿真测试 `rescue_competition` mission，以及需要改哪些配置。默认工作目录：

```bash
cd /home/level6/uav_project/src
```

## 1. 测试目标

建议按三个阶段测试：

```text
阶段 A：只跑任务状态机，不连接/不控制飞控
阶段 B：连接 SITL，但 send_commands=false，只看任务和命令日志
阶段 C：连接 SITL，并 send_commands=true，让飞机按航道飞
```

不要一上来就开实发。先确认 mission 阶段、route、local position、日志都正常。

## 2. 关键文件

主要改这三个配置：

```text
src/config/app.yaml
src/config/telemetry.yaml
src/missions/rescue_competition/config.yaml
```

相关日志输出：

```text
runtime/logs/blackbox/
runtime/logs/recce/
```

## 3. app.yaml 怎么改

文件：

```text
src/config/app.yaml
```

默认如果还在视觉跟踪任务：

```yaml
mission:
  name: visual_tracking
```

要测试比赛任务，改成：

```yaml
mission:
  name: rescue_competition
```

建议保持：

```yaml
executor:
  send_commands: false
```

原因：不要在配置文件里默认实发。实发用命令行 `--send-commands true` 临时打开，更安全。

如果只是临时运行，也可以不改 `app.yaml`，直接用命令行：

```bash
python -m app.main \
  --mission-name rescue_competition \
  --mission-config missions/rescue_competition/config.yaml \
  --send-commands false
```

## 4. telemetry.yaml 怎么改

文件：

```text
src/config/telemetry.yaml
```

SITL 测试应使用：

```yaml
data_source: sitl
active_source: sitl
```

确认 SITL 端口：

```yaml
sitl:
  connection_type: tcp
  tcp_host: 127.0.0.1
  tcp_port: 5762
```

如果你的 SITL 是默认 `sim_vehicle.py` 端口，可能需要改成：

```yaml
tcp_port: 5760
```

判断方法：如果 app 日志一直显示连接失败，优先检查这里。

常用消息频率应包含：

```yaml
message_interval_hz:
  HEARTBEAT: 1
  ATTITUDE: 10
  GLOBAL_POSITION_INT: 10
  LOCAL_POSITION_NED: 10
  VFR_HUD: 5
  SYS_STATUS: 2
  GPS_RAW_INT: 2
```

`LOCAL_POSITION_NED` 很重要，mission 需要 `local_x/local_y/local_z` 判断是否到达航点。

## 5. rescue_competition.yaml 怎么改

文件：

```text
src/missions/rescue_competition/config.yaml
```

### 5.1 最小仿真配置

建议先这样：

```yaml
name: rescue_competition
initial_stage: PREPARE
auto_start: true
takeoff_altitude_m: 5.0
takeoff_altitude_tolerance_m: 0.5
local_position_frame: 1

dry_run_skip_vision: true
dry_run_skip_payload_release: true

drop_route_end_name: drop_center
recce_route_end_name: recce_center
home_route_end_name: home
```

含义：

```text
auto_start: true
  本地位置可用后自动进入 TAKEOFF。

dry_run_skip_vision: true
  暂时不等 YOLO 发现圆筒，到投放区后按时间模拟发现目标。

dry_run_skip_payload_release: true
  暂时不要求舵机/继电器投放配置，模拟投放完成。
```

### 5.2 航道 route

route 使用 mission-local NED 坐标：

```text
x/y 是任务原点下的水平位置，单位 m
z 是 NED 坐标，向上为负
z=-5.0 表示起飞点上方 5m
```

先用短路线测试：

```yaml
route:
  - name: takeoff_clear
    x: 3.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.0
    z_tolerance_m: 0.8
    max_speed_mps: 0.8

  - name: home
    x: 0.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.0
    z_tolerance_m: 0.8
    max_speed_mps: 0.8

drop_route_end_name: takeoff_clear
recce_route_end_name: takeoff_clear
home_route_end_name: home
```

短路线没问题后，再用完整路线：

```yaml
route:
  - name: takeoff_clear
    x: 3.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.0
    z_tolerance_m: 0.8
    max_speed_mps: 0.8

  - name: drop_entry
    x: 25.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.5
    z_tolerance_m: 0.8
    max_speed_mps: 0.8

  - name: drop_center
    x: 30.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.5
    z_tolerance_m: 0.8
    max_speed_mps: 0.8

  - name: recce_entry
    x: 50.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.5
    z_tolerance_m: 0.8
    max_speed_mps: 0.8

  - name: recce_center
    x: 55.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.5
    z_tolerance_m: 0.8
    max_speed_mps: 0.8

  - name: home
    x: 0.0
    y: 0.0
    z: -5.0
    xy_tolerance_m: 1.5
    z_tolerance_m: 0.8
    max_speed_mps: 0.8
```

完整路线对应：

```text
起飞 -> 3m 清场 -> 30m 投放区 -> 55m 侦察区 -> 回 home -> 降落
```

### 5.3 投放配置

如果只是仿真主线：

```yaml
dry_run_skip_payload_release: true
payloads: []
```

如果要测试舵机命令，不建议一开始就接真实硬件。SITL 中可先配置：

```yaml
dry_run_skip_payload_release: false

payloads:
  - payload_id: 1
    label: bottle_1
    release:
      type: servo
      channel: 9
      pwm: 1900
```

或继电器：

```yaml
payloads:
  - payload_id: 1
    label: bottle_1
    release:
      type: relay
      relay_id: 0
      state: true
```

实机前一定要确认通道号和 PWM，不要直接用示例值。

### 5.4 视觉开关

不接 YOLO 时：

```yaml
dry_run_skip_vision: true
```

接 YOLO 后：

```yaml
dry_run_skip_vision: false
```

并配置目标类别：

```yaml
drop_target_classes:
  - drop_cylinder
  - cylinder
  - target
drop_target_min_confidence: 0.45
drop_target_stable_frames: 5
drop_target_max_center_error: 0.35
```

类别名必须和 YOLO 模型输出一致。

## 6. 启动 SITL

如果用 Gazebo/ArduPilot，参考：

```bash
gz sim -v4 -r iris_runway.sdf
```

另一个终端：

```bash
sim_vehicle.py -D -v ArduCopter -f JSON \
  --add-param-file=$HOME/gz_ws/src/ardupilot_gazebo/config/gazebo-iris-gimbal.parm \
  --console
```

如果需要打开 Gazebo 相机流：

```bash
gz topic \
  -t /world/iris_runway/model/iris_with_gimbal/model/gimbal/link/pitch_link/sensor/camera/image/enable_streaming \
  -m gz.msgs.Boolean \
  -p "data: 1"
```

确认 SITL 端口和 `config/telemetry.yaml` 一致。

## 7. 运行命令

### 7.1 状态机 dry-run

不发飞控命令：

```bash
python -m app.main \
  --mission-name rescue_competition \
  --mission-config missions/rescue_competition/config.yaml \
  --no-ui \
  --no-yolo-udp \
  --send-commands false
```

可以加自动退出：

```bash
python -m app.main \
  --mission-name rescue_competition \
  --mission-config missions/rescue_competition/config.yaml \
  --no-ui \
  --no-yolo-udp \
  --send-commands false \
  --run-seconds 10
```

### 7.2 连接 SITL 但不发命令

```bash
python -m app.main \
  --mission-name rescue_competition \
  --mission-config missions/rescue_competition/config.yaml \
  --connect-telemetry \
  --no-ui \
  --no-yolo-udp \
  --send-commands false
```

看日志中是否有：

```text
source=sitl link ready
local_position_valid=True
mission=...
```

### 7.3 SITL 实发航道

确认前两步都正常后，再运行：

```bash
python -m app.main \
  --mission-name rescue_competition \
  --mission-config missions/rescue_competition/config.yaml \
  --start-auto-control \
  --connect-telemetry \
  --no-yolo-udp \
  --send-commands true \
  --no-ui
```

这会允许：

```text
MissionAction 实发：takeoff/local_position/land/set_servo/set_relay
FlightCommand 实发：OVERHEAD_HOLD 等连续控制
```

所以只在 SITL 中使用。

## 8. 接 YOLO 测试

先启动 YOLO：

```bash
conda activate yolo
cd /home/level6/uav_project/src/yolo_app
python -m yolo_app.main
```

确认 `config/yolo.yaml` 的 UDP 输出端口和 app 一致：

```yaml
udp_ip: "127.0.0.1"
udp_port: 5005
```

app 侧：

```yaml
runtime:
  yolo_udp_ip: "0.0.0.0"
  yolo_udp_port: 5005
```

然后把 mission 配置改成：

```yaml
dry_run_skip_vision: false
```

运行时去掉：

```text
--no-yolo-udp
```

命令示例：

```bash
python -m app.main \
  --mission-name rescue_competition \
  --mission-config missions/rescue_competition/config.yaml \
  --connect-telemetry \
  --send-commands false \
  --no-ui
```

先 `send_commands=false` 看目标发现和阶段切换，再考虑实发。

## 9. 日志怎么看

黑匣子：

```text
runtime/logs/blackbox/*.jsonl
```

侦察结果：

```text
runtime/logs/recce/
```

运行日志重点看：

```text
mission=<当前 active mode>
hold=<阶段原因>
target_valid=<是否有目标>
raw=...
shaped=...
```

MissionAction 日志如果已接入 UI/控制日志，会出现类似：

```text
DRY action skipped action=takeoff
TX action queued action=local_position
TX action queued action=set_servo
```

## 10. 常见问题

### 10.1 一直不自动起飞

检查：

```yaml
auto_start: true
```

检查 telemetry 是否有本地位置：

```text
LOCAL_POSITION_NED
local_position_valid
```

如果没有 local position，mission 会停在 `PREPARE`。

### 10.2 SITL 连不上

检查：

```yaml
data_source: sitl
active_source: sitl
sitl.tcp_port: 5762
```

如果不行，试：

```yaml
tcp_port: 5760
```

### 10.3 飞机不动

检查命令行是否有：

```bash
--send-commands true
--start-auto-control
--connect-telemetry
```

只传 `--start-auto-control` 不等于实发。必须显式 `--send-commands true`。

### 10.4 到投放区不继续

如果暂时不接 YOLO，确认：

```yaml
dry_run_skip_vision: true
```

如果接 YOLO，确认：

```yaml
drop_target_classes:
```

里的类别名和模型输出一致。

### 10.5 不投放

仿真跳过投放：

```yaml
dry_run_skip_payload_release: true
```

测试舵机/继电器：

```yaml
dry_run_skip_payload_release: false
payloads:
  - payload_id: 1
    release:
      type: servo
      channel: 9
      pwm: 1900
```

如果没有 payload 配置，mission 应该保持安全，不应假装投放完成。

## 11. 推荐测试顺序

```text
1. rescue_competition + send_commands=false + run-seconds 10
2. connect SITL + send_commands=false
3. 短 route + send_commands=true
4. 完整 route + send_commands=true
5. 接 YOLO + send_commands=false
6. 接 YOLO + SITL 实发
7. 最后才考虑实机
```

实机前必须重新检查：

```text
telemetry.yaml 是否切回 real
executor/send_commands 是否默认 false
payload 通道和 PWM 是否正确
安全开关是否可用
螺旋桨/电池/场地是否满足安全要求
```
