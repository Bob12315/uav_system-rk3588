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
  → LinkManager
  → telemetry_link / MAVLink
```

- Action Mission 是当前唯一任务主线。
- Web UI 是当前唯一正式人工操作入口。
- `missions/common/actions/` 是 Action 实现位置。
- `config/action_missions/*.json` 是任务模板位置。
- `ActionDispatcher → LinkManager` 是当前实际发送链路。

## 模块边界

| 模块 | 当前职责 |
| --- | --- |
| `app/` | 启动、服务编排、Action runtime、任务编排、状态快照和 Web UI 挂接 |
| `missions/common/actions/` | 可组合 Action 逻辑；输出结构化 action request，不构造 MAVLink |
| `web_ui/` | 正式人工操作、Action Lab、Action Mission、状态和配置页面 |
| `telemetry_link/` | 飞控状态、命令队列、MAVLink 封装和发送 |
| `fusion/` | 感知与飞控/云台状态融合，不发送命令 |
| `yolo_app/` | RKNNLite/NPU 感知和 UDP 输出，不连接 MAVLink |
| `uav_ui/` | deprecated terminal UI；部分共用工具尚待迁出 |

## 已废弃旧主线

`MissionRunner → StageRegistry → FlightCommand → CommandShaper →
FlightCommandExecutor` 不是当前可运行主线，其依赖的大量 mission/stage/control
模块已经缺失。不得恢复或新增旧式 `missions/<mission>/mission.py`、
`missions/<mission>/stages/<stage>`。详见 [deprecated_paths.md](deprecated_paths.md)。

## 已知安全架构缺口

当前 Action 连续命令由 `ActionDispatcher` 送入 `LinkManager`。旧文档中的
CommandShaper/FlightCommandExecutor 不再服务当前 Action 主线。后续需要明确新的
Action-compatible safety pipeline，或正式记录 dispatcher 层的等价限幅、停止和
门控方案；未经明确裁决不得恢复已删除的旧控制栈。
