# 当前接口契约

## ActionModule

Action 位于 `missions/common/actions/`，由 `ActionRunner` 调用：

```python
start(params)
update(context) -> ActionResult
stop()
reset()
```

`ActionResult` 可包含 `done`、`failed`、`reason`、`detail` 和结构化 `actions`。
Action 不直接发送 MAVLink。

## ActionRuntimeService

拥有 ActionRunner 和 ActionDispatcher，负责 start/tick/stop/reset。停止或切换导航类
Action 时负责清理连续命令和 pending LOCAL_POSITION，并按路径需要保持或发送 stop。

## MissionOrchestrator

读取 `config/action_missions/*.json` 对应步骤，负责顺序、标签跳转、重试、黑板
`save_as` 和失败策略。它只编排 Action，不构造 MAVLink。

## ActionDispatcher

接收 Action request，执行 Action send-actions 与系统 send-commands 双门控，并路由：

- `local_position`
- `body_velocity` / `flight_command`
- `set_servo`
- `set_mode` / `arm` / `takeoff` / `land`
- YOLO target command
- Field heading 确认（只记录内部状态，不发送飞行动作）

当前 dispatcher 调用 LinkManager 公开接口。连续命令的统一 shaping 是已知未决安全
项，不得声称旧 FlightCommandExecutor 仍在生效。

## Runtime context

context 包含 drone、gimbal、link、perception、scene、health、command，以及当前
Field Reference 第一版字段。坐标和字段命名见
[坐标系规范](../developer/coordinate_frames.md) 和
[action_contracts.md](action_contracts.md)。

## LinkManager

是 app/telemetry_link 边界，公开 local position、body velocity、arm/mode/takeoff/
land、gimbal、servo 等语义接口。只有 telemetry_link 构造 MAVLink message。

`release_payload()` 已禁用。投放必须由 `payload_release` Action 生成 `set_servo`
request，再由 dispatcher 调用 servo 接口。

## YOLO UDP

YOLO 发布 `target` 和 `scene.detections`。app 的 UDP receiver 解码为 fusion 数据模型。
字段兼容变更必须同步更新 publisher、receiver、Web UI 和测试。

## 单位

- 距离：m。
- 速度：m/s。
- app local/body yaw：rad；明确命名为 deg 的接口除外。
- PWM：飞控 SERVO 输出 PWM。
- LOCAL_NED：北/东/下。
- BODY_NED：前/右/下。
- FIELD：右/前，Web 地图右/上。
