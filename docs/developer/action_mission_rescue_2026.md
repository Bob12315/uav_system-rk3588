# 2026 救援比赛 Action Mission

本文描述当前比赛任务主线。正式完整流程以
`config/action_missions/rescue_2026_full_auto_v2.json` 和实际代码为准。

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

`rescue_2026_full_auto_v2.json` 当前包含以下步骤：

```text
takeoff
→ gps_multi_view_localize
→ select_drop_targets
→ change_speed (1 m/s)
→ gps_drop_sequence
→ change_speed (2 m/s)
→ change_speed (1 m/s)
→ goto_waypoint (recon entry)
→ gps_recon_area_scan
→ change_speed (2 m/s)
→ goto_waypoint (return home)
→ goto_waypoint (descend home)
→ visual_land
→ land
```

速度切换必须显式使用 `change_speed` Action。`goto_waypoint` 中的到点速度参数是完成
判据，不是飞行限速。

## 模板定位

| 模板 | 用途 |
| --- | --- |
| `rescue_2026_full_auto_v2.json` | 当前完整 GPS-first 比赛流程 |
| `drop_two_targets_v2.json` | 双目标投放分项流程 |
| `recon_gps_v2.json` | 危险标识侦察分项流程 |
| `rescue_2026_full_auto.json` | 第一版完整流程，保留作回归参考 |
| `drop_two_targets_v1.json` | 第一版双投放流程，偏稳定性验证 |
| `recon_sequence_v1.json` | 第一版侦察组合流程 |
| `recon_inspect_5_targets_stepwise_v1.json` | 旧分步五目标检查流程 |
| `recon_inspect_5_targets_stepwise_v2.json` | 第二版分步侦察与报告流程 |

模板存在不代表已经通过实飞验收。正式比赛前必须在 Web UI 核对当前模板内容、场地
profile、速度、高度、SERVO 输出和失败恢复目标。

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

Mission 步骤可用 `save_as` 保存 `ActionResult.detail`，后续参数使用完整字符串 `$path`
读取。当前 v2 投放主线的主要数据流是：

```text
gps_multi_view_localize save_as drop_scan
  → drop_scan.localized_objects

select_drop_targets save_as drop_targets
  → drop_targets.selected_targets

gps_drop_sequence save_as drop_sequence
  → 双目标执行结果
```

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

当前 orchestrator 支持 `fail`、`retry_current`、`retry_current_then_jump_to`、
`jump_to` 和 `continue` 等模板已使用的策略。调整恢复路径时必须确认：

- 失败 Action 的连续速度和 pending position 已停止、清除；
- 跳转目标不会重复投放同一载荷；
- 阶段限速在失败或跳转后得到恢复；
- 侦察失败仍能进入返航/降落安全路径；
- `payload_release` 失败不得被无条件忽略。

## 场地初始化和起飞前检查

当前完整 v2 模板使用 FIELD/GPS 派生坐标。任务启动前要求 Field Reference 已确认、
同步并冻结。Web UI 的 `Competition Field Setup` 使用 schema v3 流程：输入场地前向
标记点 GPS，在起飞点采集当前 GPS 样本，生成运行时原点和 heading，再冻结到本次任务。

预采集的 schema v2 centerline profile 仍可用于固定场地和 SITL。两种流程的具体契约见
[场地原点与方向](field_origin_heading.md)。

## 安全门控

配置或加载 Mission 不发送飞行命令。实发至少需要：

1. `config/app.yaml` 中系统 `executor.send_commands` 已人工开启；
2. Action `send_actions` 请求已开启；
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
  config/action_missions/rescue_2026_full_auto_v2.json
```

validator 不连接飞控，不验证识别精度、坐标标定、飞行安全或实机投放结果。

## 当前限制

- Mission 还是顺序编排器，没有通用 if/else DSL。
- 比赛参数仍需按正式场地、机体、相机和载荷进行现场标定。
- 危险标识排名依赖当前模型、阈值和观察点覆盖，不能只凭模板校验判定有效。
- Action 连续控制尚缺完整替代旧 CommandShaper 的 safety pipeline。
- 报告结果可供 Web UI 和 blackboard 使用，但最终比赛交付形式仍需按规则确认。
