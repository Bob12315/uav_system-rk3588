# Rescue Competition Mission 功能说明

## 1. 模块定位

`rescue_competition` 是救援比赛任务的流程状态机。它负责决定当前任务阶段、
选择需要启用的 stage controller，并通过 `MissionAction` 请求一次性或重复动作。

本模块不直接连接 MAVLink，不直接调用 `telemetry_link.LinkManager`，也不计算连续
飞行控制量。所有动作由 `app.mission_runner.MissionRunner` 转发；视觉对准阶段使用
rescue 专用的 `FIXED_DOWNWARD_HOLD`，其 `FlightCommand` 仍需经过：

```text
MissionStage -> CommandShaper -> FlightCommandExecutor -> LinkManager -> MAVLink
```

主要文件：

```text
missions/rescue_competition/mission.py   状态机、配置 dataclass 和 YAML 装配
missions/rescue_competition/config.yaml  比赛任务参数和固定下视控制参数
missions/rescue_competition/stages/      rescue 专用 stage controller
missions/rescue_competition/__init__.py  对外导出
```

## 2. 总体流程

正常自动流程如下：

```text
PREPARE
  -> ARM
  -> TAKEOFF
  -> GOTO_DROPZONE
  -> DROP_SCAN
  -> DROP_ALIGN
  -> DROP_DESCEND
  -> DROP_RELEASE
  -> DROP_ASCEND
  -> DROP_RESUME_SCAN -> DROP_SCAN       未完成全部投放时
  -> GOTO_RECON                          完成全部投放后
  -> RECON_SCAN
  -> RECON_ALIGN
  -> RECON_DESCEND
  -> RECON_REPORT -> RECON_SCAN          发现侦察目标时
  -> RETURN_HOME                         扫描时间结束后
  -> LAND
  -> FINISH
```

异常配置或投放错误会进入：

```text
FAILSAFE
```

`FAILSAFE` 当前仅表示任务中止，并令 mission 输出 `aborted=true`。它不会自动发送
`LAND`、`LOITER` 或 `RTL`，安全接管仍由上层操作员、遥控器或地面站完成。

## 3. 阶段行为

| 阶段 | 核心行为 | 输出动作或 controller | 主要退出条件 |
| --- | --- | --- | --- |
| `PREPARE` | 等待本地位置和任务启动请求 | `gimbal_angle(pitch=-90)`，`once=true` | `auto_start=true` 或收到 `mission start` |
| `ARM` | 请求飞控解锁；解锁后记录任务原点和机头朝向 | `arm`，`once=true` | 遥测返回 `armed=true` 且本地位置有效 |
| `TAKEOFF` | 请求起飞 | `takeoff`，`once=true` | 相对高度达到起飞高度减容差 |
| `GOTO_DROPZONE` | 按 `route` 顺序飞到 `drop_route_end_name` | 重复 `local_position` | 航点位置和速度均稳定 |
| `DROP_SCAN` | 请求 `GUIDED`，按显式扫描点筛选投放目标 | `set_mode`、重复 `local_position` | 目标连续稳定出现，或扫描点耗尽 |
| `DROP_ALIGN` | 以载荷偏移修正相机误差，等待稳定对准 | `FIXED_DOWNWARD_HOLD` | 满足对准阈值并保持指定时间 |
| `DROP_DESCEND` | 保持对准并下降到最终投放高度 | `FIXED_DOWNWARD_HOLD`、重复 `local_position` | 位置稳定保持完成 |
| `DROP_RELEASE` | 执行舵机或继电器投放 | `set_servo` 或 `set_relay` | 动作提交后进入上升 |
| `DROP_ASCEND` | 等待投放动作，恢复舵机保持 PWM，上升到扫描高度 | 重复 `local_position`、`yolo_unlock_target` | 到达扫描高度 |
| `DROP_RESUME_SCAN` | 恢复投放扫描 | `IDLE` | 返回下一个未完成扫描点 |
| `GOTO_RECON` | 继续沿 `route` 飞到 `recce_route_end_name` | 重复 `local_position` | 航点稳定 |
| `RECON_SCAN` | 按显式扫描点累积圆筒和危险品检测 | `set_mode`、重复 `local_position` | 发现候选目标，或扫描点耗尽 |
| `RECON_ALIGN` | 等待视觉有效并短暂保持 | `FIXED_DOWNWARD_HOLD` | 保持完成，或视觉丢失 |
| `RECON_DESCEND` | 下降到识别高度 | `FIXED_DOWNWARD_HOLD`、重复 `local_position` | 位置稳定保持完成 |
| `RECON_REPORT` | 记录侦察目标位置、类别和置信度 | `IDLE` | 记录后返回扫描 |
| `RETURN_HOME` | 继续沿 `route` 飞到 `home_route_end_name` | 重复 `local_position` | home 航点稳定 |
| `LAND` | 请求降落 | `land`，`once=true` | 相对高度不高于完成阈值 |
| `FINISH` | 标记任务完成 | `IDLE`，`done=true` | 终态 |

