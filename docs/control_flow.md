# 控制数据流

本文描述从一帧 YOLO 输出到 MAVLink 命令的完整链路。

## 1. YOLO 输出

`yolo_app` 读取视频源，调用 Ultralytics YOLO 官方 tracking 和 ByteTrack，维护主目标，并通过 UDP JSON 输出。

典型字段：

```text
timestamp
frame_id
target_valid
tracking_state
track_id
class_name
confidence
cx/cy/w/h
image_width/image_height
target_size
ex/ey
lost_count
```

## 2. app 接收 YOLO

`app.service_manager.YoloUdpReceiver` 监听 `config/app.yaml` 中的：

```yaml
yolo_udp_ip
yolo_udp_port
```

并将 JSON 解码为 `fusion.models.PerceptionTarget`。

如果超时未收到 YOLO，`target_valid` 会置为 false。

## 3. telemetry 状态

`telemetry_link.LinkManager` 提供：

```python
get_latest_drone_state()
get_latest_gimbal_state()
get_link_status()
```

状态来自 `TelemetryReceiver -> StateCache`。

## 4. fusion

`FusionManager.update(perception, drone, gimbal)` 输出 `FusedState`。

融合层负责：

- 数据有效性。
- 目标状态。
- 云台状态。
- 机体姿态和速度。
- `control_allowed`。
- 相机误差和机体系误差。

融合层不负责：

- 任务切换。
- 速度控制。
- MAVLink 发送。

## 5. input adapter

`StageInputAdapter.adapt(fused)` 输出 `MissionStageInput`。

它负责：

- 计算 dt。
- 计算 source age。
- 判断 track switched。
- 判断 target stable。
- 对误差、云台角、目标尺度做一阶低通。

## 6. health monitor

`HealthMonitor.update(inputs)` 输出健康状态。

它负责：

- vision 是否 fresh。
- drone 是否 fresh。
- gimbal 是否 fresh。
- fusion 是否 ready。
- control 是否 ready。
- hold reason。

## 7. mission

`SystemRunner` 构造 `MissionContext`，再调用 `MissionRunner.update(context)`。当前 mission 输出 `MissionOutput`：

- `active_mode`：当前 mission 内 stage controller 的名字。
- `actions`：一次性或重复任务动作请求，例如 `takeoff`、`local_position`、`release_payload`。
- `stage` / `hold_reason` / `detail`：任务阶段和诊断信息。

典型流转：

```text
IDLE
  -> APPROACH_TRACK
  -> OVERHEAD_HOLD
  -> APPROACH_TRACK
```

`visual_tracking` mission 保留上述视觉跟踪流转。`rescue_competition` mission 是比赛任务骨架，按阶段请求起飞、航点、投放和降落动作。

mission 只决定流程、active stage 和通用 action，不直接发送 MAVLink。

## 8. mission stage controller

`StageRegistry.get(active_mode)` 取得当前 mission 对应阶段控制器，然后：

```python
raw_command, mode_status = mode.update(inputs)
```

`APPROACH_TRACK`：

- `ex_cam/ey_cam -> gimbal yaw/pitch rate`
- `ex_body -> vy`
- `gimbal_yaw -> yaw_rate`
- `target_size_ref - target_size -> vx`

`OVERHEAD_HOLD`：

- gimbal 进入模式后发送一次性 pitch 角度目标到正下方，yaw 保持当前角度。
- gimbal 到位后不再输出云台控制。
- `ex_cam -> vy`
- `ey_cam -> vx`

## 9. debug runtime

`DebugRuntime` 可覆盖：

- active mode。
- gimbal/body/approach 通道。
- command dry-run 语义。

## 10. command shaper

`CommandShaper.update(raw_command, dt)` 输出 shaped command。

它负责：

- 限幅。
- slew rate 平滑。
- disabled 通道归零。
- NaN/inf 归零。

## 11. executor

`FlightCommandExecutor.execute(shaped)` 将命令交给 `telemetry_link`。

body 通道：

```python
LinkManager.submit_control_command(ControlCommand(...))
```

gimbal 通道：

```python
LinkManager.send_gimbal_rate(...)
```

gimbal angle 动作通道：

```python
LinkManager.send_gimbal_angle(...)
```

如果 `send_commands=false`，只打印 dry-run 日志，不发送。

## 12. telemetry_link 发送

`CommandSender` 从队列取命令并发送：

- `ControlCommand` -> `SET_POSITION_TARGET_LOCAL_NED`
- `ActionCommand(GIMBAL_ANGLE)` -> `MAV_CMD_DO_MOUNT_CONTROL`
- `ActionCommand(SET_SERVO/SET_RELAY/RELEASE_PAYLOAD)` -> 通用动作封装
- `GimbalRateCommand` -> `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW`
- `ActionCommand` -> `COMMAND_LONG` 或 `COMMAND_INT`

断线时清空连续控制命令，避免恢复连接后发送旧命令。
