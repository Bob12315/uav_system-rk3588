# 2026 救援比赛 Action Mission

本文描述当前比赛任务主线。正式完整流程以
`config/action_missions/rescue_2026_full_auto.json` 和实际代码为准。

## 比赛任务目标

系统需要在同一次任务中完成：

1. 建立并冻结比赛 FIELD 坐标；
2. 起飞后在投放区多视角定位目标；
3. 选择两个有效目标，依次视觉对准并投放载荷；
4. 前往侦察区扫描危险标识并生成排名；
5. 返回起飞点，执行视觉辅助降落和 LAND 兜底。

FIELD 坐标中 `+Y` 为场地前方、`+X` 为场地右方，`altitude_m` 向上为正。
投放区和侦察区几何来自当前 Field Profile，不应在运行时代码中另写一套坐标。

## 当前完整流程

`rescue_2026_full_auto.json` 当前包含以下步骤：

```text
takeoff
→ 4 × (goto_waypoint → gps_capture_view)
→ gps_fuse_views
→ select_drop_targets
→ change_speed (1 m/s)
→ 2 × (goto_waypoint → gps_target_lock → align_descend → payload_release → goto_waypoint climb)
→ change_speed (2 m/s)
→ change_speed (1 m/s)
→ goto_waypoint (recon entry)
→ 5 × goto_waypoint
→ change_speed (2 m/s)
→ goto_waypoint (return home)
→ goto_waypoint (descend home)
→ target_lock (H)
→ align_descend
→ land
```

速度切换必须显式使用 `change_speed` Action。`goto_waypoint` 中的到点速度参数是完成
判据，不是飞行限速。

### 展开的 v2 Action 清单与失败分支

下表的序号就是 JSON 内的执行序；`continue` 只会前进到下一步，并不会把失败伪装成成功。

| # | label | Action | 失败策略 |
| ---: | --- | --- | --- |
| 1 | `takeoff_4_5m` | `takeoff` | fail |
| 2, 4, 6, 8 | `drop_scan_goto_1..4` | `goto_waypoint` | 最多 2 次，随后 `return_home_gps` |
| 3, 5, 7, 9 | `drop_scan_capture_1..4` | `gps_capture_view` | fail |
| 10 | `drop_scan_fuse` | `gps_fuse_views` | 最多 2 次，随后 `return_home_gps` |
| 11 | `select_gps_drop_targets` | `select_drop_targets` | `return_home_gps` |
| 12 | `drop_speed_1mps` | `change_speed` | fail |
| 13 | `drop_1_approach` | `goto_waypoint` | `restore_return_speed_2mps` |
| 14 | `drop_1_lock` | `gps_target_lock` | `restore_return_speed_2mps`；未确认指定 track 不下降 |
| 15 | `drop_1_align` | `align_descend` | `restore_return_speed_2mps` |
| 16 | `drop_1_release` | `payload_release`（SERVO9 1800→1600） | `restore_return_speed_2mps` |
| 17 | `drop_1_climb` | `goto_waypoint` | `restore_return_speed_2mps` |
| 18 | `drop_2_approach` | `goto_waypoint` | `restore_return_speed_2mps` |
| 19 | `drop_2_lock` | `gps_target_lock` | `restore_return_speed_2mps`；无第二目标时跳过下降与投放 |
| 20 | `drop_2_align` | `align_descend` | `restore_return_speed_2mps` |
| 21 | `drop_2_release` | `payload_release`（SERVO10 1800→1600） | `restore_return_speed_2mps` |
| 22 | `drop_2_climb` | `goto_waypoint` | `restore_return_speed_2mps` |
| 23 | `restore_transition_speed_2mps` | `change_speed` | fail |
| 24 | `recon_speed_1mps` | `change_speed` | fail |
| 25 | `goto_recon_entry_4m` | `goto_waypoint` | `restore_return_speed_2mps` |
| 26–30 | `recon_scan_goto_1..5` | `goto_waypoint` | `restore_return_speed_2mps` |
| 31 | `restore_return_speed_2mps` | `change_speed` | fail |
| 32 | `return_home_gps` | `goto_waypoint` | `land_home` |
| 33 | `descend_home_2_5m` | `goto_waypoint` | `land_home` |
| 34 | `final_land_lock_h` | `target_lock` / `class_single` | `land_home` |
| 35 | `final_land_align` | `align_descend` | `land_home` |
| 36 | `land_home` | `land` | fail |