## 4. 坐标与航线

`route` 使用相对于任务原点的本地 NED 坐标，单位为米。`ARM` 确认飞控已解锁且
本地位置有效时，记录位置和当时机头朝向。后续任务坐标会按该航向旋转到 EKF local
position：

```text
x：解锁时机头朝向为正
y：解锁时机头朝向右侧为正
z：NED 高度，向上为负
z=-5.0：任务原点上方 5 m
```

任务自动平移和视觉对准不会发送偏航角或偏航角速度控制，机头维持解锁/起飞时方向。

航点到达不仅检查 `xy_tolerance_m` 和 `z_tolerance_m`，还要求当前三轴合速度不超过
`max_speed_mps`。`route_hold_s` 可要求到点后继续稳定保持一段时间。

`drop_route_end_name`、`recce_route_end_name` 和 `home_route_end_name` 必须存在于
非空 `route` 中，否则加载配置时会报错。三个阶段共享 `_route_index`，因此路线应按
“投放区 -> 侦察区 -> home”的实际飞行顺序排列。

## 5. 投放目标与载荷

### 5.1 投放目标筛选

`DROP_SCAN` 从场景检测 `scene.detections` 中筛选目标：

- 类别属于 `drop_target_classes`。
- 置信度不低于 `drop_target_min_confidence`。
- 相机中心误差半径不超过 `drop_target_max_center_error`。
- 优先选择中心误差最小的候选。
- 同一目标连续出现至少 `drop_target_stable_frames` 帧。

有 `track_id` 时通过 id 判断是否为同一候选；没有 `track_id` 时使用类别和像素中心
距离近似判断。选中后 mission 请求 `yolo_lock_target`，投放后请求
`yolo_unlock_target`。

为减少重复投放，已投放位置会加入本地黑名单。无人机位于
`dropped_target_radius_m` 半径内时不会重新选择投放目标。

### 5.2 对准与偏移

任务启动后会通过一次性 `gimbal_angle` 动作将云台 pitch 设置为 `-90` 度垂直朝地。
投放对准使用 `FIXED_DOWNWARD_HOLD`。该控制器只根据 `ex_cam` / `ey_cam` 输出无人机
水平平移命令，显式保持机体偏航速率为零，不持续发送云台命令，也不要求云台反馈。
`DROP_ALIGN`、`DROP_DESCEND`、`RECON_ALIGN` 和 `RECON_DESCEND` 共用该控制器；下降
阶段的上下运动由 `local_position` 动作负责。救援任务的 `CommandShaper` 也将机体
偏航速率上限设为零。
每个 `payload_slots` 元素可设置：

```yaml
drop_center_x: 0.0
drop_center_y: 0.0
```

它们表示该载荷投放中心相对图像中心的归一化误差偏移。mission 将偏移放入
`MissionOutput.detail.target_error_offset`，由 `SystemRunner` 在进入
`FIXED_DOWNWARD_HOLD` 前从 `ex_cam` / `ey_cam` 中扣除。

### 5.3 投放动作

当前支持两种载荷释放方式：

```yaml
payload_slots:
  - id: 1
    servo_channel: 9
    release_pwm: 1900
    hold_pwm: 1100
```

以及显式继电器配置：

```yaml
payload_slots:
  - id: 2
    release:
      type: relay
      relay_id: 0
      state: true
```

舵机释放后，`DROP_ASCEND` 会在延迟结束后尝试发送 `hold_pwm`。继电器当前没有自动
反向复位动作。

## 6. 侦察结果

`RECON_SCAN` 同时做两件事：

- 使用危险品检测选择近距识别候选。
- 使用 `RecceAccumulator` 累积“圆筒内危险品标识”的投票。

投票逻辑按 `track_id` 聚合圆筒；缺少 `track_id` 时按类别和近似中心位置聚合。
危险品中心点必须位于圆筒 bbox 内。扫描结束后按 `vote_min_count` 和
`vote_min_confidence_sum` 判断结果为：

```text
confirmed   达到投票阈值
uncertain   有投票但未达到阈值
blank       圆筒内未识别出危险品
```

结果默认写入：

```text
runtime/logs/recce/recce_<timestamp>.json
runtime/logs/recce/recce_<timestamp>.csv
```

## 7. 动作出口与安全语义

mission 只生成 `MissionAction`。`MissionRunner` 根据 `send_actions` 决定是否转发：

