# app

`app/` 是系统编排层，不写具体控制算法，也不直接构造 MAVLink 消息。

## 职责

- 加载总配置。
- 启动/停止服务。
- 调用 fusion。
- 适配 `FusedState -> MissionStageInput`。
- 运行 Action Mission 编排与 P0 Safety Pipeline。
- 挂接 UI。

## 主要文件

- `main.py`：入口。
- `system_runner.py`：主循环。
- `service_manager.py`：YOLO UDP、telemetry、fusion 服务管理。
- `health_monitor.py`：数据健康状态。
- `app_config.py`：加载 app、telemetry、Web UI 和安全默认配置。

## 禁止事项

- 不写控制公式。
- 不直接 import pymavlink。
- 不绕过 `ActionDispatcher` 与 Safety Pipeline。

## 配置边界

- `config/app.yaml`：app 服务、UI、黑匣子和控制出口。
- `config/telemetry.yaml`：由 `telemetry_link.config` 统一解析，app 不重复定义解析规则。
- `config/yolo.yaml`：YOLO 进程及目标切换 UDP 配置。
- `config/action_missions/*.json`：Action Mission 模板。

旧 `control/` 配置入口已经移除。部署和调试统一使用根目录 `config/`。