## 模板定位

| 模板 | 用途 |
| --- | --- |
| `rescue_2026_full_auto.json` | 当前完整 GPS-first 比赛流程 |
| `drop_two_targets.json` | 双目标投放分项流程 |
| `recon_gps.json` | 侦察航点飞行分项流程 |

历史模板已删除，不参与正式运行 catalog 或默认 validator。

模板存在不代表已经通过实飞验收。正式比赛前必须在 Web UI 核对当前模板内容、场地
profile、速度、高度、SERVO 输出和失败恢复目标。

## SITL 固定下视相机与投放映射

`scripts/run_iris_gimbal_sitl.sh` 启动的世界使用
`iris_cuadc2026_fixed_down_camera`。其相机是固定下视、未镜像的 640 × 480 图像，10 Hz，
水平 FOV 为 2.0 rad（114.591559°）；按 4:3 图像比例推导的垂直 FOV 为 98.864783°。
因此两个投放模板中所有需要地面投影的 `gps_capture_view`、`gps_target_lock` 的 `camera`
参数均为（`final_land_lock_h` 也保留该值用于标定审计，但 `class_single` 不做地面投影）：

```json
{
  "fov_x_deg": 114.591559,
  "fov_y_deg": 98.864783,
  "image_x_sign": 1,
  "image_y_sign": -1
}
```

`align_descend` 使用 YOLO 的归一化 `ex/ey` 生成 BODY_NED 控制量，并根据当前高度、相机
FOV 和载荷相对相机的前/右安装偏移计算 `desired_ex/desired_ey`。PID 和下降/释放 deadband
使用 `ex-desired_ex`、`ey-desired_ey`，因此控制目标是让实际载荷释放点位于目标上方，
而不是让相机光轴位于目标上方。速度方向仍使用 `vx_sign=-1`、`vy_sign=1`。

Gazebo payload bridge 同时监听人工 RC 输入和飞控 SERVO 输出，但自动任务只允许后者：

| 载荷 | bridge 人工 RC 输入 | 自动任务 SERVO 输出 | PWM 时序 | Gazebo detach topic |
| --- | --- | --- | --- | --- |
| bottle1 / `payload_1` | RC13 | SERVO9 | 1600 → 1800 → 1600 | `/cuadc2026/payload/bottle1/detach` |
| bottle2 / `payload_2` | RC14 | SERVO10 | 1600 → 1800 → 1600 | `/cuadc2026/payload/bottle2/detach` |

RC13/14 是仿真 bridge 的人工触发输入，绝不是 Mission 的参数。`payload_release` 只经
`set_servo` 发送 `MAV_CMD_DO_SET_SERVO`；`config/safety.yaml` 只白名单化 SERVO9/10 的
1600--1800 PWM，禁止 RC override。

## 侦察、对准、投放原子 Action

每个 Action 的统一返回形状为 `done`、`failed`、`reason`、`output`、`detail` 和 typed
`actions`；Mission 只将有 `save_as` 的 `output` 放入 blackboard。

| 阶段 | Action 与运行方式 | 成功结果 | 失败与模板策略 |
| --- | --- | --- | --- |
| 四视角投放区侦察 | 依次运行 4 × `goto_waypoint` → `gps_capture_view`，再运行 `gps_fuse_views` → `select_drop_targets`。每个 capture 从当前 YOLO `scene.detections` 与捕获时 GPS/yaw/高度投影。 | capture: `gps_view_captured`，`output.raw_estimates`；fuse: `gps_views_fused`（也可能是空成功 `gps_views_fused_empty`），`localized_objects`；select: `selected_targets` / `target_slots`。 | 航点和融合最多两次，耗尽后跳 `return_home_gps`；目标选择失败直接返航。capture 本身是一次快照，不因空结果失败；之后由融合/选择决定是否继续。 |
| 目标复锁与对准下降 | 飞机先到融合 GPS 点上方 2.5 m，融合 GPS 到此只用于导航。每个目标运行 `gps_target_lock`，从桶类白名单且置信度不低于 0.75 的检测中直接选择距相机画面中心最近者；不做 GPS 投影距离门控，也不要求与融合目标类别一致。等待 YOLO 回报同一 track 已 locked 后，把 `locked_track_id` 显式传给 `align_descend`；对准只接受该 track 的未 stale `ex/ey`。 | lock: `gps_target_locked`，`output.locked_track_id`、`best_center_distance_norm`；align: 到释放高度且稳定对中时 `ready_to_release`，包含高度、`ex/ey`、速度、deadband 判定。 | lock 无桶目标、无 track、确认超时或无效 slot 均跳恢复速度，不进入对应下降/投放。align 对 track 不符、丢目标、stale、失高、无控制许可或超时均发零速并跳恢复速度。 |
| 投放 | `payload_release` 先生成一次 release PWM，在等待窗口维持零速，随后生成 hold PWM。 | 首 tick 为 `release_sent`，最终为 `payload_released`；`detail` 记录 payload/target ID、SERVO 输出、PWM、等待状态与零速命令。 | 模板的 `on_failed` 会跳 `restore_return_speed_2mps`，不尝试第二次释放同一载荷。但当前 ActionResult 没有 dispatch/bridge 回执：SEND、安全或传输拒绝记录在 `last_dispatch.skipped/errors`，仍可能得到 `payload_released`。因此必须同时确认 dispatch 为 accepted，以及 Gazebo bridge 的 `released bottle*` 日志；不能将该 reason 视为已实际脱钩。 |