| 动作 | 用途 |
| --- | --- |
| `takeoff` | 起飞 |
| `arm` | 解锁 |
| `gimbal_angle` | 任务启动后将云台一次性设置为垂直朝地 |
| `land` | 降落 |
| `local_position` | 本地 NED 航点 |
| `set_mode` | 切换飞控模式，扫描和对准阶段请求 `GUIDED` |
| `set_servo` | 舵机释放或恢复保持 PWM |
| `set_relay` | 继电器释放 |
| `yolo_lock_target` | 锁定投放目标 |
| `yolo_unlock_target` | 解除投放目标锁定 |

`config/app.yaml` 中必须保持：

```yaml
executor:
  send_commands: false
```

在 app 中，`actions_enabled` 与运行时 `SEND` 开关一致。`SEND=OFF` 时 action 只记录
`DRY action skipped`，不会发给飞控或 YOLO。

`dry_run_skip_payload_release=true` 只会在 `actions_enabled=false` 时模拟投放；
如果显式打开 `SEND`，mission 仍会按 `payload_slots` 请求真实舵机或继电器动作。

## 8. 配置分区

`config.yaml` 的主要分区：

| 分区 | 作用 |
| --- | --- |
| 顶层任务参数 | 初始阶段、自动启动、起飞高度、路线终点、dry-run 开关 |
| `route` | 顺序航点 |
| `drop.scan_route` | 投放区显式扫描航点 |
| `drop` | 投放数量、下降高度、上升高度和扫描超时 |
| `align` | 投放对准误差、目标状态、保持和超时 |
| `payload_release` | 释放动作后的等待时间 |
| `payload_slots` | 载荷 id、投放动作和图像投放中心偏移 |
| `recce` | 圆筒与危险品类别、投票阈值、扫描时长和输出目录 |
| `recon.scan_route` | 侦察区显式扫描航点 |
| `recon` | 侦察识别高度、保持时间和重复识别半径 |
| `input_adapter` | 输入滤波和 target stable 参数 |
| `fixed_downward_hold` | rescue 固定下视对准控制参数 |
| `shaper` | 最终命令限幅和平滑参数 |

默认 `config.yaml` 已启用 YOLO 视觉扫描，并保持 dry-run 投放：

```yaml
auto_start: false
dry_run_skip_vision: false
dry_run_skip_payload_release: true
drop_target_classes:
  - bucket
```

它会使用当前 RKNN 模型输出的 `bucket` 类别进入投放对准，但在 `SEND=OFF` 时不会执行
真实载荷释放。

## 9. 操作与诊断

常用 UI 命令：

```text
mission switch rescue_competition
mission start
mission status
mission stage <STAGE_NAME>
mission stage auto
mission reset
mode GUIDED
control send on
control send off
```

切换、重置 mission 或应用配置时，app 会关闭自动发送并清理连续控制状态。实发前应
再次确认飞控模式、路线、载荷通道和现场安全条件。正常启动顺序：

```text
mode GUIDED
control send on
mission start
```

`mission start` 不会自行打开 `SEND`。进入 `ARM` 后 mission 会请求解锁；如果
`SEND=OFF`，任务停在 `ARM` 并报告 `arm_actions_disabled`。

`MissionOutput.detail` 会提供：

```text
route_index
drop_scan_index
recon_scan_index
payload_index
drop_count
dropped_targets
reported_targets
selected_drop_target
target_error_offset
recce_observation_count
recce_confirmed_count
recce_results
recce_output_paths
```

## 10. 当前实现限制

以下字段已解析或保留，但当前状态机尚未完整使用：

- `drop_zones`、`recce_zones`：当前仅出现在诊断数量中，不参与区域判断。
- `drop.scan_speed_mps`、`recon.scan_speed_mps`：保留兼容；实际逐点速度阈值使用
  `scan_route[*].max_speed_mps`。
- `drop.intermediate_height_m`、`drop.descend_hold_s`：当前未参与下降流程。
- 顶层 `scan_duration_s`：主要作为旧配置兼容值；实际侦察扫描使用
  `recce.scan_duration_s`。
- YAML 中的 `recce.association_mode`：当前累积器固定使用“危险品中心位于圆筒
  bbox 内”的关联方式。

扫描轨迹由 YAML 中的 `drop.scan_route` 和 `recon.scan_route` 逐点明确配置。投放区
扫描完仍未发现目标时进入 `GOTO_RECON`；侦察区扫描完仍未发现危险品时写出结果并
进入 `RETURN_HOME`。`dry_run_skip_vision=true` 只跳过视觉候选，不会伪造目标或强行
进入对准阶段。

另外，`RECON_ALIGN` 当前只要求视觉新鲜且存在有效主目标，并按时间保持；它没有像
投放对准那样校验中心误差、锁定状态和稳定状态。实机近距侦察前应先在 SITL 和低速
环境中验证该行为。

## 11. 验证入口

任务单元测试：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_rescue_competition_mission.py \
  tests/test_mission_registry.py \
  tests/test_mission_runner.py \
  tests/test_recce_output.py
```

SITL 操作说明见：

```text
docs/user/rescue_competition_sitl.md
```
