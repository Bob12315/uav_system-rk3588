# 当前架构裁决

本文记录当前可运行主线。与历史文档冲突时，以本文和实际代码为准。

## 唯一任务主线

```text
Web UI
  → WebServices facade / typed routers
  → Action Lab / Action Mission
  → ActionRuntimeService
  → ActionRunner
  → thin missions/common/actions/* adapters
  → guidance/* pure algorithms
  → ActionDispatcher
  → ActionSafetyPipeline
  → LinkManager
  → telemetry_link / MAVLink
```

- Action Mission 是当前唯一任务主线。
- Web UI 是当前唯一正式人工操作入口。
- `missions/common/actions/` 是 Action 实现位置。
- `config/action_missions/*.json` 是任务模板位置。
- `ActionDispatcher → ActionSafetyPipeline → LinkManager` 是当前实际发送链路。

## 模块边界

| 模块 | 当前职责 |
| --- | --- |
| `app/` | 4 个薄文件：入口、严格配置和 composition root |
| `application/` | 用例服务、运行状态、Mission 编排、WebServices 门面 |
| `missions/common/actions/` | 原子 Action 适配器；只管理生命周期和 typed effect |
| `missions/common/lifecycle/` | Action 生命周期状态；不拥有任务级子流程 |
| `guidance/` | 无全局状态、Web、telemetry 或发送依赖的纯算法 |
| `web_ui/` | FastAPI router、静态模块和唯一正式人工入口；只依赖 WebServices |
| `telemetry_link/` | VehicleStatePort/VehicleCommandPort、队列、MAVLink 封装和发送 |
| `fusion/` | 感知与飞控/云台状态融合，不发送命令 |
| `yolo_app/` | RKNNLite/NPU 感知和 UDP 输出，不连接 MAVLink |

旧 terminal/curses UI 已从仓库移除；相关仍在使用的共用逻辑位于 `app/`，不得重新建立
独立 terminal 人工操作入口。

## 已废弃旧主线

`MissionRunner → StageRegistry → FlightCommand → CommandShaper →
FlightCommandExecutor` 不是当前可运行主线，其依赖的大量 mission/stage/control
模块已经缺失。不得恢复或新增旧式 `missions/<mission>/mission.py`、
`missions/<mission>/stages/<stage>`。详见 [deprecated_paths.md](deprecated_paths.md)。

## Action-compatible safety pipeline

当前所有允许到达 `LinkManager` 的 Action request 都先经过 `ActionSafetyPipeline`。
它负责 run/source/telemetry/TTL 校验、安全包线、Field Reference 前置条件、payload
白名单和独立 BODY_NED deadman；裁决保留 original/effective/rejected request。
参数来源见 [`p0_security_decisions.md`](p0_security_decisions.md)。未经明确裁决不得恢复
已删除的旧控制栈。

## 当前任务编排边界

正式 catalog 只有 `drop_two_targets_v2`、`recon_gps_v2`、
`rescue_2026_full_auto_v2`。多视角飞行、双目标投放、侦察航迹和视觉降落均由模板中的
原子步骤表达；Action registry 不再发布复合 sequence/scan/visual-land Action。
Mission engine 是受限顺序编排器，提供保存结果、失败重试、条件跳转和 finally 等价的
明确返航/降落步骤，不是通用脚本语言。
