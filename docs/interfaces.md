# 接口契约

本文是新框架的公开接口说明。改代码时应优先保持这些接口稳定。

## 坐标、单位和约定

- 速度单位：`m/s`。
- 角速度单位：`rad/s`，进入 MAVLink gimbal manager 前由 `telemetry_link` 转成 `deg/s`。
- 云台角度状态：当前 `telemetry_link.GimbalState` 使用 `deg`；`fusion.FusedState.gimbal_yaw/gimbal_pitch` 和 mission stage 输入使用 `rad`，改单位前必须全链路同步。
- `vx_cmd`：机体系前向速度。
- `vy_cmd`：机体系横向速度，正方向由配置 `vy_sign` 和 MAVLink frame 定义。
- `vz_cmd`：机体系竖向速度，当前默认 0。
- `yaw_rate_cmd`：机体偏航角速度。
- `ex_cam/ey_cam`：相机归一化误差。
- `ex_body/ey_body`：机体系下的目标误差。
- `target_size`：目标尺度，来自 YOLO bbox 尺寸归一化结果。

## fusion.models.PerceptionTarget

用途：YOLO UDP JSON 解码后的主目标。

主要字段：

- `timestamp: float`：感知时间戳。
- `frame_id: int`：帧编号。
- `target_valid: bool`：当前是否有有效主目标。
- `tracking_state: str`：当前使用 `locked`、`lost`、`searching`；`fusion` 只把 `locked` 视为锁定目标。
- `track_id: int`：短时 IoU 关联生成的跨帧目标 id，无效时通常为 `-1`。
- `class_name: str`：类别名。
- `confidence: float`：检测置信度。
- `cx/cy/w/h: float`：bbox 几何量。
- `image_width/image_height: int | float`：图像尺寸。
- `target_size: float`：目标尺度。
- `ex/ey: float`：相机平面误差。
- `lost_count: int`：目标丢失计数。

创建链路：`yolo_app.CurrentTarget -> UDP JSON -> app.service_manager.YoloUdpReceiver -> PerceptionTarget`。

创建者：`app.service_manager.YoloUdpReceiver` 或 YOLO 兼容输入。

消费者：`fusion.FusionManager`。

## fusion.models.FusedState

用途：融合层输出的唯一上层状态。

主要字段：

- `timestamp`、`perception_timestamp`、`drone_timestamp`、`gimbal_timestamp`：各来源时间。
- `target_valid`、`target_locked`、`track_id`、`tracking_state`。
- `ex_cam`、`ey_cam`、`ex_body`、`ey_body`。
- `target_size`、`bbox_w`、`bbox_h`、`image_width`、`image_height`。
- `gimbal_valid`、`gimbal_yaw`、`gimbal_pitch`。
- `vision_valid`、`drone_valid`、`control_allowed`、`fusion_valid`。
- `roll`、`pitch`、`yaw`、`yaw_rate`。
- `vx`、`vy`、`vz`、`altitude`。

创建者：`fusion.fusion_manager.FusionManager.update()`。

消费者：`StageInputAdapter`。

## missions.common.control.types.MissionStageInput

用途：所有 mission stage controller 的统一输入。

字段：

- `timestamp: float`
- `dt: float`
- `fused_valid: bool`
- `target_valid: bool`
- `target_locked: bool`
- `vision_valid: bool`
- `drone_valid: bool`
- `gimbal_valid: bool`
- `control_allowed: bool`
- `track_id: int | None`
- `track_switched: bool`
- `target_stable: bool`
- `tracking_state: str`
- `ex_cam: float`
- `ey_cam: float`
- `ex_body: float`
- `ey_body: float`
- `gimbal_yaw: float`
- `gimbal_pitch: float`
- `yaw_rate: float`
- `target_size: float`
- `target_size_valid: bool`
- `fusion_age_s: float`
- `vision_age_s: float`
- `drone_age_s: float`
- `gimbal_age_s: float`

创建者：`StageInputAdapter.adapt(fused: FusedState)`。

消费者：`MissionManager`、`HealthMonitor`、所有 mission stage controller。

## missions.common.control.types.FlightCommand

用途：mission stage controller 输出和 command shaper 输出的统一控制命令。

字段：

- `vx_cmd: float`：前向速度，`m/s`。
- `vy_cmd: float`：横向速度，`m/s`。
- `vz_cmd: float`：竖向速度，`m/s`。
- `yaw_rate_cmd: float`：机体偏航角速度，`rad/s`。
- `gimbal_yaw_rate_cmd: float`：云台 yaw 角速度，`rad/s`。
- `gimbal_pitch_rate_cmd: float`：云台 pitch 角速度，`rad/s`。
- `gimbal_yaw_angle_cmd: float | None`：一次性云台 yaw 角度目标，`rad`；由 executor 转成 `deg` 后交给 `LinkManager.send_gimbal_angle()`。
- `gimbal_pitch_angle_cmd: float | None`：一次性云台 pitch 角度目标，`rad`；由 executor 转成 `deg` 后交给 `LinkManager.send_gimbal_angle()`。
- `enable_body: bool`：是否允许 body 通道。
- `enable_gimbal: bool`：是否允许 gimbal 通道。
- `enable_gimbal_angle: bool`：是否发送一次性云台角度动作命令。
- `enable_approach: bool`：是否允许 approach/vx 通道。
- `active: bool`：命令是否有活动通道。
- `valid: bool`：命令是否有效。

创建者：

- `missions/<mission_name>/stages/<stage_name>/mode.py` 创建 raw command。
- `CommandShaper.update()` 创建 shaped command。

消费者：

