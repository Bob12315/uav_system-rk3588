# 当前架构裁决

本文记录当前可运行主线。与历史文档冲突时，以本文和实际代码为准。

## 唯一任务主线

```text
Web UI
  → Action Lab / Action Mission
  → ActionRuntimeService
  → ActionRunner
  → missions/common/actions/*
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
| `app/` | 启动、服务编排、Action runtime、任务编排、状态快照和 Web UI 挂接 |
| `missions/common/actions/` | 可组合 Action 逻辑；输出结构化 action request，不构造 MAVLink |
| `web_ui/` | 正式人工操作、Action Lab、Action Mission、状态和配置页面 |
| `telemetry_link/` | 飞控状态、命令队列、MAVLink 封装和发送 |
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