连续的 `align_descend` 在停止、跳转、失败、丢失视觉或 telemetry stale 时都会发送显式零速，
并清除旧连续命令；这不能替代飞手或地面站接管。

投放对准段的有效参数是：目标高度 1.2 m、下降率 0.30 m/s、修正误差下降 deadband
`|error_ex|/|error_ey| ≤ 0.16`、释放 deadband `≤ 0.02`、水平 PID 增益 0.3 且限幅 0.25 m/s、
目标最大年龄 0.5 s、最大持续时间 30 s。到达目标高度后，目标必须持续处于释放
deadband 0.2 s 才会进入投放。H 点下降段使用相同的超时、目标新鲜度和确认时长，
但高度为 0.3 m、水平限幅及 deadband 为 0.3。`align_descend` 不支持分级/慢速下降、
高度增益、积分、按更新次数超时或“丢目标继续下降”；这些参数不得加入模板。

当前机械偏移初值为：`payload_1` 相对相机后方 0.06 m（`payload_forward_m=-0.06`），
`payload_2` 相对相机前方 0.06 m（`payload_forward_m=0.06`），两者横向偏移暂为 0。
小误差修正的最小有效速度为 0.035 m/s，防止 6 cm 偏移换算后的低速指令无法克服飞控死区。
这里的正方向是机体前方和右方，不是图像方向。正式实飞前应空载测量相机光轴到实际
释放点的水平距离并更新参数；不要通过反向修改 `vx_sign/vy_sign` 校正机械安装偏差。

> [!NOTE]
> `final_land_lock_h` 使用 `target_lock.acquire_mode=class_single`，不需要也不会构造
> LOCAL_NED `params.target`。它仅作为返航已到 home 后的 GPS 残差纠正：要求最新的有效 scene，
> `perception_status` 不 stale、年龄不超过 0.5 s，且恰好有一个置信度至少 0.35、带 track_id 与
> `ex/ey` 的 H 候选。Action 先返回 `target_lock_requested` 并派发一次 YOLO 锁定，再等待同一
> track 的 `target_valid=true` / `tracking_state=locked` 回执；只有收到回执才返回 `target_locked`
> 并把 `locked_track_id` 写入 `final_h_lock`。`final_land_align` 只接受这个 track。无 H、多 H、
> 过期感知或锁定回执不匹配会继续等待，超时则以
> `target_lock_timeout` 跳到 `land_home`，不会执行 H 标志视觉下降。
>
> `ActionRuntimeService` 现在会发布 `action_start_failed` 到 Mission，因而任何未来的启动失败也
> 不会残留前一个 `goto_waypoint` 的成功结果并错误前进。

## 运行架构

```text
Action Mission JSON
  → MissionOrchestrator
  → MissionBlackboard
  → ActionRuntimeService
  → ActionRunner
  → Action.update()
  → ActionResult
  → ActionDispatcher
  → LinkManager
  → Flight Controller / YOLO / Servo
```

Mission 和 Action 不得直接调用 pymavlink 或 `LinkManager`。飞控请求只允许经由
`ActionDispatcher` 派发；投放只允许走：

```text
payload_release → set_servo → MAV_CMD_DO_SET_SERVO
```

## Blackboard 数据流