- `CommandShaper`
- `FlightCommandExecutor`
- `SystemRunner` 日志/UI。

规则：

- mission stage controller 不允许直接发送 `FlightCommand`。
- raw command 必须经过 `CommandShaper`。
- `valid=False` 时 executor 不应发送。
- disabled 通道的值应由 mode 或 shaper 归零。

## missions.common.control.types.MissionStageStatus

用途：说明 mode 当前状态，主要用于日志和 UI。

字段：

- `mode_name: str`：模式名。
- `active: bool`：模式是否处于活动控制状态。
- `valid: bool`：模式输出是否有效。
- `hold_reason: str`：未放行或保持的原因。
- `detail: dict[str, object]`：可选调试信息。

## missions.base_stage.MissionStage

接口：

```python
class MissionStage(Protocol):
    name: str

    def reset(self) -> None:
        ...

    def update(self, inputs: MissionStageInput) -> tuple[FlightCommand, MissionStageStatus]:
        ...
```

实现者：

- `ApproachTrackMode`
- `OverheadHoldMode`
- `CorridorFollowMode`

禁止：

- `update()` 内不得发送 MAVLink。
- `update()` 内不得读 YAML。
- `update()` 内不得启动线程或 socket。

## telemetry_link.models.DroneState

用途：飞控状态缓存。

主要字段：

- `connected: bool`
- `stale: bool`
- `armed: bool`
- `mode: str`
- `control_allowed: bool`
- `attitude_valid`、`velocity_valid`、`altitude_valid`
- `roll`、`pitch`、`yaw`
- `roll_rate`、`pitch_rate`、`yaw_rate`
- `vx`、`vy`、`vz`
- `altitude`、`relative_altitude`
- `lat`、`lon`
- `battery_voltage`、`battery_remaining`
- `gps_fix_type`、`satellites_visible`
- `hb_age_sec`、`rx_age_sec`

创建者：`telemetry_link.StateCache`。

消费者：`fusion.FusionManager`、UI、日志。

## telemetry_link.models.GimbalState

用途：云台状态缓存。

字段：

- `timestamp: float`
- `gimbal_valid: bool`
- `yaw: float`
- `pitch: float`
- `roll: float`
- `source_msg_type: str`
- `last_update_time: float`
- `raw_quaternion: tuple[float, float, float, float] | None`

创建者：`TelemetryReceiver`。

消费者：`fusion.FusionManager`。

## telemetry_link.models.ControlCommand

用途：连续机体控制命令，由 executor 提交给 telemetry。

字段：

- `command_type: ControlType`
- `vx: float`
- `vy: float`
- `vz: float`
- `yaw_rate: float`
- `timestamp: float`
- `frame: int`

创建者：`FlightCommandExecutor`。

消费者：`LinkManager.submit_control_command()`。

## telemetry_link.link_manager.LinkManager

核心方法：

```python
start() -> None
start_background() -> threading.Thread
stop() -> None
get_active_source() -> str
switch_active_source(source_name: str) -> bool
get_latest_drone_state() -> DroneState
get_latest_gimbal_state() -> GimbalState
get_link_status() -> LinkStatus
get_source_state(source_name: str) -> DroneState
get_source_gimbal_state(source_name: str) -> GimbalState
get_source_link_status(source_name: str) -> LinkStatus
is_connected() -> bool
submit_control_command(command: ControlCommand) -> None
submit_action_command(command: ActionCommand) -> None
send_gimbal_rate(yaw_rate: float, pitch_rate: float, ...) -> None
send_gimbal_angle(pitch: float, yaw: float, roll: float = 0.0, ...) -> None
stop_control(frame: int = 1) -> None
clear_continuous_commands() -> None
set_mode(mode: str) -> None
arm() -> None
disarm() -> None
takeoff(altitude_m: float) -> None
land() -> None
```

使用规则：

- `app.ServiceManager` 持有 `LinkManager`。
- `FlightCommandExecutor` 只通过公开方法提交命令。
- mission stage controller 不直接持有 `LinkManager`。
- `start()` 启动各 source 的后台连接/监控线程并返回，不应等待 heartbeat 成功。
- `start_background()` 保留给嵌入 app 的异步启动路径。
- `switch_active_source()` 只切换对外状态和后续命令提交目标；切换时所有 source 的连续控制队列必须清空，避免重新激活旧控制量。

## app.service_manager.ServiceManager

用途：服务生命周期管理。

核心方法：

```python
start() -> None
stop() -> None
get_perception(now: float) -> PerceptionTarget
get_drone_state() -> DroneState
get_gimbal_state() -> GimbalState
```

职责：

- 启动 YOLO UDP receiver。
- 创建/启动 `LinkManager`。
- 持有 `FusionManager`。

禁止：

- 不计算控制律。
- 不决定 mission 阶段。

## missions.Mission / app.mission_runner.MissionRunner

用途：任务阶段状态机和任务动作分发。

输入：

- `MissionContext`

输出：

- `MissionOutput.active_mode`，例如 `IDLE`、`APPROACH_TRACK`、`OVERHEAD_HOLD`。
- `MissionOutput.actions`，例如 `takeoff`、`land`、`local_position`、`release_payload`。
- `stage`、`hold_reason` 和 `detail`。

禁止：

- 不计算速度。
- mission 不直接发送命令。
- action 由 `MissionRunner` 经 `LinkManager` 转发。

## app.health_monitor.HealthMonitor

用途：判断数据健康状态。

输出典型字段：

- `vision_fresh`
- `drone_fresh`
- `gimbal_fresh`
- `fusion_ready`
- `control_ready`
- `hold_reason`

禁止：

- 不切换 mission。
- 不生成控制命令。
