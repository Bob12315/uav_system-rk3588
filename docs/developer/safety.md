# 安全边界

本文面向修改发送、限幅、停止、队列或门控逻辑的开发者。

本文描述当前真实发送链路和仍未解决的安全架构缺口。任何影响发送、限幅、停止、
队列或门控的修改都必须单独评审并先在 SITL 验证。

## 当前实际 Action 链路

```text
Action output
  → ActionRuntimeService
  → ActionDispatcher
  → LinkManager
  → telemetry_link CommandSender
  → MAVLink
```

旧 `MissionStage → FlightCommand → CommandShaper → FlightCommandExecutor` 不再是当前
可运行 Action 链路，不能继续把 FlightCommandExecutor 写成当前唯一出口。

## 已知安全架构缺口

旧文档依赖 CommandShaper/FlightCommandExecutor，但该管线不服务当前 Action 主线。
连续 BODY_NED/`flight_command` 需要新的 Action-compatible safety pipeline，或经过
评审并文档化的 dispatcher 层等价限幅、slew、NaN 防护和停止策略。

在明确裁决前：

- 不得恢复已删除的旧 control 栈。
- 不得声称当前连续命令已经拥有旧 shaper 的全部保证。
- 不得借重构改变飞控实发行为。

## SEND 双门控

系统默认：

```yaml
executor:
  send_commands: false
```

Action 实发至少同时要求：

1. 系统 SEND/`send_commands` 开启；
2. Action send-actions 请求开启。

加载模板、配置任务、查看状态和记录/确认 Field Reference 本身不得产生飞行运动
命令。连接 telemetry 不代表允许发送。

## 连续命令停止

- 停止、切换或失败退出连续 BODY_NED Action 时必须发送明确 zero/stop。
- 必须清理旧 continuous command 和 pending LOCAL_POSITION，避免恢复连接后重放。
- telemetry 断线、状态 stale 或控制不允许时必须停止连续发送。
- 丢失视觉目标不得沿用旧速度继续飞行。

## Field Reference

- 未确认 Field Reference 时必须拒绝实发 FIELD 航点。
- mission 执行中 FIELD origin/heading 冻结。
- yaw、GPS Home 或 EKF Origin 变化不能自动改写已确认 reference。
- GPS A/B 只辅助场地大方向；最终投放依赖视觉对准和激光高度。

## 投放

唯一允许主线：

```text
payload_release Action → set_servo → MAV_CMD_DO_SET_SERVO
```

SERVO 输出通道不是遥控器 RC 输入通道。禁止 `release_payload()`、RC override 和
直接 pymavlink。Action send-actions 开启但系统 SEND 关闭时仍不得调用 servo 实发。

## YOLO 与 telemetry 失效

- YOLO 超时：目标无效，跟踪/对准命令停止，不保留旧速度。
- telemetry heartbeat/RX 超时：connected=false、stale=true、control_allowed=false，
  CommandSender 停止连续控制。
- gimbal feedback 丢失时，依赖云台反馈的 Action 不得误放行。

## 实机前检查

- 已完成 dry-run 和 SITL 低速实发。
- `send_commands` 默认 false，双门控状态清楚。
- 坐标 frame、单位、正负号和 Field Reference 已确认。
- 速度、下降率和偏航参数保守。
- stop/zero、断线、丢目标和 stale 路径均已验证。
- payload SERVO 输出通道/PWM 已空载验证。
- 遥控器/地面站接管、场地和人员安全准备完成。

紧急情况优先使用遥控器或地面站接管；停止 app 只能作为辅助路径，不能成为唯一
安全手段。