Mission 步骤可用 `save_as` 保存 `ActionResult.output`，后续参数使用完整字符串 `$path`
读取。当前 v2 投放主线的主要数据流是：

```text
gps_capture_view save_as drop_scan_view_1..4
  → gps_fuse_views save_as drop_scan
  → drop_scan.localized_objects

select_drop_targets save_as drop_targets
  → drop_targets.target_slots

gps_target_lock save_as drop_1_lock / drop_2_lock
  → locked_track_id
  → align_descend(track_id=locked_track_id)
  → MissionOrchestrator 清理连续命令并保持位置
  → payload_release save_as drop_release_1..2
```

投放区融合除要求每个聚类至少 3 个有效观测外，还要求这些观测至少来自 3 个不同扫描
航点，避免单一画面内的重复框满足融合门槛。融合输出携带的总权重会参与同类别目标的
稳定排序。模板允许只选出一个目标，但缺失的第二 slot 会使复锁启动失败并直接跳到恢复
速度步骤，第二次下降和投放不会执行。

参数引用支持字典键和列表索引，例如：

```json
{
  "target": "$drop_targets.selected_targets.0"
}
```

当前只支持整个字符串为 `$path`，不支持把路径插入到其他字符串中。

## 步骤和失败策略

步骤基本结构：

```json
{
  "name": "action_name",
  "label": "optional_label",
  "save_as": "optional_blackboard_key",
  "params": {},
  "on_failed": {
    "action": "jump_to",
    "target": "recovery_label",
    "max_attempts": 1
  }
}
```

当前 orchestrator 的受限控制机制是顺序步骤、`save_as` 数据传递，以及 `fail`、
`retry_current`、`retry_current_then_jump_to`、`jump_to`、`continue`。循环展开为明确的有限
步骤，安全收尾由显式返航/降落标签承担，不提供通用脚本或旧 stage 类。调整恢复路径时必须确认：

- 失败 Action 的连续速度和 pending position 已停止、清除；
- 跳转目标不会重复投放同一载荷；
- 阶段限速在失败或跳转后得到恢复；
- 侦察失败仍能进入返航/降落安全路径；
- `payload_release` 失败不得被无条件忽略。

## 场地初始化和起飞前检查

当前完整 v2 模板使用 FIELD/GPS 派生坐标。任务启动前要求 Field Reference 已确认、
同步并冻结。Web UI 的 `Competition Field Setup` 使用 schema v3 流程：输入场地前向
标记点 GPS，在起飞点采集当前 GPS 样本，生成运行时原点和 heading，再冻结到本次任务。

schema v3 是比赛与 SITL 唯一受支持的场地流程。具体契约见
[场地原点与方向](field_origin_heading.md)。

## 安全门控

配置或加载 Mission 不发送飞行命令。实发至少需要：

1. `config/app.yaml` 中系统 `executor.send_commands` 已人工开启；
2. 当前 Action Mission 已建立绑定目标 source 的本次 run 授权；
3. telemetry、Field Reference 和相关 Action preflight 条件有效。

`SEND=OFF` 是默认状态。停止、跳过、失败或切换连续控制 Action 时必须明确发送
zero/stop 并清理旧命令。实机急停和最终接管依赖遥控器或地面站，不能只依赖停止 app。

## 验证顺序

```text
1. 当前主线单元/集成测试
2. Action Mission 模板离线校验
3. Web UI Configure 检查
4. SEND=OFF 完整干跑
5. SITL 低速 SEND=ON
6. 实机无载荷飞行
7. 挂载载荷但断开投放输出
8. 空载验证 SERVO 通道和 PWM
9. 正式载荷投放
```

离线校验：

```bash
python scripts/validate_action_missions.py
python scripts/validate_action_missions.py \
  config/action_missions/rescue_2026_full_auto.json
```

validator 不连接飞控，不验证识别精度、坐标标定、飞行安全或实机投放结果。

## 当前限制

- Mission 刻意保持受限顺序/失败分支模型，不提供通用脚本 DSL。
- 比赛参数仍需按正式场地、机体、相机和载荷进行现场标定。
- 危险标识排名依赖当前模型、阈值和观察点覆盖，不能只凭模板校验判定有效。
- Action 连续控制由 P0 Safety Pipeline 统一裁决。
- 报告结果可供 Web UI 和 blackboard 使用，但最终比赛交付形式仍需按规则确认。
