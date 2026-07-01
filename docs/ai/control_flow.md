# 当前控制与数据流

## 感知和状态

```text
camera → yolo_app/RKNNLite → UDP target + scene
                                  ↓
telemetry_link → Drone/Gimbal ─→ fusion → SystemRunner snapshot/context
```

YOLO 只负责感知；telemetry_link 只负责飞控通讯；fusion 不生成控制命令。

## Action Lab

```text
Web UI request
→ SystemRunner
→ ActionRuntimeService.start/tick
→ ActionRunner
→ missions/common/actions/<action>
→ ActionResult/action requests
→ ActionDispatcher
→ LinkManager
→ CommandSender
→ MAVLink
```

## Action Mission

```text
config/action_missions/*.json
→ MissionOrchestrator
→ current Action step
→ ActionRuntimeService
→ same dispatcher/send path as Action Lab
```

MissionOrchestrator 负责编排、黑板、重试和失败跳转；不会绕过 ActionRuntimeService。

## SEND 双门控

实发至少同时要求：

1. 系统 `send_commands`/SEND 开启；
2. Action 的 send-actions 请求开启。

配置任务、加载模板和 Field Reference UI 操作本身不应产生飞行运动命令。停止连续
BODY_NED 动作时必须发送 zero/stop 并清理旧连续命令。

## Field Reference

当前 SystemRunner 通过 RuntimeContextBuilder 提供 yaw-based FIELD 原点和方向；
FIELD Action 转为 LOCAL_NED 后才进入 dispatcher。后续将收敛为唯一
CoordinateTransform。未确认 Field Reference 时不得实发 FIELD 航点。

## 已废弃流程

MissionRunner/StageRegistry/FlightCommand/CommandShaper/FlightCommandExecutor 不是当前
可运行流程。不得为了让旧文档或旧测试通过而恢复该链路。
