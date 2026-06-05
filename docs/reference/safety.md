# 安全边界

本文用于 SITL 和实机前检查。任何改动如果影响这里的安全假设，必须更新本文。

## 默认安全策略

- `send_commands` 默认 false。
- telemetry 连接和命令发送是两个独立开关。是否连接由
  `services.connect_telemetry` 或 `--connect-telemetry` 决定。
- 不传 `--send-commands true` 时不发送连续控制命令。
- telemetry 断线时清空连续控制和云台速率命令。
- 数据不新鲜时 `HealthMonitor` 应阻止控制放行。
- `FlightCommandExecutor` 是唯一控制发送出口。

## 必须经过的控制链路

```text
MissionStage
  -> raw FlightCommand
  -> CommandShaper
  -> shaped FlightCommand
  -> FlightCommandExecutor
  -> LinkManager
  -> CommandSender
  -> MAVLink
```

任何绕过这条链路的改动都需要重新评审。

## send_commands

实机前必须确认：

```yaml
executor:
  send_commands: false
```

实发只能通过明确命令打开：

```bash
python -m app.main --connect-telemetry --send-commands true
```

## control_allowed

`control_allowed` 来自 telemetry/fusion 对飞控模式的判断。它必须只在安全控制模式下为 true。

如果飞控模式不允许控制：

- body 不应放行。
- approach 不应放行。
- shaped command 应归零或 disabled。

## YOLO 丢失

当 YOLO 超时或目标无效：

- `target_valid=false`。
- mode 不应输出有效跟踪命令。
- 默认不触发云台回中；如需搜索策略，必须显式配置打开。

需要确认：

- 丢目标不会继续前进。
- 丢目标不会保留旧速度。
- 丢目标不会自动把云台转到预设角度，除非已显式启用恢复动作。

## telemetry 丢失

当 heartbeat 或 RX 超时：

- `DroneState.connected=false`
- `DroneState.stale=true`
- `control_allowed=false`
- `GimbalState.gimbal_valid=false`
- `CommandSender` 停止发送连续控制。

## gimbal feedback 丢失

根据配置：

- gimbal 控制可不要求 gimbal fresh。
- body/approach 默认要求 gimbal fresh。

实机前确认对应 mode gating 配置保持保守，默认要求：

```yaml
require_gimbal_fresh_for_body: true
require_gimbal_fresh_for_approach: true
```

## 实机前 checklist

- 已在 SITL 中完成 dry-run。
- 已在 SITL 中完成低速实发。
- `max_vx/max_vy/max_yaw_rate` 已调成保守值。
- `send_commands` 默认 false。
- UI 或命令行能立即关闭控制发送。
- YOLO 断开时命令归零。
- telemetry 断开时命令停止。
- gimbal feedback 丢失时 body/approach 不误放行。
- 飞控处于正确模式。
- 螺旋桨/场地/遥控接管准备完成。

## 紧急处理

优先使用遥控器或地面站接管。软件侧可：

- 停止 app 进程。
- 在 UI 中关闭 send_commands。
- 发送 `mode LOITER`、`mode RTL`、`land` 等人工命令，前提是 telemetry 可用。

不要依赖单一软件停止路径作为唯一安全手段。
