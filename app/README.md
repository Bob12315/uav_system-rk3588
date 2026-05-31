# app

`app/` 是系统编排层，不写具体控制算法，也不直接构造 MAVLink 消息。

## 职责

- 加载总配置。
- 启动/停止服务。
- 调用 fusion。
- 适配 `FusedState -> MissionStageInput`。
- 运行 health monitor。
- 运行 mission runner。
- 调用当前 mission 的 active stage controller。
- 调用 command shaper 和 executor。
- 挂接 UI。

## 主要文件

- `main.py`：入口。
- `system_runner.py`：主循环。
- `service_manager.py`：YOLO UDP、telemetry、fusion 服务管理。
- `mission_runner.py`：调用当前 mission，并分发 `MissionAction`。
- `mission_manager.py`：旧视觉跟踪状态机兼容层。
- `health_monitor.py`：数据健康状态。
- `app_config.py`：加载 app 和 mission 配置；telemetry 配置复用 `telemetry_link.config`。
- `debug_runtime.py`：强制模式和通道覆盖。
- `stage_registry.py`：mission stage controller 注册。

## 禁止事项

- 不写控制公式。
- 不直接 import pymavlink。
- 不绕过 `FlightCommandExecutor`。
- 不在 mission / mission runner 里计算连续控制速度；这些放在 mission 自己的 `stages/` 里。

## 配置边界

- `config/app.yaml`：app 服务、UI、黑匣子和控制出口。
- `config/telemetry.yaml`：由 `telemetry_link.config` 统一解析，app 不重复定义解析规则。
- `config/yolo.yaml`：YOLO 进程及目标切换 UDP 配置。
- `missions/<mission_name>/config.yaml`：任务和 stage controller 参数。

旧 `control/` 配置入口已经移除。部署和调试统一使用根目录 `config/`。
